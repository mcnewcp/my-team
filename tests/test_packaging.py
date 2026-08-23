"""What the wheel ships.

The skill payload is package data rather than code, so nothing imports it and nothing
would notice it going missing until `my-team sync` ran in a target repo and installed
an empty payload. This builds the real wheel and looks inside.
"""

from __future__ import annotations

import contextlib
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from hatchling.build import build_wheel

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wheel_contents(tmp_path_factory: pytest.TempPathFactory) -> Iterator[zipfile.ZipFile]:
    """The wheel this checkout builds, through the same hook a release goes through."""
    out = tmp_path_factory.mktemp("wheel")
    with contextlib.chdir(REPO_ROOT):
        built = build_wheel(str(out))
    with zipfile.ZipFile(out / built) as wheel:
        yield wheel


def test_the_wheel_ships_the_package(wheel_contents: zipfile.ZipFile) -> None:
    names = set(wheel_contents.namelist())

    assert "my_team/__init__.py" in names
    assert "my_team/cli.py" in names
    assert "my_team/core/config.py" in names


def test_the_wheel_ships_the_payload_directory(wheel_contents: zipfile.ZipFile) -> None:
    names = set(wheel_contents.namelist())

    assert "my_team/payload/__init__.py" in names
    assert [name for name in names if name.startswith("my_team/payload/skills/")]


def test_the_wheel_installs_the_console_script(wheel_contents: zipfile.ZipFile) -> None:
    entry_points = next(
        name for name in wheel_contents.namelist() if name.endswith(".dist-info/entry_points.txt")
    )

    assert "my-team = my_team.cli:main" in wheel_contents.read(entry_points).decode()
