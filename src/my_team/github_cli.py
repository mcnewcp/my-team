"""Running `gh`, and the one way a role's identity reaches a subprocess.

Two callers, two identities. Most of what the orchestrator reads it reads as the human
— `gh` is already authenticated, and `doctor` blocks on that. Everything a **role**
does, it does with an installation token passed in that one subprocess's environment
and nowhere else.

**`gh`'s `returncode` is read here**, which [ADR
0010](../../docs/adr/0010-verify-by-observation.md) permits and scopes: what it refuses
is trusting a *harness*'s exit status, because both harnesses in scope were measured
exiting `0` on work that did not happen. `gh` is not a harness. One invocation makes one
API call, and its status says whether that call reached GitHub and came back — a fact
about the request, never an account of a task.

**`gh auth switch` is never called.** It would do the same job by mutating a config
file every concurrent tick shares, which races; `GH_TOKEN` documents itself as taking
precedence over stored credentials, so a per-process variable needs no coordination and
leaves the human's own login untouched. `tests/test_credentials.py` asserts the string
appears nowhere in the package, because this is the kind of rule that gets broken by
someone reaching for the obvious tool.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from my_team.credentials import InstallationToken, token_env

GH: Final = "gh"

GH_TIMEOUT_SECONDS: Final = 30.0
"""How long any one `gh` call may take. A diagnostic that hangs is worse than one that
fails, and nothing here is a dispatch — those carry their own clock."""


class GhError(RuntimeError):
    """A `gh` invocation that did not succeed, and everything it said about why."""

    def __init__(self, args: Sequence[str], reason: str) -> None:
        super().__init__(f"gh {' '.join(args)}: {reason}")
        self.command = tuple(args)
        self.reason = reason


def run_gh(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    token: InstallationToken | None = None,
    timeout: float = GH_TIMEOUT_SECONDS,
) -> str:
    """Run `gh` and return its stdout, or raise `GhError`.

    `token` makes the call as a role rather than as the human. It arrives as the whole
    `InstallationToken` and is unwrapped only where the child's environment is built,
    so the secret is never a bare string in a frame that could print one. It reaches the
    child through `env` alone — the parent's own environment is never touched, so two
    ticks running as different roles cannot see each other's credential.
    """
    try:
        result = subprocess.run(
            [GH, *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=_environment(token),
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise GhError(args, "`gh` is not on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise GhError(args, f"timed out after {timeout:g}s") from error

    if result.returncode != 0:
        raise GhError(args, result.stderr.strip() or f"exited {result.returncode}")
    return result.stdout


def gh_json(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    token: InstallationToken | None = None,
) -> Any:
    """Run `gh` and decode what it printed, or raise `GhError`."""
    output = run_gh(args, cwd=cwd, token=token)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise GhError(args, f"printed something that is not JSON — {error}") from error


def _environment(token: InstallationToken | None) -> Mapping[str, str] | None:
    """`None` means "inherit", which is the human's own login."""
    if token is None:
        return None
    return {**os.environ, **token_env(token)}
