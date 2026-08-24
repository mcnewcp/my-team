"""What `doctor` concludes, given what it found — the pure half of the command.

Split the way `observe()` is: `my_team.probe` does every bit of I/O and hands back
`Facts`, plain data, and `evaluate` turns that into a `Diagnosis` without touching the
world. The split is worth the seam for the same reason it is there: the verdict is the
whole value of `doctor`, and a verdict is only assertable if it can be produced from a
snapshot written down in a test.

Two rules hold the shape:

- **A probe that could not answer carries `Unavailable` in place of an answer**, never
  beside it. There is no state where a fact and the reason it is missing are both set,
  so no check has to decide which of the two to believe.
- **An advisory finding cannot carry a blocking status.** `Finding` refuses to
  construct one, so "advisory checks warn and never block" is a property of the model
  rather than a rule every branch has to remember — protection is *recommended*, and
  nothing here configures it or requires it.

`doctor` never mutates anything, which is also why the role check resolves an
installation rather than minting a token from it: minting creates a credential, and a
diagnostic that writes is a diagnostic nobody runs twice.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from my_team.core.config import KEY_MODE, ROLE_NAMES, Config, RoleConfig
from my_team.core.labels import AUTHORIZATION_LABEL, ESCALATION_LABEL

WRITE_PERMISSIONS: Final = frozenset({"write", "admin"})
"""What the `permission` API has to report for the product owner's guidance to reach a
prompt. The one place in the design the exact primitive is worth a round trip."""


class Severity(Enum):
    """Whether a check can stop a run, fixed per check and never per outcome."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"


class Status(Enum):
    """What one check concluded. `NOTE` is neither praise nor complaint — it is how a
    thing the human should know but need not change gets said."""

    PASS = "pass"
    NOTE = "note"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's verdict, and one line saying what to do about it."""

    check: str
    severity: Severity
    status: Status
    detail: str

    def __post_init__(self) -> None:
        if self.severity is Severity.ADVISORY and self.status is Status.FAIL:
            raise ValueError(f"{self.check}: an advisory check may warn but never fail")


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """Every finding, in the order the spec lists the checks.

    Not a *Report*: `CONTEXT.md` already spends that word on what a **role** says at the
    end of an **action**, and two things under one glossary term is exactly the drift
    the glossary exists to stop.
    """

    findings: tuple[Finding, ...]

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status is Status.FAIL)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status is Status.WARN)

    @property
    def ok(self) -> bool:
        """Whether the loop may run. Warnings never enter into it."""
        return not self.failures


# ── What the probe found ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Unavailable:
    """Why a probe has no answer, carried instead of the answer it does not have."""

    reason: str


@dataclass(frozen=True, slots=True)
class GhFacts:
    """`gh` on disk, and who it is logged in as — `None` when it is logged in as nobody."""

    path: str
    account: str | None


@dataclass(frozen=True, slots=True)
class HarnessFacts:
    """The harness binary the seam will spawn."""

    binary: str
    path: str


@dataclass(frozen=True, slots=True)
class ProductOwnerFacts:
    """What the `permission` API says about the login config names as product owner."""

    login: str
    permission: str


@dataclass(frozen=True, slots=True)
class RepoFacts:
    """The target repo's merge policy and label set.

    `labels` carries `Unavailable` on its own because it is its own request. A listing
    that fails says nothing about the merge policy GitHub described in the call before
    it, and nothing about the default branch that protection is then read off.
    """

    name_with_owner: str
    default_branch: str
    allow_squash_merge: bool
    allow_merge_commit: bool
    allow_rebase_merge: bool
    delete_branch_on_merge: bool
    labels: tuple[str, ...] | Unavailable


@dataclass(frozen=True, slots=True)
class Unprotected:
    """The default branch has no protection — which is legal, and the common case."""

    branch: str


@dataclass(frozen=True, slots=True)
class Protection:
    """The default branch's protection. Reported; never required, and never set here."""

    branch: str
    required_approving_review_count: int | None
    enforce_admins: bool
    require_last_push_approval: bool


