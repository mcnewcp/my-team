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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from findings import find, status_of
from my_team.core.config import KEY_MODE, ROLE_NAMES, ROLE_PERMISSIONS
from my_team.core.doctor import (
    GhFacts,
    HarnessFacts,
    InstallationFacts,
    ProductOwnerFacts,
    Protection,
    RepoFacts,
    RoleFacts,
    Status,
    Unavailable,
    Unprotected,
    evaluate,
)
from my_team.github_cli import GH
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
ROLE_OF = dict(zip(INSTALLATIONS.values(), ROLE_NAMES, strict=True))
REPO_INSTALLATION = f"/repos/{REPO}/installation"


def installed(installation_id: int) -> dict[str, Any]:
    """An installation as GitHub describes it: the id, and what it was accepted with."""
    return {
        "id": installation_id,
        "suspended_at": None,
        "permissions": {**ROLE_PERMISSIONS[ROLE_OF[installation_id]], "metadata": "read"},
    }


def refused(status: int, path: str) -> urllib.error.HTTPError:
    """What `urlopen` raises when GitHub answers with a status rather than a body."""
    return urllib.error.HTTPError(
        f"https://api.github.com{path}",
        status,
        "refused",
        email.message.Message(),
        io.BytesIO(b'{"message": "refused"}'),
    )


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
            f"/app/installations/{one}": installed(one) for one in INSTALLATIONS.values()
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


def test_a_label_with_spaces_in_it_stays_one_label(world: World, repo_root: Path) -> None:
    # `gh` prints one name per line, so splitting on whitespace would turn GitHub's own
    # `good first issue` into three labels that do not exist.
    world.gh[f"api repos/{REPO}/labels --paginate --jq .[].name"] = (
        "good first issue\nready-for-agent\nready-for-human\n"
    )

    assert probed(repo_root).repo.labels == (
        "good first issue",
        "ready-for-agent",
        "ready-for-human",
    )


def test_the_product_owner_is_resolved_against_the_permission_api(
    world: World, repo_root: Path
) -> None:
    assert probed(repo_root).product_owner == ProductOwnerFacts(login="mcnewcp", permission="admin")
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
    assert found.installation == InstallationFacts(
        suspended=False,
        permissions={**ROLE_PERMISSIONS["implementer"], "metadata": "read"},
    )
    assert found.bot_user_id == 318751706
    assert found.key_mode == KEY_MODE
    assert found.key_repo is None


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
    (root / ".git").mkdir()
    (root / ".my-team" / "config.toml").write_text(CONFIG.format(keys=root / ".my-team"))
    for name in ("implementer", "reviewer", "judge"):
        key = root / ".my-team" / f"{name}.pem"
        key.write_text(rsa_pem)
        key.chmod(KEY_MODE)

    assert role(probed(root)).key_repo == root


def test_a_key_inside_some_other_repo_is_noticed_too(
    world: World, repo_root: Path, tmp_path: Path
) -> None:
    # The target repo is the one repo a key is obviously not allowed in, and it is not
    # the only one: a key under any clone on the machine is a key something can stage.
    elsewhere = tmp_path / "keys"
    (elsewhere / ".git").mkdir()

    found = role(probed(repo_root))

    assert found.key_repo == elsewhere
    assert status_of(probed(repo_root), "role implementer") is Status.FAIL


def test_a_key_in_the_wrong_place_is_reported_without_reaching_github(
    world: World, repo_root: Path, tmp_path: Path
) -> None:
    (tmp_path / "keys" / ".git").mkdir()
    world.api_calls.clear()

    probed(repo_root)

    assert not world.api_calls, "a key that must not be used is never signed with"


def test_a_key_github_refuses_leaves_the_role_unproven(world: World, repo_root: Path) -> None:
    world.app_override = refused(401, "/app")

    assert role(probed(repo_root)).app_slug is None


