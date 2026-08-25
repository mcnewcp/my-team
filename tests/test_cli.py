"""The CLI surface: the entry point, and the commands attached to it.

The entry point's own tests come first — that it is installed, that it reports the
version the package actually carries, and that it never exits `2`, since `2` means
"escalated" and a mistyped flag must not claim one. Each command arrives with the ticket
that implements it; `doctor` is the first, and what is asserted about it here is the
wiring alone. What it *concludes* is `tests/test_doctor.py`'s question.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from my_team.cli import ExitCode, main
from my_team.core.config import KEY_MODE, ROLE_NAMES, ROLE_PERMISSIONS, Config, RoleConfig, Roles
from my_team.core.doctor import (
    Facts,
    GhFacts,
    HarnessFacts,
    InstallationFacts,
    ProductOwnerFacts,
    RepoFacts,
    RoleFacts,
    Unavailable,
    Unprotected,
)
from my_team.core.labels import AUTHORIZATION_LABEL, ESCALATION_LABEL

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SCRIPT = Path(sys.executable).parent / "my-team"


def declared_version() -> str:
    return str(tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]["version"])


def test_version_reports_the_declared_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"])

    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == f"my-team {declared_version()}"


def test_the_installed_metadata_matches_the_declared_version() -> None:
    assert metadata.version("my-team") == declared_version()


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])

    assert caught.value.code == 0
    assert "usage: my-team" in capsys.readouterr().out


def test_no_arguments_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: my-team" in capsys.readouterr().out


def test_a_usage_error_exits_one_rather_than_two(capsys: pytest.CaptureFixture[str]) -> None:
    # 2 is "escalated" in the exit-code table, so a mistyped flag must not claim it.
    with pytest.raises(SystemExit) as caught:
        main(["--not-a-flag"])

    assert caught.value.code == ExitCode.ERROR
    assert "my-team: error:" in capsys.readouterr().err


def test_the_exit_codes_are_the_documented_table() -> None:
    assert [(code.name, code.value) for code in ExitCode] == [
        ("MERGED", 0),
        ("ERROR", 1),
        ("ESCALATED", 2),
        ("AWAITING_APPROVAL", 3),
        ("HALTED", 4),
    ]


@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_the_console_script_is_on_the_path_and_runs(flag: str) -> None:
    assert CONSOLE_SCRIPT.exists(), f"{CONSOLE_SCRIPT} — is the project installed?"

    result = subprocess.run([str(CONSOLE_SCRIPT), flag], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "my-team" in result.stdout


class Unconfigured:
    """A `probe` that answers with a repo holding no config file.

    `gh` and the harness are found; the product owner, the repo and the roles are all
    unavailable behind the missing config, so this is a blocked diagnosis rather than a
    clean bill of health — what the tests below assert is the wiring around one.
    `gh_on_path` varies that single answer and nothing else.
    """

    def __init__(self, gh_on_path: bool = True) -> None:
        self.gh_on_path = gh_on_path
        self.roots: list[Path] = []

    def __call__(self, repo_root: Path, *, now: int) -> Facts:
        self.roots.append(repo_root)
        gh: GhFacts | Unavailable = (
            GhFacts(path="/usr/bin/gh", account="mcnewcp")
            if self.gh_on_path
            else Unavailable("`gh` is not on PATH")
        )
        return Facts(
            gh=gh,
            harness=HarnessFacts(binary="claude", path="/usr/bin/claude"),
            config=Unavailable("no config file — run `my-team init`"),
            product_owner=Unavailable("not checked — the config did not parse"),
            repo=Unavailable("not checked"),
            protection=Unprotected(branch="main"),
            roles={},
        )


def test_doctor_is_listed_among_the_commands(capsys: pytest.CaptureFixture[str]) -> None:
    main([])

    assert "doctor" in capsys.readouterr().out


def test_doctor_prints_the_diagnosis(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("my_team.cli.probe", Unconfigured())

    main(["doctor"])

    assert "my-team doctor" in capsys.readouterr().out


def test_doctor_exits_non_zero_when_a_blocking_check_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exit-code table describes an issue's fate, so only these two can honestly
    # describe a diagnostic.
    monkeypatch.setattr("my_team.cli.probe", Unconfigured())

    assert main(["doctor"]) == ExitCode.ERROR
    capsys.readouterr()


def test_doctor_exits_zero_when_nothing_is_unmet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("my_team.cli.probe", lambda repo_root, *, now: SOUND)

    assert main(["doctor"]) == 0
    capsys.readouterr()


def test_doctor_looks_at_the_directory_it_was_run_from(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # The CLI is run from the target repo root, which is what lets `gh` infer the repo
    # and the harness pick up project context.
    probe = Unconfigured()
    monkeypatch.setattr("my_team.cli.probe", probe)
    monkeypatch.chdir(tmp_path)

    main(["doctor"])
    capsys.readouterr()

    assert probe.roots == [Path.cwd()]


def _role(name: str, app_id: int) -> RoleConfig:
    # Distinct ids per role: one identity may not both open a pull request and approve
    # it, and `doctor` blocks a roster that shares one.
    return RoleConfig(
        app_id=app_id,
        bot_user_id=app_id + 1,
        installation_id=app_id + 2,
        key_path=Path(f"/keys/{name}.pem"),
    )


def _role_facts(name: str, declared: RoleConfig) -> RoleFacts:
    return RoleFacts(
        declared=declared,
        key_path=declared.key_path,
        key_mode=KEY_MODE,
        key_repo=None,
        app_slug=f"{name}-my-team",
        installation=InstallationFacts(suspended=False, permissions=ROLE_PERMISSIONS[name]),
        installation_reaches_repo=True,
        bot_user_id=declared.bot_user_id,
    )


_ROLES = {name: _role(name, 10 * index + 1) for index, name in enumerate(ROLE_NAMES)}
SOUND = Facts(
    gh=GhFacts(path="/usr/bin/gh", account="mcnewcp"),
    harness=HarnessFacts(binary="claude", path="/usr/bin/claude"),
    config=Config(product_owner="mcnewcp", required_checks=("lint",), roles=Roles(**_ROLES)),
    product_owner=ProductOwnerFacts(login="mcnewcp", permission="admin"),
    repo=RepoFacts(
        name_with_owner="mcnewcp/my-team",
        default_branch="main",
        allow_squash_merge=True,
        allow_merge_commit=False,
        allow_rebase_merge=False,
        delete_branch_on_merge=True,
        labels=(AUTHORIZATION_LABEL, ESCALATION_LABEL),
    ),
    protection=Unprotected(branch="main"),
    roles={name: _role_facts(name, declared) for name, declared in _ROLES.items()},
)
