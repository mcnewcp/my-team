"""What `doctor` asks the world, and what it makes of the answers.

The fakes sit at the real edges — `subprocess.run` and `urlopen` — rather than at
`run_gh` and `app_get`, so the `gh` arguments and the request URLs are constructed for
real. That is deliberate: a fake one level up would never exercise argument
construction, which is where the landmines in this design have all been.
"""

from __future__ import annotations

import base64
import email.message
import io
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from my_team.core.config import KEY_MODE
from my_team.core.doctor import (
    GhFacts,
    HarnessFacts,
    OwnerFacts,
    Protection,
    RepoFacts,
    RoleFacts,
    Unavailable,
    Unprotected,
    evaluate,
)
from my_team.probe import HARNESS_BINARY, probe

NOW = 1_755_000_000
REPO = "mcnewcp/my-team"

CONFIG = """
product_owner   = "mcnewcp"
required_checks = ["lint", "types", "tests"]

[roles.implementer]
app_id          = 4652114
bot_user_id     = 318751706
installation_id = 155006997
key_path        = "{keys}/implementer.pem"

[roles.reviewer]
app_id          = 4608397
bot_user_id     = 317436782
installation_id = 154043927
key_path        = "{keys}/reviewer.pem"

[roles.judge]
app_id          = 4652145
bot_user_id     = 318752691
installation_id = 155007556
key_path        = "{keys}/judge.pem"
"""

REPO_PAYLOAD = {
    "default_branch": "main",
    "allow_squash_merge": True,
    "allow_merge_commit": False,
    "allow_rebase_merge": False,
    "delete_branch_on_merge": True,
}

SLUGS = {
    4652114: ("implementer-my-team", 318751706),
    4608397: ("reviewer-my-team", 317436782),
    4652145: ("judge-my-team", 318752691),
}
INSTALLATIONS = {4652114: 155006997, 4608397: 154043927, 4652145: 155007556}
REPO_INSTALLATION = f"/repos/{REPO}/installation"


class Body(io.BytesIO):
    """What `urlopen` yields — a context manager over the response body."""

    def __enter__(self) -> Body:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class World:
    """A target repo as `gh` and the App API would describe it."""

    def __init__(self) -> None:
        self.binaries = {"gh": "/opt/homebrew/bin/gh", HARNESS_BINARY: "/usr/local/bin/claude"}
        self.gh: dict[str, str | Exception] = {
            "api user --jq .login": "mcnewcp\n",
            "repo view --json nameWithOwner --jq .nameWithOwner": f"{REPO}\n",
            f"api repos/{REPO}": json.dumps(REPO_PAYLOAD),
            f"api repos/{REPO}/labels --paginate --jq .[].name": (
                "ready-for-agent\nready-for-human\nbug\n"
            ),
            f"api repos/{REPO}/collaborators/mcnewcp/permission --jq .permission": "admin\n",
            f"api repos/{REPO}/branches/main --jq .protected": "false\n",
            **{f"api /users/{slug}%5Bbot%5D --jq .id": f"{bot}\n" for slug, bot in SLUGS.values()},
        }
        self.api: dict[str, Any] = {
            f"/app/installations/{one}": {"id": one} for one in INSTALLATIONS.values()
        }
        self.app_override: Any = None
        self.repo_installation_override: Any = None
        self.gh_calls: list[list[str]] = []
        self.api_calls: list[tuple[str, str]] = []
        self._jwt_app: int | None = None

    # ── the two edges ────────────────────────────────────────────────────────────

    def which(self, name: str) -> str | None:
        return self.binaries.get(name)

    def run(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.gh_calls.append(argv)
        answer = self.gh.get(" ".join(argv[1:]))
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return subprocess.CompletedProcess(argv, 1, "", "gh: Not Found (HTTP 404)\n")
        return subprocess.CompletedProcess(argv, 0, answer, "")

    def urlopen(self, request: Any, timeout: float | None = None) -> Body:
        path = request.full_url.removeprefix("https://api.github.com")
        self.api_calls.append((request.get_method(), path))
        # `/app` answers as whichever App signed the JWT, which is how a key that does
        # not belong to its `app_id` would be caught.
        if path == "/app":
            payload = self._app(request)
        elif path == REPO_INSTALLATION:
            payload = self._repo_installation(request)
        else:
            payload = self.api.get(path)
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                email.message.Message(),
                io.BytesIO(b'{"message": "Not Found"}'),
            )
        return Body(json.dumps(payload).encode())

    def _app(self, request: Any) -> Any:
        """Answer as the App whose id signed the JWT, read off the token itself."""
        if self.app_override is not None:
            return self.app_override
        return {"slug": SLUGS[self._issuer(request)][0]}

    def _repo_installation(self, request: Any) -> Any:
        """Which of this App's installations covers the target repo."""
        if self.repo_installation_override is not None:
            return self.repo_installation_override
        return {"id": INSTALLATIONS[self._issuer(request)]}

    @staticmethod
    def _issuer(request: Any) -> int:
        claims = request.get_header("Authorization").removeprefix("Bearer ").split(".")[1]
        return int(json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))["iss"])


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    made = World()
    monkeypatch.setattr(shutil, "which", made.which)
    monkeypatch.setattr(subprocess, "run", made.run)
    monkeypatch.setattr(urllib.request, "urlopen", made.urlopen)
    return made


