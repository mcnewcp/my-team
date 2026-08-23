"""Reading `.my-team/config.toml` off disk — the I/O half of the fetch/parse split."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from my_team.config_file import config_path, load_config
from my_team.core.config import ConfigError

WELL_FORMED = """
product_owner   = "mcnewcp"
required_checks = []

[roles.implementer]
app_id          = 1
bot_user_id     = 2
installation_id = 3
key_path        = "~/keys/implementer.pem"

[roles.reviewer]
app_id          = 4
bot_user_id     = 5
installation_id = 6
key_path        = "~/keys/reviewer.pem"

[roles.judge]
app_id          = 7
bot_user_id     = 8
installation_id = 9
key_path        = "~/keys/judge.pem"
"""


def write_config(repo_root: Path, body: str) -> Path:
    path = config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_the_config_lives_at_a_fixed_path_under_the_repo_root() -> None:
    assert config_path(Path("/somewhere/target")) == Path("/somewhere/target/.my-team/config.toml")


def test_a_well_formed_file_loads(tmp_path: Path) -> None:
    write_config(tmp_path, WELL_FORMED)

    config = load_config(tmp_path)

    assert config.product_owner == "mcnewcp"
    assert config.required_checks == ()
    assert config.roles.judge.app_id == 7


def test_a_missing_file_names_the_path_and_the_command_that_writes_it(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=re.escape(str(config_path(tmp_path)))) as caught:
        load_config(tmp_path)

    assert "my-team init" in str(caught.value)


def test_malformed_toml_names_the_path(tmp_path: Path) -> None:
    write_config(tmp_path, 'product_owner = "unterminated')

    with pytest.raises(ConfigError, match=re.escape(str(config_path(tmp_path)))):
        load_config(tmp_path)


def test_a_bad_key_names_both_the_path_and_the_key(tmp_path: Path) -> None:
    write_config(tmp_path, WELL_FORMED.replace("required_checks = []", ""))

    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)

    assert str(config_path(tmp_path)) in str(caught.value)
    assert "required_checks" in str(caught.value)