@pytest.mark.parametrize("status", [403, 429, 500, 502])
def test_github_failing_app_for_a_reason_that_is_not_the_key_is_not_blamed_on_the_key(
    world: World, repo_root: Path, status: int
) -> None:
    # `401` is the one status that says this key is not `app_id`'s key. A rate limit or
    # a 5xx says nothing about whose key it is, and reporting it as a credential
    # mismatch names the wrong unmet condition — the one thing doctor exists not to do.
    world.app_override = refused(status, "/app")
    found = role(probed(repo_root))

    assert isinstance(found, Unavailable)
    assert str(status) in found.reason


def test_an_installation_that_is_gone_is_reported_as_unresolved(
    world: World, repo_root: Path
) -> None:
    del world.api["/app/installations/155006997"]
    found = role(probed(repo_root))

    assert found.app_slug == "implementer-my-team"
    assert found.installation is None
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
    [urllib.error.URLError("connection reset"), refused(403, REPO_INSTALLATION)],
)
def test_a_coverage_check_that_could_not_run_still_reports_what_was_proven(
    world: World, repo_root: Path, refusal: Exception
) -> None:
    # Covering this repo is the one thing here §1 does not enumerate, so a transient
    # failure on it must not read as though the key, App and installation went
    # unexamined too — nor swallow the checks §1 does name.
    world.repo_installation_override = refusal
    found = role(probed(repo_root))

    assert isinstance(found, RoleFacts)
    assert found.app_slug == "implementer-my-team"
    assert found.installation is not None
    assert found.bot_user_id == 318751706
    assert isinstance(found.installation_reaches_repo, Unavailable)


def test_a_coverage_check_that_could_not_run_warns_and_never_blocks(
    world: World, repo_root: Path
) -> None:
    world.repo_installation_override = urllib.error.URLError("connection reset")
    facts = probed(repo_root)

    assert status_of(facts, "role implementer") is Status.PASS
    assert status_of(facts, "role implementer coverage") is Status.WARN
    assert evaluate(facts).ok, "an addition to §1's list cannot block when it cannot run"


def test_a_bot_user_id_that_disagrees_is_still_caught_when_coverage_could_not_run(
    world: World, repo_root: Path
) -> None:
    # #51 requires every `bot_user_id` be matched against the API. That check ran second
    # and behind an early return, so a transient failure of the extra coverage probe
    # suppressed a required one.
    world.repo_installation_override = urllib.error.URLError("connection reset")
    world.gh["api /users/implementer-my-team%5Bbot%5D --jq .id"] = "999\n"
    finding = find(probed(repo_root), "role implementer")

    assert finding.status is Status.FAIL
    assert "318751706" in finding.detail
    assert "999" in finding.detail


def test_a_bot_user_lookup_that_failed_carries_what_gh_said_about_it(
    world: World, repo_root: Path
) -> None:
    # A `404` under that login, a timeout and a `502` are three conditions with three
    # fixes. Collapsing them all into "the bot did not resolve" describes only the first.
    del world.gh["api /users/implementer-my-team%5Bbot%5D --jq .id"]
    found = role(probed(repo_root))

    assert isinstance(found.bot_user_id, Unavailable)
    assert "404" in found.bot_user_id.reason


def test_a_bot_user_gh_named_without_an_id_is_left_unconfirmed(
    world: World, repo_root: Path
) -> None:
    # `gh` succeeded and printed no number, which is the one answer that really is about
    # the account rather than about the lookup.
    world.gh["api /users/implementer-my-team%5Bbot%5D --jq .id"] = "\n"

    assert role(probed(repo_root)).bot_user_id is None


def test_gh_being_the_thing_at_fault_is_what_the_bot_id_line_says(
    world: World, repo_root: Path
) -> None:
    """`/users/...` is looked up as the human, so `gh` failing is `gh`'s finding.

    Collapsing it to `None` reported three bot accounts that "did not resolve" when the
    unmet condition was one login — three misleading lines under the true one.
    """
    del world.binaries["gh"]
    found = role(probed(repo_root))

    assert isinstance(found.bot_user_id, Unavailable)
    assert GH in found.bot_user_id.reason
    detail = find(probed(repo_root), "role implementer").detail
    assert "did not resolve" not in detail
    assert GH in detail


