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

from findings import checks, find, status_of
from my_team.core.config import ROLE_NAMES, ROLE_PERMISSIONS, Config, RoleConfig, Roles
from my_team.core.doctor import (
    Facts,
    Finding,
    GhFacts,
    HarnessFacts,
    InstallationFacts,
    ProductOwnerFacts,
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

LABELS = (AUTHORIZATION_LABEL, ESCALATION_LABEL, "bug")

# The three provisioned Apps. Distinct in every id, because that is what the roster is:
# a role sharing an App with another cannot both open a pull request and approve it.
ROLES = {
    "implementer": RoleConfig(
        app_id=4652114,
        bot_user_id=318751706,
        installation_id=155006997,
        key_path=Path("~/.config/my-team/keys/implementer.pem"),
    ),
    "reviewer": RoleConfig(
        app_id=4608397,
        bot_user_id=317436782,
        installation_id=154043927,
        key_path=Path("~/.config/my-team/keys/reviewer.pem"),
    ),
    "judge": RoleConfig(
        app_id=4652145,
        bot_user_id=318752691,
        installation_id=155007556,
        key_path=Path("~/.config/my-team/keys/judge.pem"),
    ),
}
ROLE = ROLES["implementer"]


def a_config(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "product_owner": "mcnewcp",
        "required_checks": ("lint", "types", "tests"),
        "roles": Roles(**ROLES),
    }
    values.update(overrides)
    return Config(**values)


def an_installation(name: str = "implementer", **overrides: Any) -> InstallationFacts:
    values: dict[str, Any] = {"suspended": False, "permissions": dict(ROLE_PERMISSIONS[name])}
    values.update(overrides)
    return InstallationFacts(**values)


def a_role(name: str = "implementer", **overrides: Any) -> RoleFacts:
    declared = ROLES[name]
    values: dict[str, Any] = {
        "declared": declared,
        "key_path": Path(f"/home/mcnewcp/.config/my-team/keys/{name}.pem"),
        "key_mode": 0o600,
        "key_repo": None,
        "app_slug": f"{name}-my-team",
        "installation": an_installation(name),
        "installation_reaches_repo": True,
        "bot_user_id": declared.bot_user_id,
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
        "labels": LABELS,
    }
    values.update(overrides)
    return RepoFacts(**values)


def healthy(**overrides: Any) -> Facts:
    """Every check passing — the baseline each case below breaks exactly one of."""
    values: dict[str, Any] = {
        "gh": GhFacts(path="/opt/homebrew/bin/gh", account="mcnewcp"),
        "harness": HarnessFacts(binary="claude", path="/Users/mcnewcp/.local/bin/claude"),
        "config": a_config(),
        "product_owner": ProductOwnerFacts(login="mcnewcp", permission="admin"),
        "repo": a_repo(),
        "protection": Unprotected(branch="main"),
        "roles": {name: a_role(name) for name in ROLE_NAMES},
    }
    values.update(overrides)
    return Facts(**values)


# ── The diagnosis as a whole ────────────────────────────────────────────────────────


def test_a_healthy_repo_passes_every_blocking_check() -> None:
    diagnosis = evaluate(healthy())

    assert diagnosis.ok
    assert not [f for f in diagnosis.findings if f.status is Status.FAIL]


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
        "role identities",
        "merge policy",
        "labels",
        "protection",
    )


def test_one_failing_blocking_check_sinks_the_diagnosis() -> None:
    diagnosis = evaluate(healthy(gh=Unavailable("gh is not on PATH")))

    assert not diagnosis.ok


def test_a_warning_alone_never_sinks_the_diagnosis() -> None:
    diagnosis = evaluate(healthy(config=a_config(required_checks=())))

    assert diagnosis.ok
    assert [f.check for f in diagnosis.findings if f.status is Status.WARN] == ["required checks"]


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


def test_gh_that_could_not_be_asked_reports_what_it_said_rather_than_no_account() -> None:
    # A timed-out `gh` and a logged-out `gh` are two conditions with two fixes, and only
    # one of them is answered by `gh auth login`.
    facts = healthy(gh=GhFacts(path="/usr/bin/gh", account=Unavailable("timed out after 30s")))
    finding = find(facts, "gh")

    assert finding.status is Status.FAIL
    assert "timed out after 30s" in finding.detail
    assert "reported no account" not in finding.detail


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
    facts = healthy(product_owner=ProductOwnerFacts(login="mcnewcp", permission=permission))

    assert status_of(facts, "product owner") is Status.PASS