@pytest.fixture
def repo_root(tmp_path: Path, rsa_pem: str) -> Path:
    """A target repo with a parsing config and three role keys at 0600, outside it."""
    root = tmp_path / "repo"
    keys = tmp_path / "keys"
    (root / ".my-team").mkdir(parents=True)
    keys.mkdir()
    (root / ".my-team" / "config.toml").write_text(CONFIG.format(keys=keys))
    for role in ("implementer", "reviewer", "judge"):
        key = keys / f"{role}.pem"
        key.write_text(rsa_pem)
        key.chmod(KEY_MODE)
    return root


def probed(repo_root: Path) -> Any:
    return probe(repo_root, now=NOW)


# ── The happy path ───────────────────────────────────────────────────────────────


def test_a_configured_repo_probes_clean(world: World, repo_root: Path) -> None:
    assert evaluate(probed(repo_root)).ok


def test_gh_and_the_harness_are_found_where_they_live(world: World, repo_root: Path) -> None:
    facts = probed(repo_root)

    assert facts.gh == GhFacts(path="/opt/homebrew/bin/gh", account="mcnewcp")
    assert facts.harness == HarnessFacts(binary=HARNESS_BINARY, path="/usr/local/bin/claude")


def test_the_repo_s_merge_policy_and_labels_are_read(world: World, repo_root: Path) -> None:
    assert probed(repo_root).repo == RepoFacts(
        name_with_owner=REPO,
        default_branch="main",
        allow_squash_merge=True,
        allow_merge_commit=False,
        allow_rebase_merge=False,
        delete_branch_on_merge=True,
        labels=("ready-for-agent", "ready-for-human", "bug"),
    )


def test_the_product_owner_is_resolved_against_the_permission_api(
    world: World, repo_root: Path
) -> None:
    assert probed(repo_root).owner == OwnerFacts(login="mcnewcp", permission="admin")
    assert [call for call in world.gh_calls if "collaborators/mcnewcp/permission" in " ".join(call)]


def test_doctor_never_mutates_anything(world: World, repo_root: Path) -> None:
    """The whole command is reads. A diagnostic that writes is one nobody runs twice."""
    probed(repo_root)

    for call in world.gh_calls:
        assert call[1] in {"api", "repo"}, call
        assert not {"-X", "--method", "-f", "-F", "--input"} & set(call), call
    assert {method for method, _ in world.api_calls} == {"GET"}


def test_the_installation_is_resolved_rather_than_minted_from(
    world: World, repo_root: Path
) -> None:
    # Minting a token would create a credential, and the same JWT that proves the GET
    # would prove the POST — so there is nothing to learn and something to clean up.
    probed(repo_root)

    assert not [path for _, path in world.api_calls if path.endswith("/access_tokens")]


