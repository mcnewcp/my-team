"""Reading one check's verdict out of a diagnosis.

Two suites evaluate `Facts` — `test_doctor.py` from snapshots written down by hand, and
`test_probe.py` from what the fakes at `subprocess.run` and `urlopen` answered — and both
ask the same three questions of the result.
"""

from __future__ import annotations

from my_team.core.doctor import Facts, Finding, Status, evaluate


def find(facts: Facts, check: str) -> Finding:
    return next(f for f in evaluate(facts).findings if f.check == check)


def status_of(facts: Facts, check: str) -> Status:
    return find(facts, check).status


def checks(facts: Facts) -> tuple[str, ...]:
    return tuple(f.check for f in evaluate(facts).findings)