def test_a_directory_where_a_role_key_belongs_reads_as_a_missing_key(
    world: World, repo_root: Path
) -> None:
    # At mode 0600 a directory clears the mode check, and the read two calls later is an
    # `IsADirectoryError` — a traceback out of the command whose whole job is to name
    # the unmet precondition.
    path = Path(role(probed(repo_root)).key_path)
    path.unlink()
    path.mkdir(mode=KEY_MODE)
    facts = probed(repo_root)

    assert role(facts).key_mode is None
    assert str(path) in find(facts, "role implementer").detail


def test_a_key_that_is_not_text_names_the_file_rather_than_raising(
    world: World, repo_root: Path
) -> None:
    path = Path(role(probed(repo_root)).key_path)
    path.write_bytes(b"\xff\xfe\x00\x01")
    path.chmod(KEY_MODE)

    found = role(probed(repo_root))
    assert isinstance(found, Unavailable)
    assert str(path) in found.reason


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


def test_a_suspended_installation_is_read_off_the_same_response_that_resolved_it(
    world: World, repo_root: Path
) -> None:
    # GitHub suspends an installation without removing it, so resolving proves only that
    # it exists. `suspended_at` comes back beside the id and costs no second request.
    world.api["/app/installations/155006997"] = {
        **installed(155006997),
        "suspended_at": "2026-08-20T10:00:00Z",
    }
    found = role(probed(repo_root))

    assert found.installation is not None
    assert found.installation.suspended
    assert status_of(probed(repo_root), "role implementer") is Status.FAIL


def test_the_authority_an_installation_was_accepted_with_is_what_gets_reported(
    world: World, repo_root: Path
) -> None:
    # Not what the App asks for now: widening a permission leaves the installation on
    # the old set until a human re-accepts it, which is the state worth catching.
    world.api["/app/installations/154043927"] = {
        **installed(154043927),
        "permissions": {"contents": "write", "pull_requests": "write", "issues": "read"},
    }
    finding = find(probed(repo_root), "role reviewer")

    assert finding.status is Status.FAIL
    assert "contents" in finding.detail


def test_an_installation_described_without_readable_permissions_still_proves_the_rest(
    world: World, repo_root: Path
) -> None:
    # What an installation grants is one of the checks §1 does not enumerate. Returning
    # it in place of the role left a key, an App and a bot id that were all proven
    # reported as though none of them had been looked at.
    world.api["/app/installations/155006997"] = {"id": 155006997}
    found = role(probed(repo_root))
    facts = probed(repo_root)

    assert isinstance(found, RoleFacts)
    assert found.bot_user_id == 318751706
    assert found.installation is not None
    assert isinstance(found.installation.permissions, Unavailable)
    assert status_of(facts, "role implementer") is Status.PASS
    assert status_of(facts, "role implementer authority") is Status.WARN
    assert evaluate(facts).ok, "an addition to §1's list cannot block when it cannot run"


def test_a_bot_user_id_that_disagrees_is_still_caught_when_the_grant_is_unreadable(
    world: World, repo_root: Path
) -> None:
    world.api["/app/installations/155006997"] = {"id": 155006997}
    world.gh["api /users/implementer-my-team%5Bbot%5D --jq .id"] = "999\n"
    finding = find(probed(repo_root), "role implementer")

    assert finding.status is Status.FAIL
    assert "999" in finding.detail


@pytest.mark.parametrize("answer", [["not", "an", "object"], "a string"])
def test_an_app_response_that_is_not_an_object_is_reported_rather_than_crashing(
    world: World, repo_root: Path, answer: Any
) -> None:
    # Every caller reads what came back by key. A `200` carrying an array reached `.get`
    # as an `AttributeError` out of role diagnosis rather than as a finding.
    world.app_override = answer

    assert isinstance(role(probed(repo_root)), Unavailable)


def test_a_repo_installation_named_without_an_id_is_not_a_definite_no(
    world: World, repo_root: Path
) -> None:
    # `False` here blocks a run, so it is claimed only on an answer that says so.
    world.repo_installation_override = {"node_id": "MDIz"}
    found = role(probed(repo_root))

    assert isinstance(found.installation_reaches_repo, Unavailable)
    assert status_of(probed(repo_root), "role implementer") is Status.PASS


