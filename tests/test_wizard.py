"""The provisioning wizard, at the one seam a test can hold it to.

`scripts/register-role-app.sh` is mostly browser choreography, and the pages it walks a
human through are not a thing to assert on. What is: the config blocks it ends with —
the ids GitHub shows once, in the shape the parser accepts — and the two facts they are
gated on, that the key on disk is one the loop will read and that a run proved the ids
in this run rather than some earlier one. Those rot silently when the config model
moves, or when a run that failed halfway leaves ids behind.

So the script is sourced in library mode, which defines every function and stops before
the prelude. Stages are driven from there like any other function, over a `$HOME` the
test owns, and the file each one leaves behind is what is asserted on.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from my_team.core.config import (
    KEY_MODE,
    ROLE_NAMES,
    ROLE_PERMISSIONS,
    UNAVOIDABLE_PERMISSION,
    parse_config,
)
from my_team.credentials import key_mode, repo_containing

WIZARD = Path(__file__).resolve().parents[1] / "scripts" / "register-role-app.sh"

RECORDED = {
    "implementer": (4652114, 318751706, 155006997),
    "reviewer": (4608397, 317436782, 154043927),
    "judge": (4652145, 318752691, 155007556),
}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="the wizard is bash")


def run_wizard(
    home: Path, script: str, *, path: str = "/usr/bin:/bin", stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    """Source the wizard for its functions alone, then run `script` against them.

    `stdin` is always a pipe, never the terminal the suite was started from: the stages
    ask the human questions, and one that reached a real terminal would hang the run
    rather than fail it.
    """
    return subprocess.run(
        ["bash", "-c", f"source {WIZARD}\n{script}"],
        capture_output=True,
        text=True,
        input=stdin,
        env={"HOME": str(home), "MT_WIZARD_LIB": "1", "PATH": path},
    )


def wizard(home: Path, script: str, *, path: str = "/usr/bin:/bin", stdin: str = "") -> str:
    result = run_wizard(home, script, path=path, stdin=stdin)
    assert result.returncode == 0, result.stderr
    return result.stdout


def succeeds(home: Path, script: str) -> bool:
    return run_wizard(home, script).returncode == 0


def keys(home: Path) -> Path:
    return home / ".config" / "my-team" / "keys"


@pytest.fixture(scope="session")
def real_key() -> str:
    """A key `openssl` reads back, because reading it back is what the wizard checks.

    The structure `rsa_pem` builds is enough to reach a signer and not enough to be
    read as a key, which is exactly the distinction under test here.
    """
    if shutil.which("openssl") is None:  # pragma: no cover — present on every CI runner
        pytest.skip("the wizard reads keys with openssl, which is not installed")
    return subprocess.run(
        ["openssl", "genrsa", "2048"], capture_output=True, text=True, check=True
    ).stdout


def provisioned(home: Path, key_pem: str, *roles: str) -> Path:
    """Each role as a verify stage that ran to the end leaves it.

    Three ids read back off the App, the marker saying this run proved them, and a key
    at the mode the wizard stores. Every case below removes exactly one of those.
    """
    recorded = home / ".config" / "my-team"
    keys(home).mkdir(parents=True, exist_ok=True)
    for role in roles:
        app_id, bot_user_id, installation_id = RECORDED[role]
        (recorded / f"{role}.env").write_text(
            f"ROLE={role}\nAPP_ID={app_id}\nAPP_SLUG={role}-my-team\n"
            f"BOT_USER_ID={bot_user_id}\nINSTALLATION_ID={installation_id}\n"
            f"VERIFIED={role}\n"
        )
        key = keys(home) / f"{role}.pem"
        key.write_text(key_pem)
        key.chmod(KEY_MODE)
    return home


def test_the_wizard_is_syntactically_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(WIZARD)], capture_output=True).returncode == 0


# ── What the wizard will call a role key ─────────────────────────────────────────


def test_a_readable_rsa_key_at_0600_is_a_role_key(tmp_path: Path, real_key: str) -> None:
    provisioned(tmp_path, real_key, "judge")

    assert succeeds(tmp_path, f"key_is_a_role_key {keys(tmp_path)}/judge.pem")


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o660, 0o777])
def test_a_key_at_any_other_mode_is_not_a_role_key(
    tmp_path: Path, real_key: str, mode: int
) -> None:
    # The same mode `doctor` blocks on and `read_private_key` refuses to read past. A
    # wizard that handed over a block for a key the loop will refuse has told the human
    # they are finished when they are not.
    provisioned(tmp_path, real_key, "judge")
    (keys(tmp_path) / "judge.pem").chmod(mode)

    assert not succeeds(tmp_path, f"key_is_a_role_key {keys(tmp_path)}/judge.pem")


def test_the_wizard_and_the_loop_agree_about_a_key_carrying_a_special_bit(
    tmp_path: Path, real_key: str
) -> None:
    """`stat` does not agree with itself above the low nine bits.

    GNU `%a` reports setuid, setgid and sticky; BSD `%OLp` drops them. So a mode-2600
    key reads as `2600` on Linux and `600` on macOS, and an unmasked comparison passes
    the wizard on one and fails it on the other. `credentials.key_mode` masks to `0o777`
    and it is the same file it will be reading, so the wizard masks the same way.
    """
    provisioned(tmp_path, real_key, "judge")
    key = keys(tmp_path) / "judge.pem"
    key.chmod(0o2600)
    if not key.stat().st_mode & 0o7000:  # pragma: no cover — some filesystems drop it
        pytest.skip("this filesystem does not keep the setgid bit")

    assert key_mode(key) == KEY_MODE, "the loop reads this as a role key"
    assert succeeds(tmp_path, f"key_is_a_role_key {key}"), "so the wizard must too"


def test_a_file_openssl_will_not_read_as_a_key_is_not_a_role_key(tmp_path: Path) -> None:
    """A re-sync never re-downloads the key, so nothing else ever looks at it again.

    Without this the wizard signs with it anyway, `openssl` fails mid-pipeline, and
    `set -e` takes the whole three-role run down — where what the human needs is one
    line naming one file.
    """
    corrupt = tmp_path / "judge.pem"
    corrupt.write_text("-----BEGIN RSA PRIVATE KEY-----\ntruncated\n")
    corrupt.chmod(KEY_MODE)

    assert not succeeds(tmp_path, f"key_is_a_role_key {corrupt}")


def test_a_directory_at_0600_is_not_a_role_key(tmp_path: Path) -> None:
    # Permission bits alone would let this through, and everything downstream of it
    # reads the path as a file.
    (tmp_path / "judge.pem").mkdir(mode=KEY_MODE)

    assert not succeeds(tmp_path, f"key_is_a_role_key {tmp_path}/judge.pem")


def test_a_path_with_nothing_at_it_is_not_a_role_key(tmp_path: Path) -> None:
    assert not succeeds(tmp_path, f"key_is_a_role_key {tmp_path}/absent.pem")


def a_repo(root: Path, marker: str = "") -> Path:
    """A work tree at `root`, marked the way git marks one."""
    root.mkdir(parents=True, exist_ok=True)
    if marker:
        (root / ".git").write_text(marker)
    else:
        (root / ".git").mkdir()
    return root


def a_key_in(root: Path, key_pem: str) -> Path:
    key = root / "judge.pem"
    key.write_text(key_pem)
    key.chmod(KEY_MODE)
    return key


@pytest.mark.parametrize("marker", ["", "gitdir: /elsewhere/.git/worktrees/w\n"])
def test_the_wizard_and_the_loop_agree_that_a_key_inside_a_repo_is_not_a_role_key(
    tmp_path: Path, real_key: str, marker: str
) -> None:
    """§5 puts keys outside *every* repo, and `read_private_key` refuses one that is not.

    A key at 0600 inside a work tree is still one `git add .` from being published, and
    a wizard that certified it would hand over a block the loop then refuses to use. The
    marker is a directory in a clone and a *file* in a linked worktree or a submodule,
    so what counts is that something is there rather than what kind of thing.
    """
    key = a_key_in(a_repo(tmp_path / "clone", marker), real_key)

    assert repo_containing(key) is not None, "the loop refuses this key"
    assert not succeeds(tmp_path, f"key_is_a_role_key {key}"), "so the wizard must too"


# ── The authority a role is fixed to ─────────────────────────────────────────────


def granted(emitted: str) -> dict[str, str]:
    """`<permission>=<level>` lines back as a mapping."""
    return dict(line.split("=", 1) for line in emitted.splitlines() if line)


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_the_wizard_and_the_loop_agree_about_what_a_role_may_do(tmp_path: Path, role: str) -> None:
    # Two copies of §5's matrix, one in bash and one in Python, and no import between
    # them: the wizard tells a human what to click and `doctor` blocks on what GitHub
    # then reports. They drift silently, and the drift is a role certified as sound by
    # the wizard and refused by the loop it was provisioned for.
    assert granted(wizard(tmp_path, f"role_permissions {role}")) == ROLE_PERMISSIONS[role]


def test_the_form_labels_are_derived_from_the_matrix_rather_than_restated(
    tmp_path: Path,
) -> None:
    labelled = wizard(tmp_path, "permission_label pull_requests write; printf '\\n'")

    assert "Pull requests" in labelled
    assert "Read and write" in labelled


def test_an_installation_that_matches_the_matrix_has_no_problems(tmp_path: Path) -> None:
    granted_lines = "contents=read\npull_requests=write\nissues=read"

    assert wizard(tmp_path, f"permission_problems reviewer '{granted_lines}'") == ""


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_the_wizard_and_the_loop_agree_about_the_one_grant_nobody_asked_for(
    tmp_path: Path, role: str
) -> None:
    # `metadata` read is on every App whether or not the form asked, so it is the one
    # subtraction the exhaustive reading needs — without it every provisioned role is
    # rejected. Two copies again, one in bash and one in Python, and the drift would be
    # a wizard that refuses exactly the rosters it just provisioned correctly.
    permission, level = UNAVOIDABLE_PERMISSION
    granted_lines = "\n".join(
        f"{name}={granted}"
        for name, granted in {**ROLE_PERMISSIONS[role], permission: level}.items()
    )

    assert wizard(tmp_path, f"permission_problems {role} '{granted_lines}'") == ""


def test_an_installation_carrying_authority_the_matrix_does_not_name_is_a_problem(
    tmp_path: Path,
) -> None:
    # The row is everything the role may hold, so a permission it does not name is one
    # expected at no access — the wizard says so on the form and must say so on the
    # verdict, or it certifies a role wider than the one it told a human to provision.
    granted_lines = "contents=read\npull_requests=write\nissues=read\nworkflows=write"

    assert "workflows is write rather than no access" in wizard(
        tmp_path, f"permission_problems reviewer '{granted_lines}'"
    )


@pytest.mark.parametrize(
    ("role", "granted_lines", "named"),
    [
        # Authority it must not hold — the matrix is two prohibitions as much as a grant.
        ("reviewer", "contents=write\npull_requests=write\nissues=read", "contents is write"),
        ("implementer", "contents=write\npull_requests=write\nissues=write", "issues is write"),
        # Authority it needs and was not given.
        ("judge", "contents=write\npull_requests=write\nissues=read", "issues is read"),
        ("implementer", "pull_requests=write\nissues=read", "contents is no access"),
    ],
)
def test_an_installation_that_does_not_match_the_matrix_names_what_is_wrong(
    tmp_path: Path, role: str, granted_lines: str, named: str
) -> None:
    assert named in wizard(tmp_path, f"permission_problems {role} '{granted_lines}'")


# ── Which repositories the installation reaches ──────────────────────────────────

FAKE_GH = """#!/bin/sh
# Stands in for `gh api`: the endpoint answers 30 repositories at a time and hands over
# the rest only when the caller asks for every page. Refuses without a token, so a
# listing that comes back at all also proves the role's token reached the child.
[ -n "$GH_TOKEN" ] || exit 1
last=30
for argument in "$@"; do [ "$argument" = "--paginate" ] && last=31; done
number=1
while [ $number -le $last ]; do echo "mcnewcp/repo$number"; number=$((number + 1)); done
"""


def test_the_repository_listing_asks_for_every_page(tmp_path: Path) -> None:
    """`/installation/repositories` answers 30 at a time.

    Without `--paginate` a target repo that sorts onto the second page reads as one the
    installation cannot reach, so the wizard withholds a config block it has earned —
    and an installation scoped far wider than the target set passes as though narrow.
    """
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "gh").write_text(FAKE_GH)
    (binaries / "gh").chmod(0o755)

    listed = wizard(
        tmp_path, "installation_repos ghs_token", path=f"{binaries}:/usr/bin:/bin"
    ).splitlines()

    assert "mcnewcp/repo1" in listed, "the token reached `gh`"
    assert "mcnewcp/repo31" in listed, "and the page after the first was asked for"


def test_a_listing_that_failed_is_not_an_installation_that_reaches_nothing(
    tmp_path: Path,
) -> None:
    # The verify stage reads an empty answer as "the installation does not reach your
    # target repos" and tells the human to re-scope it. A failed request must not put
    # that sentence on screen, so the failure travels rather than the emptiness.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "gh").write_text("#!/bin/sh\nexit 1\n")
    (binaries / "gh").chmod(0o755)

    failed = run_wizard(tmp_path, "installation_repos ghs_token", path=f"{binaries}:/usr/bin:/bin")

    assert failed.returncode != 0


# ── The config blocks, and what has to be true before one is offered ─────────────


def test_the_three_blocks_it_ends_with_are_a_config_the_parser_accepts(
    tmp_path: Path, real_key: str
) -> None:
    provisioned(tmp_path, real_key, *RECORDED)
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


def test_the_key_path_it_writes_is_kept_as_a_tilde(tmp_path: Path, real_key: str) -> None:
    # Config stores `key_path` exactly as written so that parsing never depends on
    # $HOME. A wizard that pasted an expanded path would make one machine's config
    # unusable on another.
    provisioned(tmp_path, real_key, "judge")

    assert 'key_path        = "~/.config/my-team/keys/judge.pem"' in wizard(
        tmp_path, "config_block judge"
    )


def only_a_comment(emitted: str, role: str) -> bool:
    """Nothing that would parse as config — a half-block is worse than no block."""
    return emitted.startswith(f"# [roles.{role}]") and all(
        line.startswith("#") for line in emitted.splitlines() if line
    )


def test_a_role_that_was_never_provisioned_emits_a_comment_rather_than_half_a_block(
    tmp_path: Path, real_key: str
) -> None:
    provisioned(tmp_path, real_key)

    assert only_a_comment(wizard(tmp_path, "config_block reviewer || true"), "reviewer")


@pytest.mark.parametrize("id_name", ["APP_ID", "BOT_USER_ID", "INSTALLATION_ID"])
def test_a_role_missing_any_one_id_is_not_offered_as_complete(
    tmp_path: Path, id_name: str, real_key: str
) -> None:
    # The bot user id in particular is not derivable from `app_id`, so a block without
    # it would parse and then match no review at all.
    provisioned(tmp_path, real_key, "judge")
    recorded = tmp_path / ".config" / "my-team" / "judge.env"
    recorded.write_text(
        "".join(
            line for line in recorded.read_text().splitlines(True) if not line.startswith(id_name)
        )
    )
    emitted = wizard(tmp_path, "config_block judge || true")

    assert only_a_comment(emitted, "judge")
    assert id_name.lower() in emitted, "the comment says which id is missing"


def test_a_role_whose_verification_never_finished_is_not_offered_as_complete(
    tmp_path: Path, real_key: str
) -> None:
    """Every early return in the verify stage leaves the recorded ids exactly where they
    were, so ids alone say only that *some* run once read them. The marker is what says
    a run proved the whole chain, and a run that returns early drops it."""
    provisioned(tmp_path, real_key, "judge")
    recorded = tmp_path / ".config" / "my-team" / "judge.env"
    recorded.write_text(recorded.read_text().replace("VERIFIED=judge\n", ""))

    assert only_a_comment(wizard(tmp_path, "config_block judge || true"), "judge")


def test_a_role_whose_key_slipped_off_0600_is_not_offered_as_complete(
    tmp_path: Path, real_key: str
) -> None:
    provisioned(tmp_path, real_key, "judge")
    (keys(tmp_path) / "judge.pem").chmod(0o644)
    emitted = wizard(tmp_path, "config_block judge || true")

    assert only_a_comment(emitted, "judge")
    assert "600" in emitted


def test_a_role_whose_key_sits_inside_a_repo_is_not_offered_and_names_the_repo(
    tmp_path: Path, real_key: str
) -> None:
    """The key is mode 600 and openssl reads it — what is wrong is *where* it is.

    So the comment has to name the enclosing repository rather than report a mode that
    is already correct, which would send the human to `chmod` a key that needs moving.
    """
    provisioned(tmp_path, real_key, "judge")
    checkout = a_repo(tmp_path / "clone")
    a_key_in(checkout, real_key)
    emitted = wizard(tmp_path, f"KEY_DIR={checkout}\nconfig_block judge || true")

    assert only_a_comment(emitted, "judge")
    assert f"inside the repository at {checkout}" in emitted, "the unsafe repository is named"
    assert "600" not in emitted, "and not reported as a mode this key already carries"


def test_a_role_whose_key_is_not_on_disk_is_not_offered_as_complete(
    tmp_path: Path, real_key: str
) -> None:
    # A re-sync skips the key stage entirely, so the ids can be fresh while the key the
    # config points at is missing, stale or somebody else's.
    provisioned(tmp_path, real_key, "judge")
    (keys(tmp_path) / "judge.pem").unlink()

    assert only_a_comment(wizard(tmp_path, "config_block judge || true"), "judge")


# ── The record the blocks are read out of ────────────────────────────────────────


def test_clearing_one_recorded_value_leaves_every_other_one_standing(
    tmp_path: Path, real_key: str
) -> None:
    provisioned(tmp_path, real_key, "judge")
    env_file = tmp_path / ".config" / "my-team" / "judge.env"
    wizard(tmp_path, f"ENV_FILE={env_file}\nclear_env VERIFIED")

    assert "VERIFIED" not in env_file.read_text()
    assert "APP_ID=4652145" in env_file.read_text()


def test_clearing_a_value_from_a_file_that_is_not_there_is_not_an_error(tmp_path: Path) -> None:
    assert succeeds(tmp_path, f"ENV_FILE={tmp_path}/absent.env\nclear_env VERIFIED")


def test_a_verify_run_that_returns_early_leaves_no_verdict_standing(
    tmp_path: Path, real_key: str
) -> None:
    """The verify stage returns early in five places, and none of them unwinds a write.

    So the marker has to be dropped before the first of those can fire — otherwise a run
    that got halfway leaves the previous run's verdict standing over ids nothing
    re-proved. Driven here through the first of those returns, the one that needs no
    network: a role a previous run verified, whose key has since slipped off 0600.
    """
    provisioned(tmp_path, real_key, "judge")
    key = keys(tmp_path) / "judge.pem"
    key.chmod(0o644)
    recorded = tmp_path / ".config" / "my-team" / "judge.env"

    wizard(tmp_path, f"ENV_FILE={recorded}\nPEM_PATH={key}\nverify_role judge")

    assert "VERIFIED" not in recorded.read_text(), "the earlier verdict is gone"
    assert "APP_ID=4652145" in recorded.read_text(), "and the ids it left are untouched"
    assert only_a_comment(wizard(tmp_path, "config_block judge || true"), "judge")


def test_a_verify_run_will_not_certify_a_key_that_sits_inside_a_repo(
    tmp_path: Path, real_key: str
) -> None:
    """Verification is what a config block is gated on, so this is where it has to stop.

    The key signs perfectly well — refusing it is about where it sits, and a stage that
    signed with it first would certify an identity whose key §5 forbids. `mint_jwt` is
    stubbed to say so out loud; `app_api` to keep the stage off the network.
    """
    provisioned(tmp_path, real_key, "judge")
    checkout = a_repo(tmp_path / "clone")
    key = a_key_in(checkout, real_key)
    recorded = tmp_path / ".config" / "my-team" / "judge.env"

    emitted = wizard(
        tmp_path,
        "mint_jwt() { echo REACHED-SIGNING; }\napp_api() { :; }\n"
        f"ENV_FILE={recorded}\nPEM_PATH={key}\nverify_role judge",
    )

    assert f"inside the repository at {checkout}" in emitted, "the unsafe repository is named"
    assert "REACHED-SIGNING" not in emitted, "and it was refused before being signed with"
    assert "VERIFIED" not in recorded.read_text(), "so no verdict stands"
    assert "APP_ID=4652145" in recorded.read_text(), "and the ids it left are untouched"


def test_the_key_the_wizard_stores_is_one_the_loop_will_read(tmp_path: Path, real_key: str) -> None:
    """Two places state the mode — the key stage writes it, `doctor` reads it — and a
    re-sync never re-downloads the key, so the stage is the only place it is written.
    So the download is walked through that stage and what it leaves behind is handed to
    both readers. `open_url` is the one thing stubbed out: it drives a browser.
    """
    downloaded = tmp_path / "Downloads" / "judge-my-team.2026-08-24.private-key.pem"
    downloaded.parent.mkdir()
    downloaded.write_text(real_key)
    downloaded.chmod(0o644)
    stored = keys(tmp_path) / "judge.pem"
    stored.parent.mkdir(parents=True)

    wizard(
        tmp_path,
        "open_url() { :; }\n"
        f'SRC_PEM=""\nAPP_SLUG=judge-my-team\nPEM_PATH={stored}\nstore_key judge',
        # Enter at "Downloaded?", y at "Use that one?", Enter at the closing pause.
        stdin="\ny\n\n",
    )

    assert key_mode(stored) == KEY_MODE, "the loop reads this as a role key"
    assert succeeds(tmp_path, f"key_is_a_role_key {stored}"), "and so does the wizard"
    assert not downloaded.exists(), "the download was moved rather than copied"
