"""Shared test fixtures.

End-to-end tests need a Ren'Py SDK. It is taken from the RENPY_SDK environment variable, or from
the newest one unpacked under .cache/sdk/. Without one, those tests are skipped.
"""

import hashlib
import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "games"


def find_sdk():
    if os.environ.get("RENPY_SDK"):
        return Path(os.environ["RENPY_SDK"])

    def version(path):
        return [int(i) for i in path.name.split("-")[1].split(".")]

    found = sorted((ROOT / ".cache" / "sdk").glob("renpy-*-sdk"), key=version)
    return found[-1] if found else None


@pytest.fixture(scope="session")
def sdk():
    path = find_sdk()
    if path is None or not (path / "renpy").is_dir():
        pytest.skip("no Ren'Py SDK available: set RENPY_SDK")
    return path


@pytest.fixture
def game_copy(tmp_path):
    """Returns a function that copies a fixture game into a temporary folder and returns its path."""

    copies = []

    def copy(name):
        copies.append(name)
        target = tmp_path / ("game-%d" % len(copies)) / name
        shutil.copytree(FIXTURES / name, target)
        return target

    return copy


def folder_digest(path):
    """A fingerprint of every file's name and content under a folder."""
    digest = hashlib.sha1()
    for file in sorted(Path(path).rglob("*")):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()
