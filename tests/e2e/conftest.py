"""Runs the end-to-end tests against the single-file executable when one is named (spec DIST-006).

With the RENPYTESTER_EXE environment variable set to an executable built by tools/build_exe.py,
every test that goes through the command line starts that executable instead of the source. Tests
marked `source` reach into the program itself, which cannot be done to an executable, and are skipped.
"""

import os
import subprocess
import sys

import pytest

from renpytester import cli


# Made whole now: a test may move to another folder before it runs anything.
EXECUTABLE = os.path.abspath(os.environ["RENPYTESTER_EXE"]) if os.environ.get("RENPYTESTER_EXE") else None


def executable():
    return EXECUTABLE


def run_executable(argv):
    """What cli.main does, done by the executable: prints what it printed and returns its exit code."""
    # No console window of its own for a process started by a test.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    done = subprocess.run(
        [executable(), *argv], capture_output=True, stdin=subprocess.DEVNULL, creationflags=flags)
    sys.stdout.write(done.stdout.decode("utf-8", "replace").replace("\r\n", "\n"))
    sys.stderr.write(done.stderr.decode("utf-8", "replace").replace("\r\n", "\n"))
    return done.returncode


@pytest.fixture(autouse=True)
def through_the_executable(request, monkeypatch):
    if not executable():
        return
    if request.node.get_closest_marker("source"):
        pytest.skip("reaches into the program itself; not possible with RENPYTESTER_EXE")
    monkeypatch.setattr(cli, "main", run_executable)
