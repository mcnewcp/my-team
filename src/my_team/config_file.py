"""Where `.my-team/config.toml` lives, and how it is read.

The read is here rather than in `my_team.core.config` for the same reason `fetch` is
split from `parse` at the GitHub port: the core stays a pure function over plain data,
and this module is the only place a missing or unreadable file can be reported. Every
error it raises is a `ConfigError` naming the path, since the reader's first question
is always which file the tool was looking at.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from my_team.core.config import Config, ConfigError, parse_config

CONFIG_RELATIVE_PATH = Path(".my-team") / "config.toml"


def config_path(repo_root: Path) -> Path:
    """The config file for a target repo checked out at `repo_root`."""
    return repo_root / CONFIG_RELATIVE_PATH


def load_config(repo_root: Path) -> Config:
    """Read and parse the target repo's config, or raise `ConfigError`."""
    path = config_path(repo_root)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"{path}: no config file — run `my-team init`") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: malformed TOML — {error}") from error

    try:
        return parse_config(data)
    except ConfigError as error:
        raise ConfigError(f"{path}: {error}") from error