@dataclass(frozen=True, slots=True)
class RoleFacts:
    """One role's declared identity beside what the platform says about it.

    `declared` and the observed fields sit together because every one of these checks
    is a comparison: the point is not what the API reports, it is whether config agrees
    with it. `key_path` is `declared.key_path` expanded, which is why it is a fact —
    expansion depends on `$HOME`, and the core never reads the environment.

    The last two fields are asked of two different services, so each carries its own
    `Unavailable` and neither stands in for the other. Coverage is the one check here
    §1 does not enumerate — an addition that must never suppress a requirement — while
    the bot id is looked up as the human, which makes a failed `gh` its answer rather
    than a bot account that "did not resolve". `installation_reaches_repo` is `None`
    when the target repo could not be named at all: the rest of a role's identity is
    provable with its own key alone, and stays checkable when the human's login is not.
    """

    declared: RoleConfig
    key_path: Path
    key_mode: int | None
    key_inside_repo: bool
    app_slug: str | None
    installation_resolved: bool
    installation_reaches_repo: bool | Unavailable | None
    bot_user_id: int | Unavailable | None


@dataclass(frozen=True, slots=True)
class Facts:
    """Everything one `doctor` run probed. The only input `evaluate` has."""

    gh: GhFacts | Unavailable
    harness: HarnessFacts | Unavailable
    config: Config | Unavailable
    product_owner: ProductOwnerFacts | Unavailable
    repo: RepoFacts | Unavailable
    protection: Protection | Unprotected | Unavailable
    roles: Mapping[str, RoleFacts | Unavailable]


# ── The verdict ──────────────────────────────────────────────────────────────────


def evaluate(facts: Facts) -> Diagnosis:
    """Turn what was probed into what the human is told."""
    return Diagnosis(tuple(_findings(facts)))


def _findings(facts: Facts) -> Iterator[Finding]:
    yield _gh(facts.gh)
    yield _harness(facts.harness)
    yield _config(facts.config)
    if not isinstance(facts.config, Unavailable):
        yield _required_checks(facts.config)
    yield _product_owner(facts.product_owner)
    for name in ROLE_NAMES:
        yield from _role(name, facts.roles.get(name))
    yield _merge_policy(facts.repo)
    yield _labels(facts.repo)
    yield from _protection(facts.protection)


def _blocking(check: str, status: Status, detail: str) -> Finding:
    return Finding(check=check, severity=Severity.BLOCKING, status=status, detail=detail)


def _advisory(check: str, status: Status, detail: str) -> Finding:
    return Finding(check=check, severity=Severity.ADVISORY, status=status, detail=detail)


def _gh(facts: GhFacts | Unavailable) -> Finding:
    if isinstance(facts, Unavailable):
        return _blocking("gh", Status.FAIL, facts.reason)
    if facts.account is None:
        # Not logged in and unreachable look identical from here, and `gh auth status`
        # is the command that tells them apart — so it is the one named.
        return _blocking(
            "gh",
            Status.FAIL,
            f"{facts.path} reported no account — run `gh auth status` to see why",
        )
    return _blocking("gh", Status.PASS, f"{facts.path}, authenticated as {facts.account}")


def _harness(facts: HarnessFacts | Unavailable) -> Finding:
    if isinstance(facts, Unavailable):
        return _blocking("harness", Status.FAIL, facts.reason)
    return _blocking("harness", Status.PASS, f"{facts.binary} at {facts.path}")


def _config(config: Config | Unavailable) -> Finding:
    if isinstance(config, Unavailable):
        return _blocking("config", Status.FAIL, config.reason)
    return _blocking(
        "config",
        Status.PASS,
        f"parses — product owner {config.product_owner}, three roles declared",
    )


def _required_checks(config: Config) -> Finding:
    """Declaring `[]` is legal — it means no CI gate — and worth saying out loud."""
    if not config.required_checks:
        return _advisory(
            "required checks",
            Status.WARN,
            "declared empty — the CI gate is vacuous, so nothing green is ever waited for",
        )
    return _advisory("required checks", Status.PASS, ", ".join(config.required_checks))


def _product_owner(facts: ProductOwnerFacts | Unavailable) -> Finding:
    if isinstance(facts, Unavailable):
        return _blocking("product owner", Status.FAIL, facts.reason)
    if facts.permission not in WRITE_PERMISSIONS:
        return _blocking(
            "product owner",
            Status.FAIL,
            f"{facts.login} has {facts.permission} — the product owner needs write or admin, "
            f"or their guidance is invisible to every prompt",
        )
    return _blocking("product owner", Status.PASS, f"{facts.login} has {facts.permission}")


