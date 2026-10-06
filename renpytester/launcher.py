"""Starting the game's engine invisibly and watching it (spec GAME-003, -004, -007, RUN-008)."""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SILENT_EDITOR = Path(__file__).resolve().parent / "harness" / "silent_editor.py"


@dataclass
class EngineRun:
    events: list = field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    output: str = ""


def build_environment(events_file, settings, log_dir, show_window=False):
    env = dict(os.environ)
    env["RENPYTESTER_EVENTS"] = str(events_file)
    # A file, not the value itself: a list of branches to resume can be too long for an environment variable.
    settings_file = Path(events_file).with_suffix(".settings.json")
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    env["RENPYTESTER_SETTINGS"] = str(settings_file)

    # Engine logs go to the output folder, never beside the game (SAFE-013).
    env["RENPY_LOG_BASE"] = str(log_dir)
    # No copy of the scripts into the user's profile (SAFE-014). The engine requires this exact text.
    env["RENPY_DISABLE_BACKUPS"] = "I take responsibility for this."
    # The engine opens error reports in the system text editor; give it an editor that opens nothing (GAME-010).
    env["RENPY_EDIT_PY"] = str(SILENT_EDITOR)
    # Errors are printed and the engine exits, instead of opening an interactive error screen.
    env["RENPY_SIMPLE_EXCEPTIONS"] = "1"
    # No "your graphics are slow" prompt, and straight into a new game (RUN-001).
    env["RENPY_PERFORMANCE_TEST"] = "0"
    env["RENPY_SKIP_MAIN_MENU"] = "1"
    env.pop("RENPY_SKIP_SPLASHSCREEN", None)

    if not show_window:
        # No window, no sound, no focus (ARCH-006). The software renderer needs no graphics driver.
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        env["RENPY_RENDERER"] = "sw"

    return env


def read_new_events(handle, sink):
    """Appends complete JSON lines written since the last call. Returns how many were read."""
    count = 0
    while True:
        position = handle.tell()
        line = handle.readline()
        if not line.endswith("\n"):
            handle.seek(position)  # A line still being written; pick it up next time.
            return count
        try:
            sink.append(json.loads(line))
            count += 1
        except ValueError:
            pass


def run_engine(game, command, work_dir, log_dir, settings, timeout, on_event=None, show_window=False):
    """Runs one engine process to completion, or kills it after `timeout` seconds without an event."""
    work_dir = Path(work_dir)
    log_dir = Path(log_dir)
    events_file = work_dir / ("events-%s.jsonl" % command)
    events_file.write_text("", encoding="utf-8")
    output_file = log_dir / ("output-%s.txt" % command)

    # Saves and persistent data go to a throwaway folder, never the player's own (SAFE-004).
    saves = str(work_dir / "saves")
    cmd = [str(game.python), str(game.main_script), str(game.basedir), command, "--savedir", saves]
    env = build_environment(events_file, settings, log_dir, show_window)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    result = EngineRun()
    with open(output_file, "w", encoding="utf-8", errors="replace") as output:
        process = subprocess.Popen(
            cmd, env=env, stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        try:
            with open(events_file, "r", encoding="utf-8") as handle:
                last_activity = time.monotonic()
                while True:
                    before = len(result.events)
                    if read_new_events(handle, result.events):
                        last_activity = time.monotonic()
                        if on_event:
                            for event in result.events[before:]:
                                on_event(event)
                    if process.poll() is not None:
                        before = len(result.events)
                        read_new_events(handle, result.events)
                        if on_event:
                            for event in result.events[before:]:
                                on_event(event)
                        break
                    if time.monotonic() - last_activity > timeout:
                        result.timed_out = True
                        break
                    time.sleep(0.02)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

    result.exit_code = process.returncode
    result.output = output_file.read_text(encoding="utf-8", errors="replace")
    # What the harness reported is kept with the engine's logs: it is the first thing to read when a
    # result looks wrong (REP-008).
    with open(events_file, "rb") as source, open(log_dir / events_file.name, "ab") as kept:
        kept.write(source.read())
    return result


def run_command(game, command, arguments, work_dir, log_dir, timeout):
    """Runs an engine command that reports through files of its own, such as lint.

    The harness stays inert: RENPYTESTER_EVENTS is not set. Returns (exit code or None on timeout, output).
    """
    work_dir = Path(work_dir)
    log_dir = Path(log_dir)
    env = build_environment(work_dir / "unused.jsonl", {}, log_dir)
    del env["RENPYTESTER_EVENTS"]

    saves = str(work_dir / "saves")
    cmd = [str(game.python), str(game.main_script), str(game.basedir), command, *arguments, "--savedir", saves]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            timeout=timeout, creationflags=flags)
        code, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as expired:
        code, output = None, expired.stdout or b""
    output = output.decode("utf-8", errors="replace")
    (log_dir / ("output-%s.txt" % command)).write_text(output, encoding="utf-8")
    return code, output
