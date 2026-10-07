"""The single-file executable (spec 4.13). Skipped unless RENPYTESTER_EXE names one.

The rest of the end-to-end tests run against the executable too when that variable is set (see
conftest.py here); these are the tests that are about the executable itself.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from renpytester import __version__, cli
from renpytester.cli import main as from_source  # Taken now: the tests here replace cli.main.
from tests.conftest import folder_digest
from tests.e2e.conftest import executable, run_executable

pytestmark = pytest.mark.e2e


@pytest.fixture
def exe():
    if not executable():
        pytest.skip("no executable to test: set RENPYTESTER_EXE")
    return Path(executable())


@pytest.mark.req("DIST-002", "CLI-005")
def test_executable_is_this_version_and_needs_no_python(exe, tmp_path):
    # Nothing of the Python that runs the tests is left for it to find.
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("PYTHON")}
    env["PATH"] = os.environ.get("SystemRoot", "/usr") + os.sep + ("System32" if sys.platform == "win32" else "bin")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    done = subprocess.run(
        [str(exe), "--version"], capture_output=True, stdin=subprocess.DEVNULL, env=env, cwd=str(tmp_path),
        creationflags=flags)
    assert done.returncode == 0
    assert done.stdout.decode().strip() == "renpytester " + __version__


@pytest.mark.req("DIST-002", "GUI-013", "I18N-001")
def test_executable_carries_the_harness_the_window_and_every_data_file(exe):
    readers = pytest.importorskip("PyInstaller.archive.readers")
    archive = readers.CArchiveReader(str(exe))
    held = {name.replace("\\", "/") for name in archive.toc}

    package = Path(cli.__file__).resolve().parent
    data = [p for p in package.rglob("*") if p.is_file() and p.suffix not in (".py", ".pyc")]
    data.append(package / "harness" / "silent_editor.py")
    assert len(data) > 8
    for file in data:
        assert "renpytester/" + file.relative_to(package).as_posix() in held, file

    # The window: Tk's own library, the files it reads as it starts, and Python's part of it.
    # Where these are put differs from one system to another; their names do not.
    assert any(name.split("/")[-1].startswith("_tkinter") for name in held)
    assert any(name.split("/")[-1] == "init.tcl" for name in held)
    modules = archive.open_embedded_archive("PYZ.pyz").toc
    for module in ("tkinter", "tkinter.ttk", "renpytester.gui", "renpytester.report.html_report"):
        assert module in modules, module


@pytest.mark.req("DIST-006", "DIST-002", "NFR-001")
@pytest.mark.parametrize("name", ["labels", "tl_untranslated", "missing_audio"])
def test_executable_reports_what_the_source_does(exe, sdk, game_copy, tmp_path, capsys, name):
    reports = {}
    for kind, main in (("source", from_source), ("executable", run_executable)):
        game = game_copy(name)
        before = folder_digest(game)
        output = tmp_path / kind
        code = main([str(game), "--sdk", str(sdk), "--output", str(output), "--lang", "en", "--jobs", "2"])
        text = capsys.readouterr().out
        assert folder_digest(game) == before
        report = json.loads(next(output.glob("report-*.json")).read_text(encoding="utf-8"))
        # The same but for what tells one run from another: when it was, and where the game's copy was.
        for key in ("started", "finished", "name"):
            del report[key]
        del report["game"]["path"]
        where = str(game.parent)
        reports[kind] = (code, report, text.replace(where, "").split("Full report:")[0])

    assert reports["executable"][0] == reports["source"][0]
    assert reports["executable"][1] == reports["source"][1]
    assert reports["executable"][2] == reports["source"][2]