@pytest.mark.parametrize("permission", ["read", "triage", "none"])
def test_a_product_owner_who_cannot_write_fails(permission: str) -> None:
    facts = healthy(product_owner=ProductOwnerFacts(login="ana", permission=permission))
    finding = find(facts, "product owner")

    assert finding.status is Status.FAIL
    assert "ana" in finding.detail
    assert permission in finding.detail


def test_a_product_owner_that_could_not_be_resolved_fails() -> None:
    reason = "no such user: mcnewcpp"
    finding = find(healthy(product_owner=Unavailable(reason)), "product owner")

    assert finding.status is Status.FAIL
    assert finding.detail == reason


# ── The three roles ──────────────────────────────────────────────────────────────


def with_role(name: str, facts: RoleFacts | Unavailable) -> Facts:
    roles: dict[str, RoleFacts | Unavailable] = {n: a_role(n) for n in ROLE_NAMES}
    roles[name] = facts
    return healthy(roles=roles)


def broken(name: str, **overrides: Any) -> Facts:
    """A sound roster with exactly one thing wrong with `name`."""
    return with_role(name, a_role(name, **overrides))


def test_a_sound_role_reports_the_three_ids_config_keys_on() -> None:
    detail = find(healthy(), "role implementer").detail

    assert "4652114" in detail
    assert "155006997" in detail
    assert "318751706" in detail
    assert "implementer-my-team[bot]" in detail


def test_a_missing_key_file_fails_and_names_the_path() -> None:
    finding = find(broken("judge", key_mode=None), "role judge")

    assert finding.status is Status.FAIL
    assert "/home/mcnewcp/.config/my-team/keys/judge.pem" in finding.detail


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o777, 0o660])
def test_a_key_that_is_not_0600_fails_and_names_the_mode(mode: int) -> None:
    finding = find(broken("reviewer", key_mode=mode), "role reviewer")

    assert finding.status is Status.FAIL
    assert f"{mode:04o}" in finding.detail


def test_a_key_inside_a_repository_fails_even_at_0600() -> None:
    # A key inside a work tree is one `git add .` from being published, which no file
    # mode prevents, so it is reported ahead of the mode.
    finding = find(broken("judge", key_repo=Path("/home/mcnewcp/code/my-team")), "role judge")

    assert finding.status is Status.FAIL
    assert "outside every repo" in finding.detail


def test_a_key_inside_a_repository_names_the_one_it_is_in() -> None:
    # Which clone it is in is what tells a key put in the wrong place from a `key_path`
    # that points somewhere nobody meant.
    elsewhere = Path("/home/mcnewcp/code/somewhere-else")
    finding = find(broken("judge", key_repo=elsewhere), "role judge")

    assert str(elsewhere) in finding.detail


def test_a_key_that_does_not_authenticate_as_its_app_fails() -> None:
    finding = find(broken("judge", app_slug=None), "role judge")

    assert finding.status is Status.FAIL
    assert "4652145" in finding.detail


def test_an_installation_that_does_not_resolve_fails() -> None:
    finding = find(broken("judge", installation=None), "role judge")

    assert finding.status is Status.FAIL
    assert "155007556" in finding.detail


def test_an_installation_that_does_not_cover_this_repo_fails() -> None:
    # It resolves — the App exists and the key signs for it — and the role would still
    # fail its first write, which is exactly what `doctor` is for.
    finding = find(broken("judge", installation_reaches_repo=False), "role judge")

    assert finding.status is Status.FAIL
    assert "does not cover this repo" in finding.detail


def test_a_role_is_still_checkable_when_the_repo_could_not_be_named() -> None:
    # Everything else about a role is provable with its own key alone, so gh being the
    # thing at fault must not take the key checks down with it.
    facts = broken("judge", installation_reaches_repo=None)

    assert status_of(facts, "role judge") is Status.PASS


def test_a_bot_user_id_that_disagrees_with_the_api_fails_naming_both() -> None:
    finding = find(broken("judge", bot_user_id=999), "role judge")

    assert finding.status is Status.FAIL
    assert "318752691" in finding.detail
    assert "999" in finding.detail


def test_a_bot_user_that_does_not_resolve_leaves_the_id_unconfirmed() -> None:
    finding = find(broken("judge", bot_user_id=None), "role judge")

    assert finding.status is Status.FAIL
    assert "unconfirmed" in finding.detail


