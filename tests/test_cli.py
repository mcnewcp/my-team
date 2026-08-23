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
