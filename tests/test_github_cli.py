"""Running `gh` — the arguments, the failures, and how a role's token reaches a child."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from my_team.credentials import TOKEN_VARIABLE, InstallationToken
from my_team.github_cli import GhError, gh_json, run_gh


class Spy:
    """Stands in for `subprocess.run`, recording what it was asked to do."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.result = subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        return self.result


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    recorder = Spy(stdout="ok\n")
    monkeypatch.setattr(subprocess, "run", recorder)
    return recorder


def test_gh_is_invoked_with_the_arguments_it_was_given(spy: Spy) -> None:
    run_gh(["api", "/user"])

    assert spy.calls[0]["args"] == ["gh", "api", "/user"]


def test_stdout_comes_back_verbatim(spy: Spy) -> None:
    assert run_gh(["api", "/user"]) == "ok\n"


def test_a_working_directory_is_passed_through(spy: Spy, tmp_path: Path) -> None:
    run_gh(["repo", "view"], cwd=tmp_path)

    assert spy.calls[0]["cwd"] == tmp_path


def test_without_a_token_the_child_inherits_the_human_s_own_login(spy: Spy) -> None:
    run_gh(["api", "/user"])

    assert spy.calls[0]["env"] is None


def test_a_token_reaches_the_child_and_only_the_child(spy: Spy) -> None:
    # Handed over as the whole `InstallationToken`: the type keeps its secret out of
    # representations, and a caller that had to unwrap it first would defeat that
    # everywhere between the mint and here.
    minted = InstallationToken(token="ghs_installationtoken", expires_at="2026-08-23T13:00:00Z")

    run_gh(["pr", "review"], token=minted)

    environment = spy.calls[0]["env"]
    assert environment[TOKEN_VARIABLE] == "ghs_installationtoken"
    assert environment["PATH"] == os.environ["PATH"], "the rest of the environment survives"
    assert TOKEN_VARIABLE not in os.environ, "the parent's environment is never touched"


def test_a_failure_carries_what_gh_said_about_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Spy(stderr="gh: Not Found (HTTP 404)\n", returncode=1))

    with pytest.raises(GhError, match="Not Found"):
        run_gh(["api", "/nope"])


def test_a_failure_with_nothing_on_stderr_still_names_the_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "run", Spy(returncode=3))

    with pytest.raises(GhError, match="exited 3"):
        run_gh(["api", "/nope"])


def test_gh_missing_from_the_path_is_reported_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_: Any, **__: Any) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(GhError, match="not on PATH"):
        run_gh(["api", "/user"])


def test_a_hung_call_is_killed_rather_than_waited_on(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*_: Any, **__: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=30.0)

    monkeypatch.setattr(subprocess, "run", hang)

    with pytest.raises(GhError, match="timed out"):
        run_gh(["api", "/user"])


def test_the_error_names_the_command_that_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Spy(stderr="boom", returncode=1))

    with pytest.raises(GhError) as caught:
        run_gh(["api", "/repos/a/b"])

    assert caught.value.command == ("api", "/repos/a/b")
    assert "gh api /repos/a/b" in str(caught.value)


def test_json_output_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Spy(stdout='{"login": "mcnewcp"}'))

    assert gh_json(["api", "/user"]) == {"login": "mcnewcp"}


def test_output_that_is_not_json_is_a_gh_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Spy(stdout="not json"))

    with pytest.raises(GhError, match="not JSON"):
        gh_json(["api", "/user"])