# ── The roles ────────────────────────────────────────────────────────────────────


def role(facts: Any, name: str = "implementer") -> Any:
    return facts.roles[name]


def test_a_sound_role_reports_its_slug_installation_and_bot_user(
    world: World, repo_root: Path
) -> None:
    found = role(probed(repo_root))

    assert found.app_slug == "implementer-my-team"
    assert found.installation_resolved
    assert found.bot_user_id == 318751706
    assert found.key_mode == KEY_MODE
    assert not found.key_inside_repo


def test_a_missing_key_is_reported_without_reaching_github(world: World, repo_root: Path) -> None:
    facts = probed(repo_root)
    for name in facts.roles:
        Path(facts.roles[name].key_path).unlink()
    world.api_calls.clear()

    assert role(probed(repo_root)).key_mode is None
    assert not world.api_calls, "a key that is not there cannot sign, so nothing is asked"


def test_a_key_that_is_not_0600_is_reported_with_its_mode(world: World, repo_root: Path) -> None:
    Path(role(probed(repo_root)).key_path).chmod(0o644)

    assert role(probed(repo_root)).key_mode == 0o644


def test_a_key_inside_the_target_repo_is_noticed(
    world: World, tmp_path: Path, rsa_pem: str
) -> None:
    root = tmp_path / "inside"
    (root / ".my-team").mkdir(parents=True)
    (root / ".my-team" / "config.toml").write_text(CONFIG.format(keys=root / ".my-team"))
    for name in ("implementer", "reviewer", "judge"):
        key = root / ".my-team" / f"{name}.pem"
        key.write_text(rsa_pem)
        key.chmod(KEY_MODE)

    assert role(probed(root)).key_inside_repo


def test_a_key_github_refuses_leaves_the_role_unproven(world: World, repo_root: Path) -> None:
    world.app_override = urllib.error.HTTPError(
        "https://api.github.com/app",
        401,
        "Unauthorized",
        email.message.Message(),
        io.BytesIO(b"{}"),
    )

    assert role(probed(repo_root)).app_slug is None


def test_an_installation_that_is_gone_is_reported_as_unresolved(
    world: World, repo_root: Path
) -> None:
    del world.api["/app/installations/155006997"]
    found = role(probed(repo_root))

    assert found.app_slug == "implementer-my-team"
    assert not found.installation_resolved
    assert found.bot_user_id is None


def test_an_installation_that_does_not_cover_the_repo_is_noticed(
    world: World, repo_root: Path
) -> None:
    world.repo_installation_override = {"id": 999}

    assert role(probed(repo_root)).installation_reaches_repo is False


def test_an_app_that_is_not_installed_on_the_repo_at_all_is_noticed(
    world: World, repo_root: Path
) -> None:
    world.repo_installation_override = urllib.error.HTTPError(
        f"https://api.github.com{REPO_INSTALLATION}",
        404,
        "Not Found",
        email.message.Message(),
        io.BytesIO(b"{}"),
    )

    assert role(probed(repo_root)).installation_reaches_repo is False


def test_a_repo_that_could_not_be_named_leaves_that_one_question_unasked(
    world: World, repo_root: Path
) -> None:
    del world.gh["repo view --json nameWithOwner --jq .nameWithOwner"]
    found = role(probed(repo_root))

    assert found.installation_reaches_repo is None
    assert found.key_mode == KEY_MODE, "a key is provable without gh, so it is still checked"
    assert found.app_slug == "implementer-my-team"
    assert found.bot_user_id == 318751706


@pytest.mark.parametrize(
    "refusal",
    [
        urllib.error.URLError("connection reset"),
        urllib.error.HTTPError(
            f"https://api.github.com{REPO_INSTALLATION}",
            403,
            "Forbidden",
            email.message.Message(),
            io.BytesIO(b"{}"),
        ),
    ],
)
def test_github_refusing_the_repo_installation_for_another_reason_is_reported(
    world: World, repo_root: Path, refusal: Exception
) -> None:
    world.repo_installation_override = refusal

    assert isinstance(role(probed(repo_root)), Unavailable)


