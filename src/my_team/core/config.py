"""The typed model of `.my-team/config.toml`, and the pure parse that produces it.

Reading the file is somebody else's job (`my_team.config_file`); this module turns an
already-decoded TOML table into a `Config` or raises `ConfigError` naming the key that
is wrong. Naming the key is the whole point of the error: a mistyped `max_stall_min`
that parsed silently would leave the limit it looks like it sets switched off.

Two naming rules the spec fixes, and a test guards:

- every limit is `max_*`. `cap` is spoken for twice already — as an `_Avoid_` term for
  the **smart zone**, and as the harness seam's own parameter — so config never uses it.
- roles never key on an App slug — §1 fixes the table key as the role name. That rule is
  about the key and not the fields: `RoleConfig` carries no name field for the narrower
  reason that §1's listing of role keys stops at these four. §7's briefing does want a
  per-role login beside the ids, and where that comes from is settled in #55, not here.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Final, TypedDict


class ConfigError(ValueError):
    """A config that cannot be turned into a `Config`. The message names the key."""


@dataclass(frozen=True, slots=True)
class RoleConfig:
    """One role's identity: three numeric ids and the key that signs for them.

    `key_path` is stored as written, `~` and all. Expanding it here would make parsing
    depend on `$HOME`; it is expanded where the key is read.
    """

    app_id: int
    bot_user_id: int
    installation_id: int
    key_path: Path


@dataclass(frozen=True, slots=True)
class Roles:
    """The three roles, as named fields rather than a lookup that can come up empty."""

    implementer: RoleConfig
    reviewer: RoleConfig
    judge: RoleConfig


@dataclass(frozen=True, slots=True)
class Config:
    """Everything `.my-team/config.toml` declares. Defaults live here and nowhere else.

    The three fields without defaults are the ones nothing can infer: who the product
    owner is, which checks are the gate (`[]` is a legal declaration — it means no CI
    gate — but it has to be *declared*), and the role identities.

    The defaults for the limits are guesses awaiting calibration against real runs.
    """

    product_owner: str
    required_checks: tuple[str, ...]
    roles: Roles

    smart_zone_tokens: int = 60_000
    permission_mode: str = "acceptEdits"
    model: str | None = None

    require_approval_to_merge: bool = False

    max_revision_rounds: int = 3
    max_ci_repair_rounds: int = 3
    max_rounds: int = 8
    max_stall_minutes: int = 90
    max_action_minutes: int = 30
    poll_interval: int = 15


_TOP_LEVEL_KEYS: Final = frozenset(f.name for f in fields(Config))
_ROLE_NAMES: Final = tuple(f.name for f in fields(Roles))
_ROLE_KEYS: Final = frozenset(f.name for f in fields(RoleConfig))

_TYPE_NAMES: Final[Mapping[type, str]] = {
    bool: "a boolean",
    int: "an integer",
    str: "a string",
    float: "a float",
    list: "an array",
    dict: "a table",
}


def _type_name(value: object) -> str:
    return _TYPE_NAMES.get(type(value), type(value).__name__)


class _Table:
    """One TOML table, and the dotted path that names its keys in an error."""

    def __init__(self, data: Mapping[str, object], path: str) -> None:
        self._data = data
        self._path = path

    @classmethod
    def under(cls, value: object, path: str) -> _Table:
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: expected a table, got {_type_name(value)}")
        return cls(value, path)

    def _named(self, key: str) -> str:
        return f"{self._path}.{key}" if self._path else key

    def reject_unknown(self, known: Collection[str]) -> None:
        for key in self._data:
            if key not in known:
                raise ConfigError(f"unknown key: {self._named(key)}")

    def has(self, key: str) -> bool:
        return key in self._data

    def _require(self, key: str) -> object:
        if key not in self._data:
            raise ConfigError(f"missing required key: {self._named(key)}")
        return self._data[key]

    def string(self, key: str) -> str:
        value = self._require(key)
        if not isinstance(value, str):
            raise ConfigError(f"{self._named(key)}: expected a string, got {_type_name(value)}")
        if not value.strip():
            raise ConfigError(f"{self._named(key)}: must not be empty")
        return value

    def integer(self, key: str, *, minimum: int) -> int:
        value = self._require(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{self._named(key)}: expected an integer, got {_type_name(value)}")
        if value < minimum:
            raise ConfigError(f"{self._named(key)}: must be at least {minimum}, got {value}")
        return value

    def boolean(self, key: str) -> bool:
        value = self._require(key)
        if not isinstance(value, bool):
            raise ConfigError(f"{self._named(key)}: expected a boolean, got {_type_name(value)}")
        return value

    def strings(self, key: str) -> tuple[str, ...]:
        value = self._require(key)
        if not isinstance(value, list):
            raise ConfigError(
                f"{self._named(key)}: expected an array of strings, got {_type_name(value)}"
            )
        for index, item in enumerate(value):
            named = f"{self._named(key)}[{index}]"
            if not isinstance(item, str):
                raise ConfigError(f"{named}: expected a string, got {_type_name(item)}")
            if not item.strip():
                raise ConfigError(f"{named}: must not be empty")
        return tuple(value)

    def file_path(self, key: str) -> Path:
        return Path(self.string(key))

    def table(self, key: str) -> _Table:
        return _Table.under(self._require(key), self._named(key))


class _Optional(TypedDict, total=False):
    """The keys `parse_config` passes through only when the file declares them.

    Anything absent here falls through to the default on `Config`, which is what keeps
    the defaults written down exactly once.
    """

    smart_zone_tokens: int
    permission_mode: str
    model: str | None
    require_approval_to_merge: bool
    max_revision_rounds: int
    max_ci_repair_rounds: int
    max_rounds: int
    max_stall_minutes: int
    max_action_minutes: int
    poll_interval: int


def parse_config(data: Mapping[str, object]) -> Config:
    """Turn a decoded TOML table into a `Config`, or raise `ConfigError`.

    `0` disables the three round limits, so they floor at zero. The other four floor at
    one: neither clock can be disabled — a zero-minute action budget is not a hang
    detector — and a zero-second poll or a zero-token smart zone is a spin rather than
    a setting.

    One relationship holds between two keys rather than within one: the stall clock has
    to outlast a single dispatch, or one slow action trips the detector watching it.
    """
    table = _Table(data, "")
    table.reject_unknown(_TOP_LEVEL_KEYS)

    optional: _Optional = {}
    if table.has("smart_zone_tokens"):
        optional["smart_zone_tokens"] = table.integer("smart_zone_tokens", minimum=1)
    if table.has("permission_mode"):
        optional["permission_mode"] = table.string("permission_mode")
    if table.has("model"):
        optional["model"] = table.string("model")
    if table.has("require_approval_to_merge"):
        optional["require_approval_to_merge"] = table.boolean("require_approval_to_merge")
    if table.has("max_revision_rounds"):
        optional["max_revision_rounds"] = table.integer("max_revision_rounds", minimum=0)
    if table.has("max_ci_repair_rounds"):
        optional["max_ci_repair_rounds"] = table.integer("max_ci_repair_rounds", minimum=0)
    if table.has("max_rounds"):
        optional["max_rounds"] = table.integer("max_rounds", minimum=0)
    if table.has("max_stall_minutes"):
        optional["max_stall_minutes"] = table.integer("max_stall_minutes", minimum=1)
    if table.has("max_action_minutes"):
        optional["max_action_minutes"] = table.integer("max_action_minutes", minimum=1)
    if table.has("poll_interval"):
        optional["poll_interval"] = table.integer("poll_interval", minimum=1)

    config = Config(
        product_owner=table.string("product_owner"),
        required_checks=table.strings("required_checks"),
        roles=_parse_roles(table.table("roles")),
        **optional,
    )
    if config.max_stall_minutes <= config.max_action_minutes:
        raise ConfigError(
            f"max_stall_minutes ({config.max_stall_minutes}) must exceed max_action_minutes "
            f"({config.max_action_minutes}), or one slow dispatch trips the stall detector"
        )
    return config


def _parse_roles(table: _Table) -> Roles:
    table.reject_unknown(_ROLE_NAMES)
    return Roles(
        implementer=_parse_role(table.table("implementer")),
        reviewer=_parse_role(table.table("reviewer")),
        judge=_parse_role(table.table("judge")),
    )


def _parse_role(table: _Table) -> RoleConfig:
    table.reject_unknown(_ROLE_KEYS)
    return RoleConfig(
        app_id=table.integer("app_id", minimum=1),
        bot_user_id=table.integer("bot_user_id", minimum=1),
        installation_id=table.integer("installation_id", minimum=1),
        key_path=table.file_path("key_path"),
    )