def _role(name: str, facts: RoleFacts | Unavailable | None) -> Sequence[Finding]:
    """The role's own verdict, and — only when it could not be asked — one advisory line.

    Whether the installation covers this repo is the one role check the spec's §1 does
    not enumerate. A definite *no* belongs on the blocking line, because it is a
    misconfiguration exactly like a wrong `bot_user_id`. A probe that could not answer
    belongs nowhere near it: severity is fixed per check and never per outcome, so the
    question that cannot block gets its own name and its own advisory severity rather
    than a warning wearing a blocking one.
    """
    check = f"role {name}"
    if facts is None:
        return [_blocking(check, Status.FAIL, "no entry — the roster is exactly three roles")]
    if isinstance(facts, Unavailable):
        return [_blocking(check, Status.FAIL, facts.reason)]
    return [*_identity(check, facts), *_coverage(check, facts)]


def _identity(check: str, facts: RoleFacts) -> Sequence[Finding]:
    """Everything §1 requires of a role, in the order a human can act on it."""
    declared = facts.declared
    if facts.key_mode is None:
        return [_blocking(check, Status.FAIL, f"no key at {facts.key_path}")]
    if facts.key_inside_repo:
        # A key inside the repo is one `git add .` from being published, which no file
        # mode prevents — so it is reported ahead of the mode.
        return [
            _blocking(
                check,
                Status.FAIL,
                f"{facts.key_path} is inside the target repo — role keys live outside every repo",
            )
        ]
    if facts.key_mode != KEY_MODE:
        return [
            _blocking(
                check,
                Status.FAIL,
                f"{facts.key_path} is mode {facts.key_mode:04o} — role keys are "
                f"{KEY_MODE:04o}; run `chmod {KEY_MODE:o}` on it",
            )
        ]
    if facts.app_slug is None:
        return [
            _blocking(
                check,
                Status.FAIL,
                f"the key at {facts.key_path} does not authenticate as app_id {declared.app_id}",
            )
        ]
    if not facts.installation_resolved:
        return [
            _blocking(
                check,
                Status.FAIL,
                f"installation_id {declared.installation_id} does not resolve for "
                f"{facts.app_slug} — is the App installed anywhere?",
            )
        ]
    if facts.installation_reaches_repo is False:
        # Resolving proves the installation exists; this proves it is the one covering
        # the repo the loop is pointed at. Without it a role passes `doctor` and then
        # fails its first write.
        return [
            _blocking(
                check,
                Status.FAIL,
                f"installation {declared.installation_id} does not cover this repo — "
                f"install {facts.app_slug} on it, or config names the wrong installation",
            )
        ]
    if isinstance(facts.bot_user_id, Unavailable):
        return [
            _blocking(
                check,
                Status.FAIL,
                f"{facts.app_slug}[bot] was not looked up, so bot_user_id "
                f"{declared.bot_user_id} is unconfirmed — {facts.bot_user_id.reason}",
            )
        ]
    if facts.bot_user_id is None:
        return [
            _blocking(
                check,
                Status.FAIL,
                f"{facts.app_slug}[bot] did not resolve, so bot_user_id "
                f"{declared.bot_user_id} is unconfirmed",
            )
        ]
    if facts.bot_user_id != declared.bot_user_id:
        return [
            _blocking(
                check,
                Status.FAIL,
                f"bot_user_id is {declared.bot_user_id} but {facts.app_slug}[bot] "
                f"is {facts.bot_user_id}",
            )
        ]
    return [
        _blocking(
            check,
            Status.PASS,
            f"app {declared.app_id} · installation {declared.installation_id} · "
            f"{facts.app_slug}[bot] {facts.bot_user_id}",
        )
    ]


def _coverage(check: str, facts: RoleFacts) -> Sequence[Finding]:
    """One line, and only when the repo-coverage probe failed outright.

    Silent when it answered either way — `True` needs no saying and `False` is already
    on the blocking line — and silent when the repo could not be named at all, because
    then `gh` has failed its own check and this has nothing to add to it.
    """
    if not isinstance(facts.installation_reaches_repo, Unavailable):
        return []
    return [
        _advisory(
            f"{check} coverage",
            Status.WARN,
            f"whether installation {facts.declared.installation_id} covers this repo "
            f"could not be checked — {facts.installation_reaches_repo.reason}",
        )
    ]


def _merge_policy(repo: RepoFacts | Unavailable) -> Finding:
    """Squash-merge-only with auto-delete, because one pull request is one commit.

    A merge commit breaks the assumption the commit conventions rest on, so this is the
    one repo setting `doctor` blocks on — and, like protection, it is never set here.
    """
    if isinstance(repo, Unavailable):
        return _blocking("merge policy", Status.FAIL, repo.reason)

    problems = _merge_problems(repo)
    if problems:
        return _blocking("merge policy", Status.FAIL, f"{repo.name_with_owner}: {problems}")
    return _blocking(
        "merge policy",
        Status.PASS,
        f"{repo.name_with_owner}: squash-merge only, branches deleted on merge",
    )


