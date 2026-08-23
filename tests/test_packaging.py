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
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from hatchling.build import build_wheel

REPO_ROOT = Path(__file__).resolve().parents[1]

# Repo-relative, the way pyproject.toml and git name things.
PACKAGE_SOURCE_ROOT = "src"
PACKAGE_DIR = f"{PACKAGE_SOURCE_ROOT}/my_team"
PAYLOAD_DIR = f"{PACKAGE_DIR}/payload/skills"

# The one ignore file a hatchling build reads, and so the only one this test may read.
BUILD_IGNORE_FILE = ".gitignore"

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


def git(*args: str, cwd: Path) -> str:
    """Run git quietly and hand back its stdout, so none of it reaches the test report."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def source_package_members(repo_root: Path) -> set[str]:
    """Every file under the source package, named the way the wheel would name it.

    Git is the authority on what counts as source, because it keeps no list this test
    has to maintain. Untracked-but-not-ignored files count: the wheel ships a payload
    member the moment it is written, so one still waiting to be staged belongs on both
    sides rather than reading as a discrepancy.

    Which rules do the ignoring has to be settled deliberately, because git and
    hatchling disagree. Hatchling reads a single file, the `.gitignore` beside
    pyproject.toml. Git's standard exclusions read three more: a `.gitignore` in any
    subdirectory, the repository's own `.git/info/exclude`, and the developer's global
    excludes file. A rule in any of those three would drop a file from this side while
    the build went on shipping it, so the check would answer to whatever the person
    running it happens to ignore. Git is handed the build's one file and nothing else.
    """
    listed = git(
        "ls-files",
        "--cached",
        "--others",
        f"--exclude-from={BUILD_IGNORE_FILE}",
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


def throwaway_pyproject(exclude: Sequence[str] = ()) -> str:
    """A config that builds this same source tree, dropping the members named.

    It is written out rather than patched from the real pyproject.toml because a config
    that already carried an `exclude` key would take the patch as a duplicate and fail
    on TOML rather than on the thing under test.
    """
    quoted = ", ".join(f'"{path}"' for path in exclude)
    exclude_line = f"exclude = [{quoted}]\n" if exclude else ""
    return f"""\
[project]
name = "my-team"
version = "0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{PACKAGE_DIR}"]
{exclude_line}"""


def throwaway_project(tmp_path: Path, pyproject: str) -> Path:
    """This source tree, copied out as a project of its own under a git of its own.

    source_package_members reads a tree through git, so the copy has to be one — and the
    copy, not this checkout, is where a test may leave ignore rules lying around.
    """
    project = tmp_path / "project"
    project.mkdir()
    shutil.copytree(REPO_ROOT / PACKAGE_SOURCE_ROOT, project / PACKAGE_SOURCE_ROOT)
    shutil.copy(REPO_ROOT / BUILD_IGNORE_FILE, project / BUILD_IGNORE_FILE)
    (project / "pyproject.toml").write_text(pyproject)
    git("init", "--quiet", cwd=project)
    git("add", "--all", cwd=project)
    return project


def hide_an_untracked_module(project: Path, ignore_file: Path, module: str) -> str:
    """Add an unstaged package module, hide it in `ignore_file`, and name it wheel-side."""
    (project / PACKAGE_DIR / module).write_text("")
    ignore_file.parent.mkdir(parents=True, exist_ok=True)
    ignore_file.write_text(f"{module}\n")
    return wheel_name(f"{PACKAGE_DIR}/{module}")


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
    project = throwaway_project(
        tmp_path, throwaway_pyproject([EXCLUDED_MODULE, f"{PAYLOAD_DIR}/**"])
    )

    with zipfile.ZipFile(build_wheel_at(project, tmp_path / "wheel")) as wheel:
        shipped = wheel_package_members(wheel)

    members = source_package_members(project)
    assert shipped != members
    missing = members - shipped
    assert wheel_name(EXCLUDED_MODULE) in missing
    assert [name for name in missing if name.startswith(PAYLOAD_PREFIX)]


def test_an_ignore_rule_the_build_never_reads_leaves_the_check_alone(tmp_path: Path) -> None:
    """And it is worth nothing if a green run only means the two sides agree on this machine.

    Every ignore rule git reads over and above the build's one `.gitignore` is set here,
    each hiding a package module of its own, and the equality has to come out the same:
    the wheel ships all three, so the expectation has to name all three. Left to git's
    standard exclusions it would shrink instead, and a checkout would pass or fail this
    suite by what its own developer happens to ignore.
    """
    project = throwaway_project(tmp_path, throwaway_pyproject())
    global_excludes = tmp_path / "global-excludes"
    git("config", "core.excludesFile", str(global_excludes), cwd=project)
    hidden = {
        hide_an_untracked_module(
            project, project / PACKAGE_DIR / ".gitignore", "hidden_by_a_nested_gitignore.py"
        ),
        hide_an_untracked_module(
            project, project / ".git" / "info" / "exclude", "hidden_by_the_repo_exclude.py"
        ),
        hide_an_untracked_module(project, global_excludes, "hidden_by_the_global_excludes.py"),
    }

    with zipfile.ZipFile(build_wheel_at(project, tmp_path / "wheel")) as wheel:
        shipped = wheel_package_members(wheel)

    assert hidden <= shipped
    assert shipped == source_package_members(project)


def test_the_wheel_installs_the_console_script(wheel_contents: zipfile.ZipFile) -> None:
    entry_points = next(
        name for name in wheel_contents.namelist() if name.endswith(".dist-info/entry_points.txt")
    )

    assert "my-team = my_team.cli:main" in wheel_contents.read(entry_points).decode()
