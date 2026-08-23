"""Speaking as a role: the key on disk, the JWT, the token, and where it may travel."""

from __future__ import annotations

import ast
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from my_team.core.config import KEY_MODE, RoleConfig
from my_team.credentials import (
    TOKEN_VARIABLE,
    AppApiError,
    CredentialError,
    app_get,
    app_jwt_for,
    installation_token,
    key_file,
    key_mode,
    read_private_key,
    token_env,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

ROLE = RoleConfig(
    app_id=4652114,
    bot_user_id=318751706,
    installation_id=155006997,
    key_path=Path("~/.config/my-team/keys/implementer.pem"),
)


def a_key(tmp_path: Path, body: str, *, mode: int = KEY_MODE) -> Path:
    path = tmp_path / "implementer.pem"
    path.write_text(body)
    path.chmod(mode)
    return path


def role_with_key(path: Path) -> RoleConfig:
    return RoleConfig(
        app_id=ROLE.app_id,
        bot_user_id=ROLE.bot_user_id,
        installation_id=ROLE.installation_id,
        key_path=path,
    )


class Response(io.BytesIO):
    """What `urlopen` yields: a context manager over the body."""

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class Api:
    """Stands in for `urlopen`, recording the request and replying with `body`."""

    def __init__(self, body: object) -> None:
        self.body = body
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Response:
        self.requests.append(request)
        return Response(json.dumps(self.body).encode())


# ── The key on disk ──────────────────────────────────────────────────────────────


def test_the_key_path_is_expanded_where_it_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/mcnewcp")

    assert key_file(ROLE) == Path("/home/mcnewcp/.config/my-team/keys/implementer.pem")


def test_a_missing_key_has_no_mode(tmp_path: Path) -> None:
    assert key_mode(tmp_path / "absent.pem") is None


def test_a_present_key_reports_its_permission_bits(tmp_path: Path, rsa_pem: str) -> None:
    assert key_mode(a_key(tmp_path, rsa_pem, mode=0o644)) == 0o644


def test_a_key_at_0600_is_read(tmp_path: Path, rsa_pem: str) -> None:
    assert read_private_key(a_key(tmp_path, rsa_pem)) == rsa_pem


def test_a_missing_key_is_refused_by_path(tmp_path: Path) -> None:
    with pytest.raises(CredentialError, match=str(tmp_path / "absent.pem")):
        read_private_key(tmp_path / "absent.pem")


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o660, 0o777])
def test_a_key_that_is_not_0600_is_refused_rather_than_merely_reported(
    tmp_path: Path, rsa_pem: str, mode: int
) -> None:
    # `doctor` reports the mode; this is the refusal, so a run that skipped `doctor`
    # cannot quietly use a world-readable key.
    with pytest.raises(CredentialError, match=f"{mode:04o}"):
        read_private_key(a_key(tmp_path, rsa_pem, mode=mode))


def test_the_jwt_is_signed_with_the_key_on_disk(tmp_path: Path, rsa_pem: str) -> None:
    token = app_jwt_for(role_with_key(a_key(tmp_path, rsa_pem)), now=1_755_000_000)

    assert len(token.split(".")) == 3


def test_a_role_whose_key_is_unusable_cannot_mint_a_jwt(tmp_path: Path, rsa_pem: str) -> None:
    with pytest.raises(CredentialError):
        app_jwt_for(role_with_key(a_key(tmp_path, rsa_pem, mode=0o644)), now=1)


# ── Speaking to GitHub as the App ────────────────────────────────────────────────


def test_a_get_carries_the_bearer_jwt_gh_cannot_send(monkeypatch: pytest.MonkeyPatch) -> None:
    api = Api({"slug": "implementer-my-team"})
    monkeypatch.setattr(urllib.request, "urlopen", api)

    assert app_get("a.b.c", "/app") == {"slug": "implementer-my-team"}
    request = api.requests[0]
    assert request.full_url == "https://api.github.com/app"
    assert request.get_header("Authorization") == "Bearer a.b.c"
    assert request.get_header("X-github-api-version") == "2022-11-28"
    assert request.get_method() == "GET"


def test_a_refusal_keeps_its_status_so_a_404_can_be_told_from_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise urllib.error.HTTPError(
            url="https://api.github.com/app/installations/1",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"message": "Not Found"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(AppApiError) as caught:
        app_get("a.b.c", "/app/installations/1")

    assert caught.value.status == 404
    assert "Not Found" in str(caught.value)


def test_an_unreachable_github_is_an_error_about_the_run_not_about_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(*_: object, **__: object) -> None:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)

    with pytest.raises(CredentialError) as caught:
        app_get("a.b.c", "/app")

    assert not isinstance(caught.value, AppApiError)
    assert "could not reach GitHub" in str(caught.value)


def test_minting_a_token_posts_to_the_role_s_own_installation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rsa_pem: str
) -> None:
    api = Api({"token": "ghs_abc", "expires_at": "2026-08-23T13:00:00Z"})
    monkeypatch.setattr(urllib.request, "urlopen", api)

    minted = installation_token(role_with_key(a_key(tmp_path, rsa_pem)), now=1_755_000_000)

    assert api.requests[0].full_url == (
        "https://api.github.com/app/installations/155006997/access_tokens"
    )
    assert api.requests[0].get_method() == "POST"
    assert minted.token == "ghs_abc"
    assert minted.expires_at == "2026-08-23T13:00:00Z"


# ── Where a token may travel ─────────────────────────────────────────────────────


def test_a_token_travels_as_gh_token_and_nothing_else() -> None:
    assert token_env("ghs_abc") == {TOKEN_VARIABLE: "ghs_abc"}


def test_gh_auth_switch_is_never_called_anywhere() -> None:
    """It mutates a config file every concurrent tick shares, so it races.

    Asserted over the source rather than trusted to memory, because it is the obvious
    tool to reach for and the failure it causes is intermittent. Prose *about* the rule
    is not a breach of it, so what is searched for is the call: a `"switch"` argument in
    Python, and an uncommented `gh auth switch` in a shell script.
    """
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in (REPO_ROOT / "src").rglob("*.py")
        if any(
            isinstance(node, ast.Constant) and node.value == "switch"
            for node in ast.walk(ast.parse(path.read_text()))
        )
    ]
    offenders += [
        path.relative_to(REPO_ROOT)
        for path in (REPO_ROOT / "scripts").rglob("*.sh")
        if any(
            "gh auth switch" in line and not line.lstrip().startswith("#")
            for line in path.read_text().splitlines()
        )
    ]

    assert not offenders, f"`gh auth switch` mutates global state and races: {offenders}"