def _merge_problems(repo: RepoFacts) -> str:
    problems = [
        message
        for wrong, message in (
            (not repo.allow_squash_merge, "squash merging is disabled"),
            (repo.allow_merge_commit, "merge commits are allowed"),
            (repo.allow_rebase_merge, "rebase merging is allowed"),
            (not repo.delete_branch_on_merge, "branches are not deleted on merge"),
        )
        if wrong
    ]
    return "; ".join(problems)


def _labels(repo: RepoFacts | Unavailable) -> Finding:
    if isinstance(repo, Unavailable):
        return _blocking("labels", Status.FAIL, repo.reason)
    if isinstance(repo.labels, Unavailable):
        return _blocking("labels", Status.FAIL, repo.labels.reason)

    missing = [name for name in (AUTHORIZATION_LABEL, ESCALATION_LABEL) if name not in repo.labels]
    if missing:
        return _blocking(
            "labels",
            Status.FAIL,
            f"missing {' and '.join(missing)} — `my-team init` creates them",
        )
    return _blocking("labels", Status.PASS, f"{AUTHORIZATION_LABEL} and {ESCALATION_LABEL} exist")


def _protection(protection: Protection | Unprotected | Unavailable) -> Sequence[Finding]:
    """Protection is reported and never required, so nothing here can fail.

    Only the two settings that surprise people warrant a warning, and the third is
    flagged as unmeasured rather than judged — a claim about its effect on the loop is
    not one this design has earned.
    """
    if isinstance(protection, Unavailable):
        return [_advisory("protection", Status.WARN, f"not reported — {protection.reason}")]
    if isinstance(protection, Unprotected):
        return [
            _advisory(
                "protection",
                Status.NOTE,
                f"{protection.branch} is not protected — protection is recommended, "
                f"never required, and nothing here configures it",
            )
        ]

    findings = [
        _advisory("protection", Status.NOTE, f"{protection.branch} is protected"),
        _approvals(protection),
        _enforce_admins(protection),
    ]
    if protection.require_last_push_approval:
        findings.append(
            _advisory(
                "protection last push",
                Status.NOTE,
                "require_last_push_approval is set; its effect on the loop is unmeasured",
            )
        )
    return findings


def _approvals(protection: Protection) -> Finding:
    """No approving review required and zero required are the same fact to GitHub.

    Either way it stops computing `reviewDecision`, so they share a warning and differ
    only in how the branch got there.
    """
    count = protection.required_approving_review_count
    if count:
        return _advisory(
            "protection approvals", Status.PASS, f"{count} approving review(s) required"
        )
    how = (
        "required_approving_review_count is 0"
        if count == 0
        else f"{protection.branch} requires no approving review"
    )
    return _advisory(
        "protection approvals",
        Status.WARN,
        f"{how}, so GitHub does not compute reviewDecision — harmless to the ladder, "
        f"which never reads it, and confusing to a human",
    )


def _enforce_admins(protection: Protection) -> Finding:
    if not protection.enforce_admins:
        return _advisory(
            "protection admins",
            Status.WARN,
            "enforce_admins is false — that configuration guards the pipeline and not the human",
        )
    return _advisory("protection admins", Status.PASS, "enforce_admins is on")


# ── Rendering ────────────────────────────────────────────────────────────────────

_MARKERS: Final[Mapping[Status, str]] = {
    Status.PASS: "✓",
    Status.NOTE: "·",
    Status.WARN: "⚠",
    Status.FAIL: "✗",
}


def render(diagnosis: Diagnosis) -> str:
    """The whole diagnosis as plain lines — no cursor tricks, so redirecting it reads."""
    width = max(len(f.check) for f in diagnosis.findings)
    lines = ["my-team doctor", ""]
    lines += [
        f"  {_MARKERS[f.status]} {f.check.ljust(width)}  {f.detail}" for f in diagnosis.findings
    ]
    return "\n".join([*lines, "", f"  {_summary(diagnosis)}"]) + "\n"


def _summary(diagnosis: Diagnosis) -> str:
    warnings = _count(len(diagnosis.warnings), "warning")
    if diagnosis.ok:
        if not diagnosis.warnings:
            return "Everything the loop depends on is in place."
        return f"Nothing blocking. {warnings} to read."
    return f"{_count(len(diagnosis.failures), 'blocking check')} failed, {warnings}."


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
