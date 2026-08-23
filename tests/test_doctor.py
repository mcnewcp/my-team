"""What `doctor` concludes, given what it found. No I/O anywhere in here.

Every check the spec's §1 lists gets a case in both directions, because the value of
`doctor` is entirely in the verdict: a check that silently passes when it should fail
is worse than no check, and one that blocks on an advisory is worse still.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from my_team.core.config import Config, RoleConfig, Roles
from my_team.core.doctor import (
    Facts,
    Finding,
    GhFacts,
    HarnessFacts,
    OwnerFacts,
    Protection,
    RepoFacts,
    RoleFacts,
    Severity,
    Status,
    Unavailable,
    Unprotected,
    evaluate,
    render,
)
from my_team.core.labels import AUTHORIZATION_LABEL, ESCALATION_LABEL

ROLE = RoleConfig(
    app_id=4652114,
    bot_user_id=318751706,
    installation_id=155006997,
    key_path=Path("~/.config/my-team/keys/implementer.pem"),
)


def a_config(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "product_owner": "mcnewcp",
        "required_checks": ("lint", "types", "tests"),
        "roles": Roles(implementer=ROLE, reviewer=ROLE, judge=ROLE),
    }
    values.update(overrides)
    return Config(**values)


def a_role(**overrides: Any) -> RoleFacts:
    values: dict[str, Any] = {
        "declared": ROLE,
        "key_path": Path("/home/mcnewcp/.config/my-team/keys/implementer.pem"),
        "key_mode": 0o600,
        "key_inside_repo": False,
        "app_slug": "implementer-my-team",
        "installation_resolved": True,
        "installation_reaches_repo": True,
        "bot_user_id": 318751706,
    }
    values.update(overrides)
    return RoleFacts(**values)


def a_repo(**overrides: Any) -> RepoFacts:
    values: dict[str, Any] = {
        "name_with_owner": "mcnewcp/my-team",
        "default_branch": "main",
        "allow_squash_merge": True,
        "allow_merge_commit": False,
        "allow_rebase_merge": False,
        "delete_branch_on_merge": True,
        "labels": (AUTHORIZATION_LABEL, ESCALATION_LABEL, "bug"),
    }
    values.update(overrides)
    return RepoFacts(**values)


def healthy(**overrides: Any) -> Facts:
    """Every check passing — the baseline each case below breaks exactly one of."""
    values: dict[str, Any] = {
        "gh": GhFacts(path="/opt/homebrew/bin/gh", account="mcnewcp"),
        "harness": HarnessFacts(binary="claude", path="/Users/mcnewcp/.local/bin/claude"),
        "config": a_config(),
        "owner": OwnerFacts(login="mcnewcp", permission="admin"),
        "repo": a_repo(),
        "protection": Unprotected(branch="main"),
        "roles": {"implementer": a_role(), "reviewer": a_role(), "judge": a_role()},
    }
    values.update(overrides)
    return Facts(**values)


def find(facts: Facts, check: str) -> Finding:
    return next(f for f in evaluate(facts).findings if f.check == check)


def status_of(facts: Facts, check: str) -> Status:
    return find(facts, check).status


def checks(facts: Facts) -> tuple[str, ...]:
    return tuple(f.check for f in evaluate(facts).findings)


# ── The report as a whole ────────────────────────────────────────────────────────


def test_a_healthy_repo_passes_every_blocking_check() -> None:
    report = evaluate(healthy())

    assert report.ok
    assert not [f for f in report.findings if f.status is Status.FAIL]


def test_the_checks_are_reported_in_the_order_the_spec_lists_them() -> None:
    assert checks(healthy()) == (
        "gh",
        "harness",
        "config",
        "required checks",
        "product owner",
        "role implementer",
        "role reviewer",
        "role judge",
        "merge policy",
        "labels",
        "protection",
    )


def test_one_failing_blocking_check_sinks_the_report() -> None:
    report = evaluate(healthy(gh=Unavailable("gh is not on PATH")))

    assert not report.ok


def test_a_warning_alone_never_sinks_the_report() -> None:
    report = evaluate(healthy(config=a_config(required_checks=())))

    assert report.ok
    assert [f.check for f in report.findings if f.status is Status.WARN] == ["required checks"]


def test_no_advisory_check_can_ever_block() -> None:
    # The rule is structural rather than remembered: an advisory finding that carried a
    # blocking status could not be constructed in the first place.
    with pytest.raises(ValueError, match="advisory"):
        Finding(
            check="protection",
            severity=Severity.ADVISORY,
            status=Status.FAIL,
            detail="protection is recommended, never required",
        )


@pytest.mark.parametrize(
    "check",
    ["gh", "harness", "config", "product owner", "role judge", "merge policy", "labels"],
)
def test_the_spec_s_blocking_list_is_blocking(check: str) -> None:
    assert find(healthy(), check).severity is Severity.BLOCKING


@pytest.mark.parametrize("check", ["required checks", "protection"])
def test_the_spec_s_advisory_list_is_advisory(check: str) -> None:
    assert find(healthy(), check).severity is Severity.ADVISORY


# ── gh and the harness binary ────────────────────────────────────────────────────


def test_gh_missing_fails_and_says_so() -> None:
    finding = find(healthy(gh=Unavailable("`gh` is not on PATH")), "gh")

    assert finding.status is Status.FAIL
    assert "not on PATH" in finding.detail


def test_gh_present_but_unauthenticated_fails() -> None:
    finding = find(healthy(gh=GhFacts(path="/usr/bin/gh", account=None)), "gh")

    assert finding.status is Status.FAIL
    assert "gh auth status" in finding.detail


def test_gh_authenticated_names_the_account() -> None:
    assert "mcnewcp" in find(healthy(), "gh").detail


def test_the_harness_binary_missing_fails() -> None:
    finding = find(healthy(harness=Unavailable("`claude` is not on PATH")), "harness")

    assert finding.status is Status.FAIL


def test_the_harness_binary_present_names_where_it_was_found() -> None:
    assert "/Users/mcnewcp/.local/bin/claude" in find(healthy(), "harness").detail


# ── Config, and the required checks ──────────────────────────────────────────────


def test_a_config_that_does_not_parse_fails_with_the_parser_s_own_message() -> None:
    reason = ".my-team/config.toml: missing required key: product_owner"
    finding = find(healthy(config=Unavailable(reason)), "config")

    assert finding.status is Status.FAIL
    assert finding.detail == reason


def test_an_empty_required_checks_warns_that_the_ci_gate_is_vacuous() -> None:
    finding = find(healthy(config=a_config(required_checks=())), "required checks")

    assert finding.status is Status.WARN
    assert "vacuous" in finding.detail


def test_declared_required_checks_are_listed() -> None:
    finding = find(healthy(), "required checks")

    assert finding.status is Status.PASS
    assert "lint, types, tests" in finding.detail


def test_the_required_checks_line_is_dropped_when_the_config_did_not_parse() -> None:
    # There is nothing to say about a key in a file that would not load, and the config
    # failure above it already says why.
    assert "required checks" not in checks(healthy(config=Unavailable("no config file")))


# ── The product owner ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("permission", ["admin", "write"])
def test_a_product_owner_who_can_write_passes(permission: str) -> None:
    facts = healthy(owner=OwnerFacts(login="mcnewcp", permission=permission))

    assert status_of(facts, "product owner") is Status.PASS


@pytest.mark.parametrize("permission", ["read", "triage", "none"])
def test_a_product_owner_who_cannot_write_fails(permission: str) -> None:
    finding = find(healthy(owner=OwnerFacts(login="ana", permission=permission)), "product owner")

    assert finding.status is Status.FAIL
    assert "ana" in finding.detail
    assert permission in finding.detail


def test_a_product_owner_that_could_not_be_resolved_fails() -> None:
    reason = "no such user: mcnewcpp"
    finding = find(healthy(owner=Unavailable(reason)), "product owner")

    assert finding.status is Status.FAIL
    assert finding.detail == reason


# ── The three roles ──────────────────────────────────────────────────────────────


def with_role(name: str, facts: RoleFacts | Unavailable) -> Facts:
    roles: dict[str, RoleFacts | Unavailable] = {
        "implementer": a_role(),
        "reviewer": a_role(),
        "judge": a_role(),
    }
    roles[name] = facts
    return healthy(roles=roles)


def test_a_sound_role_reports_the_three_ids_config_keys_on() -> None:
    detail = find(healthy(), "role implementer").detail

    assert "4652114" in detail
    assert "155006997" in detail
    assert "318751706" in detail
    assert "implementer-my-team[bot]" in detail


def test_a_missing_key_file_fails_and_names_the_path() -> None:
    finding = find(with_role("judge", a_role(key_mode=None)), "role judge")

    assert finding.status is Status.FAIL
    assert "/home/mcnewcp/.config/my-team/keys/implementer.pem" in finding.detail


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o777, 0o660])
def test_a_key_that_is_not_0600_fails_and_names_the_mode(mode: int) -> None:
    finding = find(with_role("reviewer", a_role(key_mode=mode)), "role reviewer")

    assert finding.status is Status.FAIL
    assert f"{mode:04o}" in finding.detail


def test_a_key_inside_the_target_repo_fails_even_at_0600() -> None:
    # A key inside the repo is one `git add .` from being published, which no file mode
    # prevents, so it is reported ahead of the mode.
    finding = find(with_role("judge", a_role(key_inside_repo=True)), "role judge")

    assert finding.status is Status.FAIL
    assert "outside every repo" in finding.detail


def test_a_key_that_does_not_authenticate_as_its_app_fails() -> None:
    finding = find(with_role("judge", a_role(app_slug=None)), "role judge")

    assert finding.status is Status.FAIL
    assert "4652114" in finding.detail


def test_an_installation_that_does_not_resolve_fails() -> None:
    finding = find(with_role("judge", a_role(installation_resolved=False)), "role judge")

    assert finding.status is Status.FAIL
    assert "155006997" in finding.detail


def test_an_installation_that_does_not_cover_this_repo_fails() -> None:
    # It resolves — the App exists and the key signs for it — and the role would still
    # fail its first write, which is exactly what `doctor` is for.
    finding = find(with_role("judge", a_role(installation_reaches_repo=False)), "role judge")

    assert finding.status is Status.FAIL
    assert "does not cover this repo" in finding.detail


def test_a_role_is_still_checkable_when_the_repo_could_not_be_named() -> None:
    # Everything else about a role is provable with its own key alone, so gh being the
    # thing at fault must not take the key checks down with it.
    facts = with_role("judge", a_role(installation_reaches_repo=None))

    assert status_of(facts, "role judge") is Status.PASS


def test_a_bot_user_id_that_disagrees_with_the_api_fails_naming_both() -> None:
    finding = find(with_role("judge", a_role(bot_user_id=999)), "role judge")

    assert finding.status is Status.FAIL
    assert "318751706" in finding.detail
    assert "999" in finding.detail


def test_a_bot_user_that_does_not_resolve_leaves_the_id_unconfirmed() -> None:
    finding = find(with_role("judge", a_role(bot_user_id=None)), "role judge")

    assert finding.status is Status.FAIL
    assert "unconfirmed" in finding.detail


def test_a_role_that_could_not_be_probed_fails_with_the_reason() -> None:
    finding = find(with_role("reviewer", Unavailable("the config did not parse")), "role reviewer")

    assert finding.status is Status.FAIL
    assert finding.detail == "the config did not parse"


def test_every_role_in_the_roster_gets_a_line_even_when_none_were_probed() -> None:
    report = evaluate(healthy(roles={}))

    assert [f.check for f in report.findings if f.check.startswith("role ")] == [
        "role implementer",
        "role reviewer",
        "role judge",
    ]
    assert all(f.status is Status.FAIL for f in report.findings if f.check.startswith("role "))


# ── Merge policy and labels ──────────────────────────────────────────────────────


def test_squash_only_with_auto_delete_passes() -> None:
    finding = find(healthy(), "merge policy")

    assert finding.status is Status.PASS
    assert "mcnewcp/my-team" in finding.detail


@pytest.mark.parametrize(
    ("override", "named"),
    [
        ({"allow_merge_commit": True}, "merge commits"),
        ({"allow_rebase_merge": True}, "rebase"),
        ({"allow_squash_merge": False}, "squash"),
        ({"delete_branch_on_merge": False}, "deleted on merge"),
    ],
)
def test_anything_but_squash_only_with_auto_delete_fails(
    override: Mapping[str, bool], named: str
) -> None:
    finding = find(healthy(repo=a_repo(**override)), "merge policy")

    assert finding.status is Status.FAIL
    assert named in finding.detail


def test_every_merge_policy_problem_is_reported_at_once() -> None:
    finding = find(
        healthy(repo=a_repo(allow_merge_commit=True, delete_branch_on_merge=False)),
        "merge policy",
    )

    assert "merge commits" in finding.detail
    assert "deleted on merge" in finding.detail


def test_a_repo_that_could_not_be_read_fails_both_checks_that_need_it() -> None:
    facts = healthy(repo=Unavailable("could not read mcnewcp/my-team"))

    assert status_of(facts, "merge policy") is Status.FAIL
    assert status_of(facts, "labels") is Status.FAIL


def test_both_labels_present_passes() -> None:
    assert status_of(healthy(), "labels") is Status.PASS


@pytest.mark.parametrize("missing", [AUTHORIZATION_LABEL, ESCALATION_LABEL])
def test_a_missing_label_fails_and_names_it(missing: str) -> None:
    remaining = tuple(name for name in a_repo().labels if name != missing)
    finding = find(healthy(repo=a_repo(labels=remaining)), "labels")

    assert finding.status is Status.FAIL
    assert missing in finding.detail


# ── Branch protection, which is reported and never required ──────────────────────


def a_protection(**overrides: Any) -> Protection:
    values: dict[str, Any] = {
        "branch": "main",
        "required_approving_review_count": 1,
        "enforce_admins": True,
        "require_last_push_approval": False,
    }
    values.update(overrides)
    return Protection(**values)


def test_an_unprotected_default_branch_is_a_note_and_never_a_warning() -> None:
    finding = find(healthy(), "protection")

    assert finding.status is Status.NOTE
    assert "main" in finding.detail
    assert "never required" in finding.detail


def test_an_unprotected_branch_raises_none_of_the_protection_sub_warnings() -> None:
    assert [c for c in checks(healthy()) if c.startswith("protection")] == ["protection"]


def test_a_protected_branch_is_reported() -> None:
    finding = find(healthy(protection=a_protection()), "protection")

    assert finding.status is Status.NOTE
    assert "protected" in finding.detail


def test_zero_required_approvals_warns_that_review_decision_stops_being_computed() -> None:
    facts = healthy(protection=a_protection(required_approving_review_count=0))
    finding = find(facts, "protection approvals")

    assert finding.status is Status.WARN
    assert "reviewDecision" in finding.detail


def test_no_review_requirement_at_all_warns_for_the_same_reason() -> None:
    facts = healthy(protection=a_protection(required_approving_review_count=None))
    finding = find(facts, "protection approvals")

    assert finding.status is Status.WARN
    assert "reviewDecision" in finding.detail


def test_a_real_approval_requirement_passes() -> None:
    facts = healthy(protection=a_protection(required_approving_review_count=2))

    assert status_of(facts, "protection approvals") is Status.PASS


def test_protection_that_exempts_admins_warns() -> None:
    facts = healthy(protection=a_protection(enforce_admins=False))
    finding = find(facts, "protection admins")

    assert finding.status is Status.WARN
    assert "enforce_admins" in finding.detail


def test_protection_that_includes_admins_passes() -> None:
    assert status_of(healthy(protection=a_protection()), "protection admins") is Status.PASS


def test_require_last_push_approval_is_noted_as_unmeasured_when_set() -> None:
    facts = healthy(protection=a_protection(require_last_push_approval=True))
    finding = find(facts, "protection last push")

    assert finding.status is Status.NOTE
    assert "unmeasured" in finding.detail


def test_require_last_push_approval_is_silent_when_unset() -> None:
    assert "protection last push" not in checks(healthy(protection=a_protection()))


def test_protection_that_could_not_be_read_warns_and_still_never_blocks() -> None:
    finding = find(healthy(protection=Unavailable("the repo could not be read")), "protection")

    assert finding.status is Status.WARN
    assert evaluate(healthy(protection=Unavailable("x"))).ok


# ── Rendering ────────────────────────────────────────────────────────────────────


def test_every_finding_reaches_the_rendered_report() -> None:
    report = evaluate(healthy())
    rendered = render(report)

    for finding in report.findings:
        assert finding.check in rendered
        assert finding.detail in rendered


def test_a_healthy_report_says_so_and_names_no_failure() -> None:
    rendered = render(evaluate(healthy()))

    assert "0 failed" not in rendered
    assert "blocking check failed" not in rendered


def test_failures_are_counted_in_the_closing_line() -> None:
    rendered = render(evaluate(healthy(gh=Unavailable("no gh"), harness=Unavailable("no claude"))))

    assert "2 blocking checks failed" in rendered


def test_one_failure_is_counted_in_the_singular() -> None:
    rendered = render(evaluate(healthy(gh=Unavailable("no gh"))))

    assert "1 blocking check failed" in rendered


def test_warnings_are_counted_separately_from_failures() -> None:
    facts = healthy(
        config=a_config(required_checks=()), protection=a_protection(enforce_admins=False)
    )

    assert "2 warnings" in render(evaluate(facts))


def test_one_warning_is_counted_in_the_singular() -> None:
    assert "1 warning" in render(evaluate(healthy(config=a_config(required_checks=()))))


def test_the_columns_line_up_whatever_the_longest_check_name_is() -> None:
    lines = [line for line in render(evaluate(healthy())).splitlines() if " ✓ " in line]

    assert len({line.index(line.strip().split()[1]) for line in lines}) == 1
