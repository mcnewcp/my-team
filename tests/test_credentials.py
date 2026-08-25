"""Speaking as a role: the key on disk, the JWT, the token, and where it may travel."""

from __future__ import annotations

import ast
import http.client
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from my_team.core.app_jwt import app_jwt
from my_team.core.config import KEY_MODE, RoleConfig
from my_team.credentials import (
    TOKEN_VARIABLE,
    AppApiError,
    CredentialError,
    InstallationToken,
    app_get,
    app_jwt_for,
    installation_token,
    key_file,
    key_mode,
    read_private_key,
    repo_containing,
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


def a_repo(root: Path, marker: str = "") -> Path:
    """A work tree at `root`, marked the way git marks one."""
    root.mkdir(parents=True, exist_ok=True)
    if marker:
        (root / ".git").write_text(marker)
    else:
        (root / ".git").mkdir()
    return root


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


def test_a_key_outside_every_repository_sits_in_none(tmp_path: Path) -> None:
    assert repo_containing(tmp_path / "keys" / "implementer.pem") is None


def test_a_key_under_a_repository_names_the_work_tree_it_is_in(tmp_path: Path) -> None:
    root = a_repo(tmp_path / "clone")

    assert repo_containing(root / ".my-team" / "implementer.pem") == root


def test_a_linked_worktree_is_a_repository_too(tmp_path: Path) -> None:
    # A `git worktree` — and a submodule — carries `.git` as a *file* pointing at the
    # real directory. Both stage a key just as readily, so what is there is what counts
    # rather than whether it is a directory.
    root = a_repo(tmp_path / "worktree", marker="gitdir: /elsewhere/.git/worktrees/w\n")

    assert repo_containing(root / "keys" / "judge.pem") == root


def test_the_nearest_enclosing_repository_is_the_one_named(tmp_path: Path) -> None:
    outer = a_repo(tmp_path / "outer")
    inner = a_repo(outer / "vendor" / "inner", marker="gitdir: ../../.git/modules/inner\n")

    assert repo_containing(inner / "reviewer.pem") == inner


def test_a_key_symlinked_into_a_repository_is_inside_it(tmp_path: Path) -> None:
    # The file `git add .` would stage is the one at the end of the link, so the link is
    # followed before the question is asked.
    root = a_repo(tmp_path / "clone")
    (root / "implementer.pem").write_text("-----BEGIN RSA PRIVATE KEY-----")
    outside = tmp_path / "implementer.pem"
    outside.symlink_to(root / "implementer.pem")

    assert repo_containing(outside) == root


def test_a_key_behind_a_directory_that_will_not_open_is_inside_no_repository(
    tmp_path: Path,
) -> None:
    # Looking for a `.git` means stat'ing inside, and a directory that refuses answers
    # with an error rather than with a "no". `doctor` asks before it knows whether there
    # is a key there at all, so the error has to become the answer.
    closed = tmp_path / "closed"
    closed.mkdir(mode=0o600)
    try:
        assert repo_containing(closed / "implementer.pem") is None
    finally:
        closed.chmod(0o700)


def test_a_key_inside_a_repository_is_refused_even_at_0600(tmp_path: Path, rsa_pem: str) -> None:
    # No file mode prevents what is wrong with it: a key inside a work tree is one
    # `git add .` from being published. `doctor` reports it; this is the refusal.
    root = a_repo(tmp_path / "clone")

    with pytest.raises(CredentialError, match="outside every repo"):
        read_private_key(a_key(root, rsa_pem))


def test_a_key_inside_a_repository_that_doctor_never_saw_is_refused_all_the_same(
    tmp_path: Path, rsa_pem: str
) -> None:
    # `doctor` runs in one repo; this key is under another. Both are work trees, and the
    # invariant is outside *every* repo rather than outside the one being diagnosed.
    other = a_repo(tmp_path / "some-other-clone")

    with pytest.raises(CredentialError, match=str(other)):
        read_private_key(a_key(other, rsa_pem))


def test_a_key_inside_a_repository_is_refused_by_location_before_its_mode(
    tmp_path: Path, rsa_pem: str
) -> None:
    # Both are wrong, and only one of them `chmod` fixes.
    root = a_repo(tmp_path / "clone")

    with pytest.raises(CredentialError, match="outside every repo"):
        read_private_key(a_key(root, rsa_pem, mode=0o644))


@pytest.mark.parametrize("mode", [0o600, 0o700])
def test_a_directory_where_the_key_should_be_is_no_key_rather_than_a_key(
    tmp_path: Path, mode: int
) -> None:
    """Permission bits alone would let a `0600` directory through the mode check.

    Whatever came next would then be an `IsADirectoryError` out of a read, which is a
    crash where the whole point is a named precondition. Only a regular file is a
    candidate for being a key.
    """
    directory = tmp_path / "implementer.pem"
    directory.mkdir(mode=mode)

    assert key_mode(directory) is None
    with pytest.raises(CredentialError, match="no private key"):
        read_private_key(directory)


def test_a_path_the_filesystem_will_not_stat_is_no_key_either(tmp_path: Path) -> None:
    # A symlink loop answers neither "here it is" nor "it is not there" — it raises. A
    # key that cannot be reached is a key that is not there, and saying so beats a
    # traceback out of a diagnostic.
    (tmp_path / "a.pem").symlink_to(tmp_path / "b.pem")
    (tmp_path / "b.pem").symlink_to(tmp_path / "a.pem")

    assert key_mode(tmp_path / "a.pem") is None


def test_a_key_that_is_not_text_is_refused_by_name_rather_than_raised_through(
    tmp_path: Path,
) -> None:
    # GitHub hands out PEM, but a downloaded DER — or any truncated binary — sits at the
    # same path with the same mode, and decoding it must fail the way every other
    # unusable key does.
    binary = tmp_path / "implementer.pem"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    binary.chmod(KEY_MODE)

    with pytest.raises(CredentialError, match=str(binary)):
        read_private_key(binary)


def test_the_jwt_is_signed_with_the_key_on_disk(tmp_path: Path, rsa_pem: str) -> None:
    """The file at `key_path` is the one that signs, and nothing else is.

    Asserted by signing the same bytes directly: PKCS#1 v1.5 is deterministic, so an
    identical token is the proof that the key came off disk. What a signature is *worth*
    is `tests/test_app_jwt.py`'s question, and it asks openssl.
    """
    signed = app_jwt_for(role_with_key(a_key(tmp_path, rsa_pem)), now=1_755_000_000)

    assert signed == app_jwt(rsa_pem, app_id=ROLE.app_id, now=1_755_000_000)


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


def test_a_refusal_with_a_truncated_body_keeps_its_status_and_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TruncatedErrorBody(Response):
        def read(self, *_: object) -> bytes:
            raise http.client.IncompleteRead(b"{")

    def refuse(*_: object, **__: object) -> None:
        raise urllib.error.HTTPError(
            url="https://api.github.com/app",
            code=503,
            msg="Service Unavailable",
            hdrs=None,  # type: ignore[arg-type]
            fp=TruncatedErrorBody(b""),
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(AppApiError) as caught:
        app_get("a.b.c", "/app")

    assert caught.value.status == 503
    assert caught.value.path == "/app"


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


def test_a_minted_token_never_appears_in_its_own_representation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rsa_pem: str
) -> None:
    """`InstallationToken` says it is never logged, so the default `repr` cannot hold it.

    A dataclass prints every field, and `repr` is what a failed assertion, a traceback
    frame and an idle `print` all reach for — so the invariant has to be a property of
    the type rather than of everyone who handles one.
    """
    monkeypatch.setattr(
        urllib.request, "urlopen", Api({"token": "ghs_abc", "expires_at": "2026-08-23T13:00:00Z"})
    )

    minted = installation_token(role_with_key(a_key(tmp_path, rsa_pem)), now=1_755_000_000)

    assert "ghs_abc" not in repr(minted)
    assert "2026-08-23T13:00:00Z" in repr(minted), "the expiry is not a secret and is worth seeing"
    assert minted.token == "ghs_abc", "redacted from the representation, not from the value"


def test_a_successful_response_that_is_not_json_names_the_call_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A proxy, a captive portal or a maintenance page all answer 200 with HTML. Letting
    # the decoder raise turns that into a traceback out of role diagnosis, where what
    # `doctor` owes the human is one line naming the condition that is unmet.
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_, **__: Response(b"<html>nope"))

    with pytest.raises(CredentialError, match="/app"):
        app_get("a.b.c", "/app")


