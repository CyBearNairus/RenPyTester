"""The engine must not open error files in a text editor during a run (spec GAME-010)."""

import subprocess

import pytest

from renpytester import discovery
from renpytester.launcher import build_environment

pytestmark = pytest.mark.e2e

RECORDING_EDITOR = '''
class Editor(object):
    has_projects = False

    def begin(self, new_window=False, **kwargs):
        pass

    def end(self, **kwargs):
        pass

    def open(self, filename, line=None, **kwargs):
        with open(%r, "a") as record:
            record.write(filename + "\\n")

    def open_project(self, directory):
        pass
'''


@pytest.mark.req("GAME-010")
def test_engine_sends_error_files_to_the_editor_we_supply(sdk, game_copy, tmp_path):
    """A failing game run normally makes the engine open errors.txt in the system editor.

    This runs that exact situation with an editor that only records what it was asked to open. The
    record proves the engine goes through the editor we name in RENPY_EDIT_PY, which in real runs is
    the one that opens nothing.
    """
    game = discovery.discover(game_copy("parse_error"), sdk)
    record = tmp_path / "opened.txt"
    editor = tmp_path / "recording_editor.py"
    editor.write_text(RECORDING_EDITOR % str(record), encoding="utf-8")
    (tmp_path / "logs").mkdir()

    env = build_environment(tmp_path / "events.jsonl", {}, tmp_path / "logs")
    assert env["RENPY_EDIT_PY"] != str(editor)
    env["RENPY_EDIT_PY"] = str(editor)

    cmd = [str(game.python), str(game.main_script), str(game.basedir), "run", "--savedir", str(tmp_path / "saves")]
    subprocess.run(cmd, env=env, capture_output=True, timeout=60)

    assert record.is_file(), "the engine did not go through RENPY_EDIT_PY when the game failed"
    assert "errors.txt" in record.read_text()
