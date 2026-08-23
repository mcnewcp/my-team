"""What the wheel ships.

The skill payload is package data rather than code, so nothing imports it and nothing
would notice it going missing until `my-team sync` ran in a target repo and installed
an empty payload. This builds the real wheel and looks inside.

The expectation is derived from the source tree rather than written down, so a package
or a payload member added later is covered the moment it exists. A written list would
have to be remembered, and forgetting is the thing being guarded against.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from hatchling.build import build_wheel

REPO_ROOT = Path(__file__).resolve().parents[1]

# Repo-relative, the way pyproject.toml and git name things.
PACKAGE_SOURCE_ROOT = "src"
PACKAGE_DIR = f"{PACKAGE_SOURCE_ROOT}/my_team"
PAYLOAD_DIR = f"{PACKAGE_DIR}/payload/skills"

# Two generated top-level directories are defined by the wheel format. Neither came from
# the source tree, so counting them as members would make the two sides disagree by
# exactly the files that are supposed to differ.
GENERATED_WHEEL_DIRS = (".dist-info", ".data")


def wheel_name(source_path: str) -> str:
    """A repo-relative source path, renamed the way the wheel names it.

    src layout: the wheel names a member relative to the directory holding the package,
    so the src root falls away and nothing else does. Wheel-relative and repo-relative
    names look alike, which is why every crossing goes through here.
    """
    return source_path.removeprefix(f"{PACKAGE_SOURCE_ROOT}/")


PAYLOAD_PREFIX = f"{wheel_name(PAYLOAD_DIR)}/"

# The member a partial build is told to drop, so the check is watched catching package
# data and a Python module rather than only the payload it was written for.
EXCLUDED_MODULE = f"{PACKAGE_DIR}/config_file.py"

# A throwaway project that builds this same source tree with members excluded. It is
# written out rather than patched from the real pyproject.toml because a config that
# already carried an `exclude` key would take the patch as a duplicate and fail on TOML
# rather than on the thing under test.
PARTIAL_BUILD_PYPROJECT = f"""\
[project]
name = "my-team"
version = "0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{PACKAGE_DIR}"]
exclude = ["{EXCLUDED_MODULE}", "{PAYLOAD_DIR}/**"]
"""


def git(*args: str, cwd: Path) -> str:
    """Run git quietly and hand back its stdout, so none of it reaches the test report."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def source_package_members(repo_root: Path) -> set[str]:
    """Every file under the source package, named the way the wheel would name it.

    Git is the authority on what counts as source, because it already knows that
    `__pycache__` and `*.pyc` are leavings and it keeps no list this test has to
    maintain. Untracked-but-not-ignored files count: the wheel ships a payload member
    the moment it is written, so one still waiting to be staged belongs on both sides
    rather than reading as a discrepancy.

    `core.excludesFile` is emptied because hatchling reads only the ignore rules in the
    tree. Left alone, whatever a developer happens to ignore globally would decide what
    this repo calls source, and code that is clean in CI would fail on their machine.
    """
    listed = git(
        "-c",
        "core.excludesFile=",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        PACKAGE_DIR,
        cwd=repo_root,
    )
    return {wheel_name(path) for path in listed.split("\0") if path}


def wheel_package_members(wheel: zipfile.ZipFile) -> set[str]:
    """Everything in the wheel that came from the source tree."""
    return {
        name
        for name in wheel.namelist()
        if not name.partition("/")[0].endswith(GENERATED_WHEEL_DIRS)
    }


def build_wheel_at(project_root: Path, output_dir: Path) -> Path:
    """Build a project through the same PEP 517 hook a release goes through."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.chdir(project_root):
        return output_dir / build_wheel(str(output_dir))


@pytest.fixture(scope="module")
def wheel_contents(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    """The wheel this checkout builds."""
    with zipfile.ZipFile(build_wheel_at(REPO_ROOT, tmp_path_factory.mktemp("wheel"))) as wheel:
        yield wheel


def test_the_wheel_ships_every_source_package_member(wheel_contents: zipfile.ZipFile) -> None:
    assert wheel_package_members(wheel_contents) == source_package_members(REPO_ROOT)


def test_the_wheel_ships_the_payload_directory(wheel_contents: zipfile.ZipFile) -> None:
    """The check above holds just as well over a payload that reaches the wheel as nothing.

    It says the two sides agree, not that either is populated, so this is the one thing
    it cannot see. Today the directory is held open by a `.gitkeep` and that is all this
    asserts; it grows teeth on its own as skills land.
    """
    shipped = wheel_package_members(wheel_contents)

    assert [name for name in shipped if name.startswith(PAYLOAD_PREFIX)]


def test_a_partial_wheel_stops_matching_the_source_package(tmp_path: Path) -> None:
    """The check earns its runtime only if a partial wheel actually fails it.

    This source tree is rebuilt under a config carrying an `exclude` line — the shape a
    future partial exclusion would most plausibly arrive in — naming a Python module and
    the payload, because the check is claimed over both.
    """
    project = tmp_path / "project"
    project.mkdir()
    shutil.copytree(REPO_ROOT / PACKAGE_SOURCE_ROOT, project / PACKAGE_SOURCE_ROOT)
    shutil.copy(REPO_ROOT / ".gitignore", project / ".gitignore")
    (project / "pyproject.toml").write_text(PARTIAL_BUILD_PYPROJECT)
    # source_package_members reads a tree through git, so the copy has to be one.
    git("init", "--quiet", cwd=project)
    git("add", "--all", cwd=project)

    with zipfile.ZipFile(build_wheel_at(project, tmp_path / "wheel")) as wheel:
        shipped = wheel_package_members(wheel)

    members = source_package_members(project)
    assert shipped != members
    missing = members - shipped
    assert wheel_name(EXCLUDED_MODULE) in missing
    assert [name for name in missing if name.startswith(PAYLOAD_PREFIX)]


def test_the_wheel_installs_the_console_script(wheel_contents: zipfile.ZipFile) -> None:
    entry_points = next(
        name for name in wheel_contents.namelist() if name.endswith(".dist-info/entry_points.txt")
    )

    assert "my-team = my_team.cli:main" in wheel_contents.read(entry_points).decode()