def test_a_response_body_that_stops_early_names_the_call_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Truncated(Response):
        def read(self, *_: object) -> bytes:
            raise http.client.IncompleteRead(b"{")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_, **__: Truncated(b""))

    with pytest.raises(CredentialError, match="/app"):
        app_get("a.b.c", "/app")


def test_a_successful_response_that_is_not_an_object_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every caller reads what comes back by key. A JSON array answers `.get` with an
    # `AttributeError` several frames later, naming a method rather than a call.
    monkeypatch.setattr(urllib.request, "urlopen", Api(["implementer-my-team"]))

    with pytest.raises(CredentialError, match="/app"):
        app_get("a.b.c", "/app")


def test_a_token_response_without_a_token_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rsa_pem: str
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", Api({"expires_at": "2026-08-23T13:00:00Z"}))

    with pytest.raises(CredentialError, match="access_tokens"):
        installation_token(role_with_key(a_key(tmp_path, rsa_pem)), now=1_755_000_000)


# ── Where a token may travel ─────────────────────────────────────────────────────


def test_a_token_travels_as_gh_token_and_nothing_else() -> None:
    minted = InstallationToken(token="ghs_abc", expires_at="2026-08-23T13:00:00Z")

    assert token_env(minted) == {TOKEN_VARIABLE: "ghs_abc"}


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
