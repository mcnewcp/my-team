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
from importlib import metadata
from typing import NoReturn

PROGRAM = "my-team"

USAGE_ERROR = 1
"""Exit `1` (error), not argparse's default `2`, which is reserved for "escalated"."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(USAGE_ERROR)


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
