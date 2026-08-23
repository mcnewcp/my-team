"""The CLI surface: `--version`, `--help`, and the exit code a usage error takes.

No subcommand exists yet — each arrives with the ticket that implements it — so what is
asserted here is the entry point itself: that it is installed, that it reports the
version the package actually carries, and that it never exits `2`.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from my_team.cli import ExitCode, main
from my_team.core.config import KEY_MODE, Config, RoleConfig, Roles
from my_team.core.doctor import (
    Facts,
    GhFacts,
    HarnessFacts,
    OwnerFacts,
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


class Healthy:
    """A `probe` that answers with a repo where nothing is wrong."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.roots: list[Path] = []

    def __call__(self, repo_root: Path, *, now: int) -> Facts:
        self.roots.append(repo_root)
        gh: GhFacts | Unavailable = (
            GhFacts(path="/usr/bin/gh", account="mcnewcp")
            if self.ok
            else Unavailable("`gh` is not on PATH")
        )
        return Facts(
            gh=gh,
            harness=HarnessFacts(binary="claude", path="/usr/bin/claude"),
            config=Unavailable("no config file — run `my-team init`"),
            owner=Unavailable("not checked — the config did not parse"),
            repo=Unavailable("not checked"),
            protection=Unprotected(branch="main"),
            roles={},
        )


def test_doctor_is_listed_among_the_commands(capsys: pytest.CaptureFixture[str]) -> None:
    main([])

    assert "doctor" in capsys.readouterr().out


def test_doctor_prints_the_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("my_team.cli.probe", Healthy())

    main(["doctor"])

    assert "my-team doctor" in capsys.readouterr().out


def test_doctor_exits_non_zero_when_a_blocking_check_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exit-code table describes an issue's fate, so only these two can honestly
    # describe a diagnostic.
    monkeypatch.setattr("my_team.cli.probe", Healthy())

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
    probe = Healthy()
    monkeypatch.setattr("my_team.cli.probe", probe)
    monkeypatch.chdir(tmp_path)

    main(["doctor"])
    capsys.readouterr()

    assert probe.roots == [Path.cwd()]


_ROLE = RoleConfig(
    app_id=1, bot_user_id=2, installation_id=3, key_path=Path("/keys/implementer.pem")
)
_ROLE_FACTS = RoleFacts(
    declared=_ROLE,
    key_path=Path("/keys/implementer.pem"),
    key_mode=KEY_MODE,
    key_inside_repo=False,
    app_slug="implementer-my-team",
    installation_resolved=True,
    bot_user_id=2,
)
SOUND = Facts(
    gh=GhFacts(path="/usr/bin/gh", account="mcnewcp"),
    harness=HarnessFacts(binary="claude", path="/usr/bin/claude"),
    config=Config(
        product_owner="mcnewcp",
        required_checks=("lint",),
        roles=Roles(implementer=_ROLE, reviewer=_ROLE, judge=_ROLE),
    ),
    owner=OwnerFacts(login="mcnewcp", permission="admin"),
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
    roles=dict.fromkeys(("implementer", "reviewer", "judge"), _ROLE_FACTS),
)
