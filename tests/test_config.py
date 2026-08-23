"""The typed config model — every key in the spec's §1, and the errors it raises.

Each parse error is asserted to name the offending key, because the key name is the
whole value of the message to whoever mistyped it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import MISSING, fields, replace
from pathlib import Path
from typing import Any

import pytest

from my_team.core.config import Config, ConfigError, RoleConfig, Roles, parse_config

# The example from docs/spec/v0.1.md §1, verbatim.
DOCUMENTED_EXAMPLE = """
product_owner   = "mcnewcp"
required_checks = ["lint", "types", "tests"]

smart_zone_tokens = 60000
permission_mode   = "acceptEdits"
model             = "claude-sonnet-5"

require_approval_to_merge = false

max_revision_rounds  = 3
max_ci_repair_rounds = 3
max_rounds           = 8
max_stall_minutes    = 90
max_action_minutes   = 30
poll_interval        = 15

[roles.implementer]
app_id          = 4652114
bot_user_id     = 318751706
installation_id = 155006997
key_path        = "~/.config/my-team/keys/implementer.pem"

[roles.reviewer]
app_id          = 4608397
bot_user_id     = 317436782
installation_id = 154043927
key_path        = "~/.config/my-team/keys/reviewer.pem"

[roles.judge]
app_id          = 4652145
bot_user_id     = 318752691
installation_id = 155007556
key_path        = "~/.config/my-team/keys/judge.pem"
"""


def minimal(**overrides: Any) -> dict[str, Any]:
    """The smallest config that parses: the three keys with no default, plus roles."""
    role = {
        "app_id": 1,
        "bot_user_id": 2,
        "installation_id": 3,
        "key_path": "~/keys/x.pem",
    }
    data: dict[str, Any] = {
        "product_owner": "mcnewcp",
        "required_checks": ["lint"],
        "roles": {name: dict(role) for name in ("implementer", "reviewer", "judge")},
    }
    data.update(overrides)
    return data


def a_config(**overrides: Any) -> Config:
    """A `Config` built directly, the way a config source that is not a file would."""
    role = RoleConfig(app_id=1, bot_user_id=2, installation_id=3, key_path=Path("~/keys/x.pem"))
    values: dict[str, Any] = {
        "product_owner": "mcnewcp",
        "required_checks": ("lint",),
        "roles": Roles(implementer=role, reviewer=role, judge=role),
    }
    values.update(overrides)
    return Config(**values)


def test_the_documented_example_parses_to_the_documented_values() -> None:
    config = parse_config(tomllib.loads(DOCUMENTED_EXAMPLE))

    assert config == Config(
        product_owner="mcnewcp",
        required_checks=("lint", "types", "tests"),
        roles=Roles(
            implementer=RoleConfig(
                app_id=4652114,
                bot_user_id=318751706,
                installation_id=155006997,
                key_path=Path("~/.config/my-team/keys/implementer.pem"),
            ),
            reviewer=RoleConfig(
                app_id=4608397,
                bot_user_id=317436782,
                installation_id=154043927,
                key_path=Path("~/.config/my-team/keys/reviewer.pem"),
            ),
            judge=RoleConfig(
                app_id=4652145,
                bot_user_id=318752691,
                installation_id=155007556,
                key_path=Path("~/.config/my-team/keys/judge.pem"),
            ),
        ),
        smart_zone_tokens=60000,
        permission_mode="acceptEdits",
        model="claude-sonnet-5",
        require_approval_to_merge=False,
        max_revision_rounds=3,
        max_ci_repair_rounds=3,
        max_rounds=8,
        max_stall_minutes=90,
        max_action_minutes=30,
        poll_interval=15,
    )


def test_every_optional_key_has_its_documented_default() -> None:
    config = parse_config(minimal())

    assert config.smart_zone_tokens == 60000
    assert config.permission_mode == "acceptEdits"
    assert config.model is None
    assert config.require_approval_to_merge is False
    assert config.max_revision_rounds == 3
    assert config.max_ci_repair_rounds == 3
    assert config.max_rounds == 8
    assert config.max_stall_minutes == 90
    assert config.max_action_minutes == 30
    assert config.poll_interval == 15


def test_required_checks_may_be_empty() -> None:
    assert parse_config(minimal(required_checks=[])).required_checks == ()


def test_key_path_is_kept_as_written() -> None:
    # Expansion happens where the key is read, so parsing stays independent of $HOME.
    config = parse_config(minimal())
    assert config.roles.judge.key_path == Path("~/keys/x.pem")


@pytest.mark.parametrize(
    ("removed", "named"),
    [
        (("product_owner",), "product_owner"),
        (("required_checks",), "required_checks"),
        (("roles",), "roles"),
        (("roles", "reviewer"), "roles.reviewer"),
        (("roles", "implementer", "bot_user_id"), "roles.implementer.bot_user_id"),
    ],
)
def test_a_missing_required_key_is_named(removed: tuple[str, ...], named: str) -> None:
    data = minimal()
    target: Any = data
    for step in removed[:-1]:
        target = target[step]
    del target[removed[-1]]

    with pytest.raises(ConfigError, match=re.escape(named)):
        parse_config(data)


@pytest.mark.parametrize(
    ("data", "named"),
    [
        (minimal(max_stall_min=5), "max_stall_min"),
        (minimal(trusted_humans=["mcnewcp"]), "trusted_humans"),
    ],
)
def test_an_unknown_top_level_key_is_named(data: dict[str, Any], named: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(named)):
        parse_config(data)


def test_an_unknown_role_is_named() -> None:
    data = minimal()
    data["roles"]["reviewr"] = dict(data["roles"]["reviewer"])

    with pytest.raises(ConfigError, match=re.escape("roles.reviewr")):
        parse_config(data)


def test_an_unknown_key_inside_a_role_is_named() -> None:
    data = minimal()
    data["roles"]["judge"]["slug"] = "my-team-judge"

    with pytest.raises(ConfigError, match=re.escape("roles.judge.slug")):
        parse_config(data)


@pytest.mark.parametrize(
    ("data", "named"),
    [
        (minimal(product_owner=7), "product_owner"),
        (minimal(product_owner=""), "product_owner"),
        (minimal(required_checks="lint"), "required_checks"),
        (minimal(required_checks=["lint", 3]), "required_checks"),
        (minimal(required_checks=["lint", ""]), "required_checks"),
        (minimal(permission_mode=True), "permission_mode"),
        (minimal(model=3), "model"),
        (minimal(require_approval_to_merge="yes"), "require_approval_to_merge"),
        (minimal(smart_zone_tokens="60000"), "smart_zone_tokens"),
        (minimal(smart_zone_tokens=1.5), "smart_zone_tokens"),
        (minimal(product_owner={"login": "mcnewcp"}), "product_owner"),
        (minimal(max_rounds=True), "max_rounds"),
        (minimal(roles=[]), "roles"),
    ],
)
def test_a_key_of_the_wrong_type_is_named(data: dict[str, Any], named: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(named)):
        parse_config(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_id", "4652114"),
        ("bot_user_id", True),
        ("installation_id", 0),
        ("key_path", 3),
        ("key_path", ""),
    ],
)
def test_a_role_field_of_the_wrong_type_is_named(field: str, value: object) -> None:
    data = minimal()
    data["roles"]["implementer"][field] = value

    with pytest.raises(ConfigError, match=re.escape(f"roles.implementer.{field}")):
        parse_config(data)


@pytest.mark.parametrize("key", ["max_revision_rounds", "max_ci_repair_rounds", "max_rounds"])
def test_zero_disables_the_round_limits(key: str) -> None:
    assert getattr(parse_config(minimal(**{key: 0})), key) == 0


@pytest.mark.parametrize(
    "key",
    [
        "smart_zone_tokens",
        "max_stall_minutes",
        "max_action_minutes",
        "poll_interval",
    ],
)
def test_the_limits_that_cannot_be_disabled_reject_zero(key: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(key)):
        parse_config(minimal(**{key: 0}))


@pytest.mark.parametrize(
    "key",
    [
        "smart_zone_tokens",
        "max_revision_rounds",
        "max_ci_repair_rounds",
        "max_rounds",
        "max_stall_minutes",
        "max_action_minutes",
        "poll_interval",
    ],
)
def test_no_limit_may_be_negative(key: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(key)):
        parse_config(minimal(**{key: -1}))


def test_the_config_surface_is_exactly_the_documented_keys() -> None:
    assert {f.name for f in fields(Config)} == {
        "product_owner",
        "required_checks",
        "roles",
        "smart_zone_tokens",
        "permission_mode",
        "model",
        "require_approval_to_merge",
        "max_revision_rounds",
        "max_ci_repair_rounds",
        "max_rounds",
        "max_stall_minutes",
        "max_action_minutes",
        "poll_interval",
    }


def test_every_limit_is_named_max_and_nothing_is_named_cap() -> None:
    # `cap` is spoken for twice already — as an _Avoid_ term for the smart zone, and as
    # the harness seam's own parameter — so config never uses it.
    names = {f.name for f in fields(Config)} | {f.name for f in fields(RoleConfig)}

    assert not [name for name in names if "cap" in name]
    assert {name for name in names if "round" in name or "minutes" in name} == {
        "max_revision_rounds",
        "max_ci_repair_rounds",
        "max_rounds",
        "max_stall_minutes",
        "max_action_minutes",
    }


def test_a_role_keys_on_numeric_ids_and_never_on_a_slug() -> None:
    assert {f.name for f in fields(RoleConfig)} == {
        "app_id",
        "bot_user_id",
        "installation_id",
        "key_path",
    }

    role = parse_config(minimal()).roles.implementer
    assert isinstance(role.app_id, int)
    assert isinstance(role.bot_user_id, int)
    assert isinstance(role.installation_id, int)


DEFAULTS = {f.name: f.default for f in fields(Config) if f.default is not MISSING}


def a_value_other_than(default: object) -> object:
    if isinstance(default, bool):
        return not default
    if isinstance(default, int):
        return default + 1
    return "changed"


@pytest.mark.parametrize("key", sorted(DEFAULTS))
def test_every_optional_key_is_read_from_the_file(key: str) -> None:
    """A key that reached the model but not the parser would be silently ignored."""
    declared = a_value_other_than(DEFAULTS[key])

    assert getattr(parse_config(minimal(**{key: declared})), key) == declared


@pytest.mark.parametrize(("stall", "action"), [(30, 30), (29, 30)])
def test_the_stall_clock_must_outlast_one_dispatch(stall: int, action: int) -> None:
    # Otherwise one slow dispatch trips the detector watching it.
    with pytest.raises(ConfigError, match="max_stall_minutes"):
        parse_config(minimal(max_stall_minutes=stall, max_action_minutes=action))


def test_the_stall_clock_may_be_one_minute_longer_than_a_dispatch() -> None:
    config = parse_config(minimal(max_stall_minutes=31, max_action_minutes=30))

    assert config.max_stall_minutes == 31


@pytest.mark.parametrize(("stall", "action"), [(30, 30), (29, 30)])
def test_direct_construction_rejects_a_stall_clock_that_cannot_outlast_a_dispatch(
    stall: int, action: int
) -> None:
    # The rule belongs to the model, not the parser: a config source that never sees a
    # TOML file must not be able to mint a value the file parser would have rejected.
    with pytest.raises(ConfigError, match="max_stall_minutes"):
        a_config(max_stall_minutes=stall, max_action_minutes=action)


def test_a_dataclass_copy_cannot_move_one_clock_past_the_other() -> None:
    config = a_config()

    with pytest.raises(ConfigError, match="max_stall_minutes"):
        replace(config, max_stall_minutes=config.max_action_minutes)


@pytest.mark.parametrize(("stall", "action"), [(31, 30), (90, 30), (2, 1)])
def test_a_stall_clock_that_outlasts_a_dispatch_is_constructible(stall: int, action: int) -> None:
    config = a_config(max_stall_minutes=stall, max_action_minutes=action)

    assert (config.max_stall_minutes, config.max_action_minutes) == (stall, action)


def test_the_documented_clock_defaults_are_constructible() -> None:
    # The pair the spec ships has to satisfy the rule the model now enforces.
    config = a_config()

    assert (config.max_stall_minutes, config.max_action_minutes) == (90, 30)


def test_the_clock_failure_names_both_values_and_the_relation() -> None:
    # A message carrying only one of the two clocks leaves the reader guessing which
    # of them to move.
    with pytest.raises(ConfigError) as raised:
        a_config(max_stall_minutes=20, max_action_minutes=30)

    message = str(raised.value)
    assert "max_stall_minutes (20)" in message
    assert "max_action_minutes (30)" in message
    assert "must exceed" in message
