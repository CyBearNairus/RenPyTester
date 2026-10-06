import os
import subprocess
from pathlib import Path

import pytest

from renpytester.launcher import MAX_DEFAULT_JOBS, SILENT_EDITOR, build_environment, default_jobs


@pytest.fixture
def env(tmp_path):
    return build_environment(tmp_path / "events.jsonl", {"seed": 1}, tmp_path / "logs")


@pytest.mark.req("GAME-007", "ARCH-006")
def test_engine_is_started_with_no_window_and_no_sound(env, tmp_path):
    assert env["SDL_VIDEODRIVER"] == "dummy"
    assert env["SDL_AUDIODRIVER"] == "dummy"
    assert env["RENPY_RENDERER"] == "sw"
    shown = build_environment(tmp_path / "events.jsonl", {}, tmp_path / "logs", show_window=True)
    assert shown.get("SDL_VIDEODRIVER") != "dummy"


@pytest.mark.req("SAFE-013", "SAFE-014")
def test_engine_logs_and_backups_stay_out_of_the_game_and_the_profile(env, tmp_path):
    assert env["RENPY_LOG_BASE"] == str(tmp_path / "logs")
    assert env["RENPY_DISABLE_BACKUPS"]


@pytest.mark.req("GAME-010")
def test_engine_is_given_an_editor_that_opens_nothing(env, monkeypatch):
    path = Path(env["RENPY_EDIT_PY"])
    assert path == SILENT_EDITOR
    assert path.is_file()

    def forbidden(*args, **kwargs):
        raise AssertionError("the editor tried to open something")

    monkeypatch.setattr(subprocess, "call", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", forbidden)

    # Load the file the way the engine does, then use it the way the engine does.
    scope = {"__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope, scope)
    editor = scope["Editor"]()
    editor.begin(new_window=True)
    editor.open("traceback.txt", 1)
    editor.end()
    editor.open_project("somewhere")


@pytest.mark.req("NFR-001")
def test_engine_orders_sets_the_same_way_on_every_run(env):
    assert env["PYTHONHASHSEED"] == "0"


@pytest.mark.req("RUN-014")
def test_default_number_of_game_processes_follows_cores_and_free_memory():
    plenty = 64 * 1024 ** 3
    assert default_jobs(cpus=1, memory=plenty) == 1
    assert default_jobs(cpus=4, memory=plenty) == 3
    assert default_jobs(cpus=64, memory=plenty) == MAX_DEFAULT_JOBS
    # Little free memory: fewer processes, but always at least one.
    assert default_jobs(cpus=8, memory=2 * 1024 ** 3) == 2
    assert default_jobs(cpus=8, memory=1024) == 1
    assert default_jobs() >= 1
