"""The provisioning wizard, at the one seam a test can hold it to.

Almost all of `scripts/register-role-app.sh` is browser choreography, which no test can
reach. One part is not: the config blocks it ends with. Those are the whole point of
the wizard — the ids GitHub shows once, in the shape the parser accepts — and they are
also the part that silently rots when the config model moves. So the wizard is run in
library mode, asked for its blocks, and the blocks are handed to `parse_config`.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from my_team.core.config import KEY_MODE, parse_config

WIZARD = Path(__file__).resolve().parents[1] / "scripts" / "register-role-app.sh"

RECORDED = {
    "implementer": (4652114, 318751706, 155006997),
    "reviewer": (4608397, 317436782, 154043927),
    "judge": (4652145, 318752691, 155007556),
}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="the wizard is bash")


def wizard(home: Path, script: str) -> str:
    """Source the wizard for its functions alone, then run `script` against them."""
    result = subprocess.run(
        ["bash", "-c", f"source {WIZARD}\n{script}"],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "MT_WIZARD_LIB": "1", "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def provisioned(home: Path, *roles: str) -> Path:
    """The ids the wizard's verify stage records, for the roles named."""
    recorded = home / ".config" / "my-team"
    recorded.mkdir(parents=True, exist_ok=True)
    for role in roles:
        app_id, bot_user_id, installation_id = RECORDED[role]
        (recorded / f"{role}.env").write_text(
            f"ROLE={role}\nAPP_ID={app_id}\nAPP_SLUG={role}-my-team\n"
            f"BOT_USER_ID={bot_user_id}\nINSTALLATION_ID={installation_id}\n"
        )
    return home


def test_the_wizard_is_syntactically_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(WIZARD)], capture_output=True).returncode == 0


def test_the_three_blocks_it_ends_with_are_a_config_the_parser_accepts(
    tmp_path: Path,
) -> None:
    provisioned(tmp_path, *RECORDED)
    blocks = wizard(tmp_path, "for r in implementer reviewer judge; do config_block $r; done")

    config = parse_config(
        tomllib.loads(f'product_owner = "mcnewcp"\nrequired_checks = []\n{blocks}')
    )

    for role, (app_id, bot_user_id, installation_id) in RECORDED.items():
        declared = getattr(config.roles, role)
        assert (declared.app_id, declared.bot_user_id, declared.installation_id) == (
            app_id,
            bot_user_id,
            installation_id,
        )


def test_the_key_path_it_writes_is_kept_as_a_tilde(tmp_path: Path) -> None:
    # Config stores `key_path` exactly as written so that parsing never depends on
    # $HOME. A wizard that pasted an expanded path would make one machine's config
    # unusable on another.
    provisioned(tmp_path, "judge")

    assert 'key_path        = "~/.config/my-team/keys/judge.pem"' in wizard(
        tmp_path, "config_block judge"
    )


def test_a_role_that_was_never_provisioned_emits_a_comment_rather_than_half_a_block(
    tmp_path: Path,
) -> None:
    provisioned(tmp_path)
    emitted = wizard(tmp_path, "config_block reviewer || true")

    assert emitted.startswith("# [roles.reviewer]")
    assert "app_id" not in emitted


def test_a_role_whose_bot_user_id_never_resolved_is_not_offered_as_complete(
    tmp_path: Path,
) -> None:
    # The bot user id is not derivable from `app_id`, so a block missing it would parse
    # and then match no review at all.
    provisioned(tmp_path, "judge")
    recorded = tmp_path / ".config" / "my-team" / "judge.env"
    recorded.write_text(recorded.read_text().replace("BOT_USER_ID=318752691\n", ""))

    assert wizard(tmp_path, "config_block judge || true").startswith("# [roles.judge]")


def test_the_wizard_stores_keys_at_the_mode_the_config_model_requires() -> None:
    # Two places state the mode — the wizard writes it and `doctor` checks it — so this
    # binds the writer to the constant the reader uses.
    assert f"chmod {KEY_MODE:o}" in WIZARD.read_text()