# ── Branch protection ────────────────────────────────────────────────────────────


def test_an_unprotected_branch_is_read_off_the_branch_rather_than_a_404(
    world: World, repo_root: Path
) -> None:
    facts = probed(repo_root)

    assert facts.protection == Unprotected(branch="main")
    assert not [call for call in world.gh_calls if "protection" in " ".join(call)]


def test_a_branch_without_a_boolean_protected_flag_is_not_reported_as_unprotected(
    world: World, repo_root: Path
) -> None:
    # Only `false` proves there is no protection. A null answer says GitHub did not
    # describe the branch, so turning it into a definite no would hide that failure.
    world.gh[f"api repos/{REPO}/branches/main --jq .protected"] = "null\n"

    assert isinstance(probed(repo_root).protection, Unavailable)


@pytest.mark.parametrize("branch", ["release#1", "release/1.0", "feature?x"])
def test_a_default_branch_is_asked_after_as_one_path_segment(
    world: World, repo_root: Path, branch: str
) -> None:
    """A branch name is not a URL fragment, and `#` is legal in one.

    Interpolated raw, `release#1` asks GitHub about `release` — which either does not
    exist or is somebody else's branch, and either way the protection reported is not
    the default branch's. Encoding `/` as well is measured rather than assumed: GitHub
    resolves both spellings of a branch name identically.
    """
    encoded = urllib.parse.quote(branch, safe="")
    world.gh[f"api repos/{REPO}"] = json.dumps({**REPO_PAYLOAD, "default_branch": branch})
    world.gh[f"api repos/{REPO}/branches/{encoded} --jq .protected"] = "false\n"
    facts = probed(repo_root)

    assert facts.protection == Unprotected(branch=branch)
    assert [call for call in world.gh_calls if encoded in " ".join(call)]


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


@pytest.mark.parametrize(
    "field,value",
    [
        ("required_approving_review_count", "2"),
        ("require_last_push_approval", "false"),
        ("enforce_admins", "false"),
    ],
)
def test_a_protected_branch_with_a_non_typed_field_is_not_coerced(
    world: World, repo_root: Path, field: str, value: str
) -> None:
    # JSON strings are truthy in Python, so coercion turns the literal `"false"` into
    # true and lets a string approval count reach the diagnosis as if GitHub supplied
    # the documented boolean and integer fields.
    reviews: dict[str, object] = {
        "required_approving_review_count": 2,
        "require_last_push_approval": False,
    }
    enforce_admins: dict[str, object] = {"enabled": True}
    if field == "enforce_admins":
        enforce_admins["enabled"] = value
    else:
        reviews[field] = value
    world.gh[f"api repos/{REPO}/branches/main --jq .protected"] = "true\n"
    world.gh[f"api repos/{REPO}/branches/main/protection"] = json.dumps(
        {"required_pull_request_reviews": reviews, "enforce_admins": enforce_admins}
    )

    assert isinstance(probed(repo_root).protection, Unavailable)


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
    for absent in (facts.repo, facts.product_owner, facts.protection):
        assert isinstance(absent, Unavailable)
        assert "gh" in absent.reason


def test_gh_that_cannot_name_an_account_is_not_authenticated(world: World, repo_root: Path) -> None:
    del world.gh["api user --jq .login"]
    facts = probed(repo_root)

    assert isinstance(facts.gh, GhFacts)
    assert isinstance(facts.gh.account, Unavailable)
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


def test_a_config_that_will_not_read_is_a_finding_rather_than_a_traceback(
    world: World, repo_root: Path
) -> None:
    # `doctor` blocks on this file parsing, and every way it refuses to be read has to
    # arrive as that check failing — a directory in its place included.
    config = repo_root / ".my-team" / "config.toml"
    config.unlink()
    config.mkdir()
    facts = probed(repo_root)

    assert isinstance(facts.config, Unavailable)
    assert status_of(facts, "config") is Status.FAIL
    assert str(config) in find(facts, "config").detail


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
    assert isinstance(facts.product_owner, Unavailable)