def test_a_bot_user_that_cannot_be_looked_up_is_left_unconfirmed(
    world: World, repo_root: Path
) -> None:
    del world.gh["api /users/implementer-my-team%5Bbot%5D --jq .id"]

    assert role(probed(repo_root)).bot_user_id is None


def test_a_key_that_is_not_a_key_names_the_file(world: World, repo_root: Path) -> None:
    path = Path(role(probed(repo_root)).key_path)
    path.write_text("not a pem")
    path.chmod(KEY_MODE)

    found = role(probed(repo_root))
    assert isinstance(found, Unavailable)
    assert str(path) in found.reason


@pytest.mark.parametrize("status", [403, 500])
def test_github_failing_for_any_other_reason_is_not_a_finding_about_the_config(
    world: World, repo_root: Path, status: int
) -> None:
    world.api["/app/installations/155006997"] = urllib.error.HTTPError(
        "https://api.github.com/app/installations/155006997",
        status,
        "boom",
        email.message.Message(),
        io.BytesIO(b"{}"),
    )

    assert isinstance(role(probed(repo_root)), Unavailable)


def test_an_unreachable_github_is_reported_rather_than_guessed_at(
    world: World, repo_root: Path
) -> None:
    world.app_override = urllib.error.URLError("no route to host")

    assert isinstance(role(probed(repo_root)), Unavailable)


def test_an_app_described_without_a_slug_is_reported(world: World, repo_root: Path) -> None:
    world.app_override = {"id": 4652114}

    assert isinstance(role(probed(repo_root)), Unavailable)


# ── Branch protection ────────────────────────────────────────────────────────────


def test_an_unprotected_branch_is_read_off_the_branch_rather_than_a_404(
    world: World, repo_root: Path
) -> None:
    facts = probed(repo_root)

    assert facts.protection == Unprotected(branch="main")
    assert not [call for call in world.gh_calls if "protection" in " ".join(call)]


def test_a_protected_branch_is_described(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}/branches/main --jq .protected"] = "true\n"
    world.gh[f"api repos/{REPO}/branches/main/protection"] = json.dumps(
        {
            "required_pull_request_reviews": {
                "required_approving_review_count": 2,
                "require_last_push_approval": True,
            },
            "enforce_admins": {"enabled": True},
        }
    )

    assert probed(repo_root).protection == Protection(
        branch="main",
        required_approving_review_count=2,
        enforce_admins=True,
        require_last_push_approval=True,
    )


def test_protection_without_a_review_rule_reports_no_count(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}/branches/main --jq .protected"] = "true\n"
    world.gh[f"api repos/{REPO}/branches/main/protection"] = json.dumps(
        {"enforce_admins": {"enabled": False}}
    )
    found = probed(repo_root).protection

    assert found.required_approving_review_count is None
    assert not found.enforce_admins
    assert not found.require_last_push_approval


def test_protection_that_cannot_be_read_never_blocks(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}/branches/main --jq .protected"] = "true\n"
    facts = probed(repo_root)

    assert isinstance(facts.protection, Unavailable)
    assert evaluate(facts).ok


def test_protection_described_unrecognisably_is_reported(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}/branches/main --jq .protected"] = "true\n"
    world.gh[f"api repos/{REPO}/branches/main/protection"] = json.dumps(["not", "a", "table"])

    assert isinstance(probed(repo_root).protection, Unavailable)


# ── When a prerequisite is missing ───────────────────────────────────────────────


def test_gh_missing_stops_everything_that_needs_it_and_says_why(
    world: World, repo_root: Path
) -> None:
    del world.binaries["gh"]
    facts = probed(repo_root)

    assert isinstance(facts.gh, Unavailable)
    for absent in (facts.repo, facts.owner, facts.protection):
        assert isinstance(absent, Unavailable)
        assert "gh" in absent.reason