def test_a_coverage_check_that_could_not_run_gets_its_own_advisory_line() -> None:
    """Covering this repo is the one role check §1 does not enumerate.

    Severity is fixed per check and never per outcome, so the question that cannot block
    cannot be a warning on the line that can. It gets its own name, and the blocking line
    goes on saying that everything §1 does ask for was proven.
    """
    facts = broken("judge", installation_reaches_repo=Unavailable("connection reset"))
    identity, coverage = find(facts, "role judge"), find(facts, "role judge coverage")

    assert identity.status is Status.PASS
    assert "318752691" in identity.detail, "the required checks all passed and still say so"
    assert coverage.severity is Severity.ADVISORY
    assert coverage.status is Status.WARN
    assert "could not be checked" in coverage.detail
    assert "connection reset" in coverage.detail
    assert evaluate(facts).ok


@pytest.mark.parametrize("reaches", [True, False, None])
def test_a_coverage_check_that_answered_adds_no_line_of_its_own(reaches: bool | None) -> None:
    # `True` needs no saying, `False` is already on the blocking line, and `None` means
    # `gh` could not name the repo — which is `gh`'s own failing check, not this one's.
    facts = broken("judge", installation_reaches_repo=reaches)

    assert "role judge coverage" not in checks(facts)


def test_a_bot_id_that_was_never_looked_up_names_the_prerequisite_and_not_the_bot() -> None:
    # `/users/...` is looked up as the human, so `gh` failing is `gh`'s finding. Saying
    # the bot "did not resolve" puts three misleading lines under the one true one.
    facts = broken("judge", bot_user_id=Unavailable("`gh` is not on PATH"))
    finding = find(facts, "role judge")

    assert finding.status is Status.FAIL
    assert "did not resolve" not in finding.detail
    assert "not on PATH" in finding.detail


def test_a_role_that_could_not_be_probed_fails_with_the_reason() -> None:
    finding = find(with_role("reviewer", Unavailable("the config did not parse")), "role reviewer")

    assert finding.status is Status.FAIL
    assert finding.detail == "the config did not parse"


def test_every_role_in_the_roster_gets_a_line_even_when_none_were_probed() -> None:
    diagnosis = evaluate(healthy(roles={}))

    named = [f for f in diagnosis.findings if f.check.removeprefix("role ") in ROLE_NAMES]

    assert [f.check for f in named] == ["role implementer", "role reviewer", "role judge"]
    assert all(f.status is Status.FAIL for f in named)


def test_a_suspended_installation_fails_even_though_it_resolves() -> None:
    # GitHub suspends an installation without removing it: every id still resolves, and
    # the role is granted nothing until a human unsuspends it.
    finding = find(
        broken("judge", installation=an_installation("judge", suspended=True)), "role judge"
    )

    assert finding.status is Status.FAIL
    assert "suspended" in finding.detail


@pytest.mark.parametrize(
    ("name", "granted", "named"),
    [
        # Missing authority: the role cannot do its job.
        ("implementer", {"contents": "read"}, "contents"),
        ("judge", {"issues": "read"}, "issues"),
        # Authority it must not hold: the matrix is two prohibitions as well as a grant.
        ("reviewer", {"contents": "write"}, "contents"),
        ("implementer", {"issues": "write"}, "issues"),
    ],
)
def test_an_installation_that_does_not_match_the_role_s_authority_fails(
    name: str, granted: Mapping[str, str], named: str
) -> None:
    permissions = {**ROLE_PERMISSIONS[name], **granted}
    finding = find(
        broken(name, installation=an_installation(name, permissions=permissions)), f"role {name}"
    )

    assert finding.status is Status.FAIL
    assert named in finding.detail
    assert granted[named] in finding.detail


def test_an_installation_missing_a_permission_outright_says_no_access() -> None:
    permissions = {k: v for k, v in ROLE_PERMISSIONS["judge"].items() if k != "issues"}
    finding = find(
        broken("judge", installation=an_installation("judge", permissions=permissions)),
        "role judge",
    )

    assert finding.status is Status.FAIL
    assert "issues no access" in finding.detail


def test_a_grant_that_could_not_be_read_warns_on_its_own_line_and_never_blocks() -> None:
    """What an installation grants is a check §1 does not enumerate.

    Severity is fixed per check and never per outcome, so the question that cannot block
    gets its own name — and the blocking line goes on saying that everything §1 does ask
    for was proven.
    """
    unreadable = an_installation("judge", permissions=Unavailable("described unrecognisably"))
    facts = broken("judge", installation=unreadable)
    identity, authority = find(facts, "role judge"), find(facts, "role judge authority")

    assert identity.status is Status.PASS
    assert "318752691" in identity.detail, "the required checks all passed and still say so"
    assert authority.severity is Severity.ADVISORY
    assert authority.status is Status.WARN
    assert "could not be read" in authority.detail
    assert evaluate(facts).ok