def test_a_repo_github_describes_unrecognisably_is_reported(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}"] = json.dumps({"default_branch": "main"})

    assert isinstance(probed(repo_root).repo, Unavailable)


def test_a_repo_that_is_not_a_table_is_reported(world: World, repo_root: Path) -> None:
    world.gh[f"api repos/{REPO}"] = json.dumps(["main"])

    assert isinstance(probed(repo_root).repo, Unavailable)


def test_a_repo_with_a_null_default_branch_is_reported_rather_than_crashing(
    world: World, repo_root: Path
) -> None:
    # A 200 whose fields are null is not a repo GitHub described — read as one it reaches
    # `quote(None)` and the command whose job is naming the unmet precondition ends in a
    # traceback instead. Protection is advisory, so it goes unread and never blocks.
    world.gh[f"api repos/{REPO}"] = json.dumps({**REPO_PAYLOAD, "default_branch": None})
    facts = probed(repo_root)

    assert isinstance(facts.repo, Unavailable)
    assert "default_branch" in facts.repo.reason
    assert status_of(facts, "merge policy") is Status.FAIL
    assert isinstance(facts.protection, Unavailable)
    assert status_of(facts, "protection") is Status.WARN


def test_a_null_merge_flag_is_reported_rather_than_read_as_a_policy(
    world: World, repo_root: Path
) -> None:
    # `bool(None)` is `False`, so a field GitHub left null would arrive as a merge policy
    # someone has to go and fix — a confidently wrong answer, which is worse here than
    # no answer at all.
    world.gh[f"api repos/{REPO}"] = json.dumps({**REPO_PAYLOAD, "allow_squash_merge": None})
    facts = probed(repo_root)

    assert isinstance(facts.repo, Unavailable)
    assert "allow_squash_merge" in facts.repo.reason


def test_a_product_owner_who_is_not_a_collaborator_is_reported_by_login(
    world: World, repo_root: Path
) -> None:
    del world.gh[f"api repos/{REPO}/collaborators/mcnewcp/permission --jq .permission"]
    facts = probed(repo_root)

    assert isinstance(facts.product_owner, Unavailable)
    assert "mcnewcp" in facts.product_owner.reason


def test_a_repo_that_cannot_be_read_at_all_leaves_nothing_to_say_about_it(
    world: World, repo_root: Path
) -> None:
    # The other half of the split: with the repo object itself unread there is no merge
    # policy, no label set and no default branch to ask about protection.
    del world.gh[f"api repos/{REPO}"]
    facts = probed(repo_root)

    assert isinstance(facts.repo, Unavailable)
    assert isinstance(facts.protection, Unavailable)


def test_labels_that_cannot_be_listed_leave_the_rest_of_the_repo_read(
    world: World, repo_root: Path
) -> None:
    # The label list is its own request, so its failure is its own finding. Folding the
    # two together reported a merge policy GitHub had already described correctly, and
    # skipped protection, which needs nothing but the default branch.
    del world.gh[f"api repos/{REPO}/labels --paginate --jq .[].name"]
    facts = probed(repo_root)

    assert isinstance(facts.repo, RepoFacts)
    assert facts.repo.allow_squash_merge and not facts.repo.allow_merge_commit
    assert isinstance(facts.repo.labels, Unavailable)
    assert facts.protection == Unprotected(branch="main")
    assert status_of(facts, "merge policy") is Status.PASS
    assert status_of(facts, "labels") is Status.FAIL


def test_a_hung_gh_does_not_hang_the_diagnosis(world: World, repo_root: Path) -> None:
    world.gh["api user --jq .login"] = subprocess.TimeoutExpired(cmd="gh", timeout=30.0)
    facts = probed(repo_root)

    assert isinstance(facts.gh, GhFacts)
    assert isinstance(facts.gh.account, Unavailable)
    assert "timed out" in facts.gh.account.reason
    assert "timed out" in find(facts, "gh").detail, "and a timeout is not a logged-out gh"


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
