"""The `my-team` command line entry point.

Run from a **target repo** root, so `gh` infers the repo and the harness picks up
project context for free. The remaining commands — `init`, `sync`, `eject`, `work`,
`clean` — arrive with the tickets that implement them; this module owns the parser they
attach to, and the version.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from enum import IntEnum
from importlib import metadata
from pathlib import Path
from typing import NoReturn

from my_team.core.doctor import evaluate, render
from my_team.probe import probe

PROGRAM = "my-team"


class ExitCode(IntEnum):
    """What the process exits with, so a wrapper script never parses output.

    The likeliest way a human meets one of these is running `work` on an issue that is
    already parked, which is why each one prints why. A usage error takes `ERROR`
    rather than argparse's own `2`, which would claim an escalation that never happened.

    The table describes an *issue's* fate, so only two of the five can honestly describe
    a diagnostic: `doctor` exits `0` when every blocking check passed and `ERROR` when
    one did not.
    """

    MERGED = 0
    ERROR = 1
    ESCALATED = 2
    AWAITING_APPROVAL = 3
    HALTED = 4


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(ExitCode.ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=PROGRAM,
        description="Drive a GitHub-backed development loop over a labelled issue.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM} {metadata.version(PROGRAM)}",
    )
    commands = parser.add_subparsers(title="commands", metavar="<command>")
    doctor = commands.add_parser(
        "doctor",
        help="check every precondition the loop depends on; change nothing",
        description=(
            "Check every precondition the loop depends on. Blocking checks fail and "
            "advisory checks warn, so a misconfiguration is found before a run rather "
            "than during one. Nothing is mutated, and nothing is configured for you."
        ),
    )
    doctor.set_defaults(run=run_doctor)
    return parser


def run_doctor(_: argparse.Namespace) -> int:
    """Probe, evaluate, print. The one clock read in the command lives here."""
    report = evaluate(probe(Path.cwd(), now=int(time.time())))
    sys.stdout.write(render(report))
    return int(ExitCode.MERGED if report.ok else ExitCode.ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    command = getattr(arguments, "run", None)
    if command is None:
        parser.print_help()
        return 0
    return int(command(arguments))
