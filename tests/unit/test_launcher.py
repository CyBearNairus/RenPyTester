import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from renpytester.launcher import (
    MAX_DEFAULT_JOBS, SILENT_EDITOR, STARTUP_SECONDS, Startup, build_environment, default_jobs, run_command,
    run_engine)


@pytest.fixture
def env(tmp_path):
    return build_environment(tmp_path / "events.jsonl", {"seed": 1}, tmp_path / "logs")


@pytest.mark.req("GAME-007", "ARCH-006", "NFR-007")
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


@pytest.mark.req("NFR-001", "RUN-026")
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


# Stands in for the engine: says when it started, takes a while to "load the game", says so the way
# the harness does, and then works for a while longer.
STAND_IN = """
import json, os, sys, time
record = os.path.join(sys.argv[1], "record-%d.json" % os.getpid())
times = {"start": time.time()}
time.sleep(0.4)
if "--never-loads" not in sys.argv:
    times["loaded"] = time.time()
    open(os.environ["RENPYTESTER_LOADED"], "w").close()
    time.sleep(0.6)
times["end"] = time.time()
with open(record, "w") as out:
    json.dump(times, out)
"""


@pytest.fixture
def stand_in(tmp_path):
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8")
    (tmp_path / "game").mkdir()
    return SimpleNamespace(python=sys.executable, main_script=script, basedir=tmp_path / "game")


def records(game):
    import json

    return sorted(
        (json.loads(path.read_text()) for path in game.basedir.glob("record-*.json")), key=lambda r: r["start"])


@pytest.mark.req("RUN-027")
def test_game_processes_start_one_at_a_time_and_then_run_together(stand_in, tmp_path):
    def play(number):
        run_engine(stand_in, "run", tmp_path / ("work-%d" % number), tmp_path / ("logs-%d" % number), {}, 30)

    def lint():
        run_command(stand_in, "lint", [], tmp_path / "work-lint", tmp_path / "logs-lint", 30)

    (tmp_path / "work-lint").mkdir()
    (tmp_path / "logs-lint").mkdir()
    threads = [threading.Thread(target=play, args=(number,)) for number in range(2)] + [threading.Thread(target=lint)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    first, second, third = records(stand_in)
    # None starts before the one before it has loaded the game...
    assert second["start"] >= first["loaded"] and third["start"] >= second["loaded"]
    # ...and none waits for the one before it to finish.
    assert second["start"] < first["end"] and third["start"] < second["end"]


@pytest.mark.req("RUN-027")
def test_process_that_dies_before_loading_the_game_lets_the_next_one_start(stand_in, tmp_path):
    code, _output = run_command(stand_in, "lint", ["--never-loads"], tmp_path, tmp_path, 30)
    assert code == 0
    started = time.monotonic()
    assert Startup(stand_in, tmp_path, "run").enter() is True
    assert time.monotonic() - started < 1


@pytest.mark.req("RUN-008")
def test_game_that_is_still_starting_is_not_taken_for_one_that_stopped(stand_in, tmp_path):
    # The stand-in takes a second and reports nothing: longer than the time allowed without progress.
    assert STARTUP_SECONDS >= 60
    result = run_engine(stand_in, "run", tmp_path / "work", tmp_path / "logs", {}, 0.2)
    assert (result.timed_out, result.exit_code) == (False, 0)

    # Once it has reported in, going quiet for that long is a hang.
    stand_in.main_script.write_text(
        "import os, time\n"
        "with open(os.environ['RENPYTESTER_EVENTS'], 'a') as events:\n"
        "    events.write('{\"ev\": \"hello\"}\\n')\n"
        "time.sleep(30)\n", encoding="utf-8")
    started = time.monotonic()
    result = run_engine(stand_in, "run", tmp_path / "work", tmp_path / "logs", {}, 0.5)
    assert result.timed_out is True and [event["ev"] for event in result.events] == ["hello"]
    assert time.monotonic() - started < 15


@pytest.mark.req("RUN-027")
def test_process_that_cannot_be_started_does_not_keep_the_next_one_waiting(stand_in, tmp_path):
    (tmp_path / "logs").write_text("a file where the folder for logs should be", encoding="utf-8")
    with pytest.raises(OSError):
        run_command(stand_in, "lint", [], tmp_path / "work", tmp_path / "logs", 30)
    with pytest.raises(OSError):
        run_engine(stand_in, "run", tmp_path / "work", tmp_path / "logs", {}, 30)
    started = time.monotonic()
    assert Startup(stand_in, tmp_path, "run").enter() is True
    assert time.monotonic() - started < 1


@pytest.mark.req("RUN-027", "CLI-006")
def test_waiting_for_a_turn_to_start_ends_when_the_run_is_stopped(stand_in, tmp_path):
    first = Startup(stand_in, tmp_path, "run")
    assert first.enter() is True
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    try:
        result = run_engine(stand_in, "run", tmp_path / "work", tmp_path / "logs", {}, 30, cancel=stop)
        assert result.cancelled is True
        assert records(stand_in) == []  # It was never started.
    finally:
        first.leave()