def test_gh_that_cannot_name_an_account_is_not_authenticated(world: World, repo_root: Path) -> None:
    del world.gh["api user --jq .login"]
    facts = probed(repo_root)

    assert facts.gh == GhFacts(path="/opt/homebrew/bin/gh", account=None)
    assert isinstance(facts.repo, Unavailable)


def test_an_empty_login_counts_as_no_account(world: World, repo_root: Path) -> None:
    world.gh["api user --jq .login"] = "\n"

    assert probed(repo_root).gh.account is None


def test_the_harness_binary_missing_is_reported_on_its_own(world: World, repo_root: Path) -> None:
    del world.binaries[HARNESS_BINARY]
    facts = probed(repo_root)

    assert isinstance(facts.harness, Unavailable)
    assert isinstance(facts.gh, GhFacts), "one missing binary says nothing about the other"


def test_a_directory_that_is_not_a_github_repo_is_reported(world: World, repo_root: Path) -> None:
    world.gh["repo view --json nameWithOwner --jq .nameWithOwner"] = "\n"
    facts = probed(repo_root)

    assert isinstance(facts.repo, Unavailable)
    assert str(repo_root) in facts.repo.reason


def test_a_missing_config_leaves_the_roles_unchecked_and_says_why(
    world: World, tmp_path: Path
) -> None:
    facts = probe(tmp_path, now=NOW)

    assert isinstance(facts.config, Unavailable)
    assert "my-team init" in facts.config.reason
    assert set(facts.roles) == {"implementer", "reviewer", "judge"}
    for unchecked in facts.roles.values():
        assert isinstance(unchecked, Unavailable)
        assert "config" in unchecked.reason
    assert isinstance(facts.owner, Unavailable)


def test_a_repo_github_describes_unrecognisably_is_reported(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}"] = json.dumps({"default_branch": "main"})

    assert isinstance(probed(repo_root).repo, Unavailable)


def test_a_repo_that_is_not_a_table_is_reported(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}"] = json.dumps(["main"])

    assert isinstance(probed(repo_root).repo, Unavailable)


def test_a_product_owner_who_is_not_a_collaborator_is_reported_by_login(
    world: World, repo_root: Path
) -> None:
    del world.gh[f"api repos/{REPO}/collaborators/mcnewcp/permission --jq .permission"]
    facts = probed(repo_root)

    assert isinstance(facts.owner, Unavailable)
    assert "mcnewcp" in facts.owner.reason


def test_labels_that_cannot_be_listed_leave_the_repo_unread(world: World, repo_root: Path) -> None:
    del world.gh[f"api repos/{REPO}/labels --paginate --jq .[].name"]

    assert isinstance(probed(repo_root).repo, Unavailable)


def test_a_hung_gh_does_not_hang_the_diagnosis(world: World, repo_root: Path) -> None:
    world.gh["api user --jq .login"] = subprocess.TimeoutExpired(cmd="gh", timeout=30.0)
    facts = probed(repo_root)

    assert isinstance(facts.gh, GhFacts)
    assert facts.gh.account is None


def test_every_role_still_gets_an_answer_when_one_of_them_is_broken(
    world: World, repo_root: Path
) -> None:
    Path(role(probed(repo_root), "judge").key_path).unlink()
    facts = probed(repo_root)

    assert isinstance(facts.roles["implementer"], RoleFacts)
    assert facts.roles["judge"].key_mode is None


def test_a_github_that_goes_away_mid_role_is_reported(world: World, repo_root: Path) -> None:
    world.api["/app/installations/155006997"] = urllib.error.URLError("connection reset")

    assert isinstance(role(probed(repo_root)), Unavailable)


def test_a_repo_view_that_fails_outright_is_reported(world: World, repo_root: Path) -> None:
    del world.gh["repo view --json nameWithOwner --jq .nameWithOwner"]
    facts = probed(repo_root)

    assert isinstance(facts.repo, Unavailable)
    assert "404" in facts.repo.reason
