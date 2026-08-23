"""The `my-team` command line entry point.

Run from a **target repo** root, so `gh` infers the repo and the harness picks up
project context for free. The commands themselves — `init`, `sync`, `eject`, `doctor`,
`work`, `clean` — arrive with the tickets that implement them; this module owns the
parser they attach to, and the version.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import IntEnum
from importlib import metadata
from typing import NoReturn

PROGRAM = "my-team"


class ExitCode(IntEnum):
    """What the process exits with, so a wrapper script never parses output.

    The likeliest way a human meets one of these is running `work` on an issue that is
    already parked, which is why each one prints why. A usage error takes `ERROR`
    rather than argparse's own `2`, which would claim an escalation that never happened.
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