def test_a_grant_that_was_read_adds_no_line_of_its_own() -> None:
    assert "role judge authority" not in checks(healthy())


def test_a_permission_the_matrix_does_not_name_is_not_judged() -> None:
    # GitHub grants every App `metadata` by itself, so a matrix read as an exhaustive
    # list would fail every correctly provisioned role.
    permissions = {**ROLE_PERMISSIONS["reviewer"], "metadata": "read"}

    assert (
        status_of(
            broken("reviewer", installation=an_installation("reviewer", permissions=permissions)),
            "role reviewer",
        )
        is Status.PASS
    )


def test_the_authority_matrix_covers_the_whole_roster() -> None:
    # A fourth role added to `Roles` without a row here would be checked against a
    # `KeyError` rather than against the spec's table.
    assert tuple(ROLE_PERMISSIONS) == ROLE_NAMES


@pytest.mark.parametrize(
    "addition",
    [
        {"installation_reaches_repo": False},
        {"installation": an_installation("judge", suspended=True)},
    ],
)
def test_a_check_the_spec_does_not_enumerate_never_reports_in_place_of_one_it_does(
    addition: Mapping[str, Any],
) -> None:
    """The one ordering rule inside a role's line.

    Coverage, suspension and the authority matrix are this design's own additions. A
    role whose `bot_user_id` disagrees with the API has failed a check §1 names, and
    reporting an addition instead would name a condition the spec never asked about
    while the required one went unmentioned.
    """
    finding = find(broken("judge", bot_user_id=999, **addition), "role judge")

    assert "318752691" in finding.detail
    assert "999" in finding.detail


# ── One identity per role ────────────────────────────────────────────────────────


def sharing(name: str, **overrides: Any) -> Facts:
    """A roster where `name` declares somebody else's ids."""
    declared = ROLES["implementer"]
    values: dict[str, Any] = {
        "app_id": declared.app_id,
        "bot_user_id": declared.bot_user_id,
        "installation_id": ROLES[name].installation_id,
        "key_path": ROLES[name].key_path,
    }
    values.update(overrides)
    roles = {**ROLES, name: RoleConfig(**values)}
    return healthy(config=a_config(roles=Roles(**roles)))


def test_three_distinct_identities_pass() -> None:
    finding = find(healthy(), "role identities")

    assert finding.status is Status.PASS
    assert finding.severity is Severity.BLOCKING


def test_two_roles_sharing_one_app_cannot_both_open_and_approve() -> None:
    # Platform-enforced rather than orchestrator-policed: the App is refused with a
    # `422` and no review is recorded, at the end of a round rather than before one.
    finding = find(sharing("judge"), "role identities")

    assert finding.status is Status.FAIL
    assert "app_id 4652114" in finding.detail
    assert "implementer" in finding.detail and "judge" in finding.detail


def test_two_roles_sharing_one_bot_user_fail_on_that_alone() -> None:
    # A bot user id is what a review is matched on, so two roles behind one of them are
    # indistinguishable to the state machine even with two Apps.
    finding = find(sharing("reviewer", app_id=4608397), "role identities")

    assert finding.status is Status.FAIL
    assert "bot_user_id 318751706" in finding.detail
    assert "app_id" not in finding.detail


def test_the_roster_check_is_dropped_when_the_config_did_not_parse() -> None:
    # There are no ids to compare in a file that would not load, and the config failure
    # above already says so.
    assert "role identities" not in checks(healthy(config=Unavailable("no config file")))


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


def test_a_label_listing_that_failed_fails_only_the_label_check() -> None:
    # Two requests, two answers: the merge policy GitHub already described is not put in
    # doubt by a listing that timed out beside it.
    facts = healthy(repo=a_repo(labels=Unavailable("gh api repos/.../labels: timed out")))

    assert status_of(facts, "labels") is Status.FAIL
    assert status_of(facts, "merge policy") is Status.PASS
    assert "timed out" in find(facts, "labels").detail


def test_both_labels_present_passes() -> None:
    assert status_of(healthy(), "labels") is Status.PASS


@pytest.mark.parametrize("missing", [AUTHORIZATION_LABEL, ESCALATION_LABEL])
def test_a_missing_label_fails_and_names_it(missing: str) -> None:
    remaining = tuple(name for name in LABELS if name != missing)
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


def test_every_finding_reaches_the_rendered_diagnosis() -> None:
    diagnosis = evaluate(healthy())
    rendered = render(diagnosis)

    for finding in diagnosis.findings:
        assert finding.check in rendered
        assert finding.detail in rendered


def test_a_clean_diagnosis_says_so_and_names_no_failure() -> None:
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
