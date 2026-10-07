"""Starting the game's engine invisibly and watching it (spec GAME-003, -004, -007, RUN-008)."""

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

SILENT_EDITOR = Path(__file__).resolve().parent / "harness" / "silent_editor.py"


def frozen():
    """True when this is the single-file executable and not Python running the source (DIST-002)."""
    return bool(getattr(sys, "frozen", False))


def leave_bundle(environ=None):
    """Stops the single-file executable's own libraries from reaching the programs it starts (DIST-006).

    To find the libraries it carries, the executable puts the folder it unpacked them into first in
    the search for libraries, and what it starts inherits that: the game's engine would be given the
    executable's libraries in place of its own. Run from source, there is nothing to undo.
    """
    if not frozen():
        return
    environ = os.environ if environ is None else environ
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)
    elif sys.platform.startswith("linux"):
        # The executable keeps what the user had here under another name. Libraries this program
        # still has to load are not affected: the search path was read when the process started.
        original = environ.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            environ.pop("LD_LIBRARY_PATH", None)
        else:
            environ["LD_LIBRARY_PATH"] = original


_gates = {}
_gates_lock = threading.Lock()


class Startup:
    """Lets one process at a time start in a game folder (RUN-027).

    A game may write files of its own as it starts, script files among them, and a process that
    reads the script while another is rewriting it loads a game with parts missing. So a process is
    started only when the one before it has loaded the game, which the harness says by making the
    file named in RENPYTESTER_LOADED. After that they run at the same time.
    """

    def __init__(self, game, work_dir, command):
        key = os.path.normcase(os.path.abspath(str(game.basedir)))
        with _gates_lock:
            self.gate = _gates.setdefault(key, threading.Lock())
        self.marker = Path(work_dir) / ("loaded-%s" % command)
        self.held = False

    def enter(self, cancel=None):
        """Waits for its turn. Returns False when the run was stopped while waiting."""
        self.marker.unlink(missing_ok=True)
        while not self.gate.acquire(timeout=0.05):
            if cancel is not None and cancel.is_set():
                return False
        self.held = True
        return True

    def check(self):
        """Lets the next process start once this one has loaded the game."""
        if self.held and self.marker.exists():
            self.leave()

    def leave(self):
        if self.held:
            self.held = False
            self.gate.release()


@dataclass
class EngineRun:
    events: list = field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    output: str = ""


def available_memory():
    """Free physical memory in bytes, or None where the standard library cannot tell."""
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        "total", "available", "total_page", "available_page", "total_virtual",
                        "available_virtual", "extended")]

            status = Status()
            status.length = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.available)
            return None
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None


# What one game process is allowed for when choosing how many to run at once.
MEMORY_PER_PROCESS = 768 * 1024 * 1024
MAX_DEFAULT_JOBS = 8


def default_jobs(cpus=None, memory=None):
    """How many game processes to run at once when the user does not say (RUN-014).

    One core is left for everything else on the computer, and no more processes are started than
    there is free memory for.
    """
    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    memory = memory if memory is not None else available_memory()
    jobs = min(max(cpus - 1, 1), MAX_DEFAULT_JOBS)
    if memory is not None:
        jobs = min(jobs, max(int(memory // MEMORY_PER_PROCESS), 1))
    return jobs


def build_environment(events_file, settings, log_dir, show_window=False, loaded=None):
    env = dict(os.environ)
    env["RENPYTESTER_EVENTS"] = str(events_file)
    env.pop("RENPYTESTER_LOADED", None)
    if loaded is not None:
        # The harness makes this file when the game has been loaded (RUN-027).
        env["RENPYTESTER_LOADED"] = str(loaded)
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
    # The same order inside sets and dictionaries on every run: the engine's lint, and any game that
    # loops over a set, would otherwise give different results from one run to the next (NFR-001).
    env["PYTHONHASHSEED"] = "0"
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


def run_engine(game, command, work_dir, log_dir, settings, timeout, on_event=None, show_window=False, cancel=None):
    """Runs one engine process to completion, or kills it after `timeout` seconds without an event.

    Processes running at the same time must each be given a `work_dir` and a `log_dir` of their own:
    the events file, the saves and the engine's logs live there (RUN-015). `cancel` is an event that,
    once set, has the process shut down.
    """
    work_dir = Path(work_dir)
    log_dir = Path(log_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    events_file = work_dir / ("events-%s.jsonl" % command)
    events_file.write_text("", encoding="utf-8")
    output_file = log_dir / ("output-%s.txt" % command)

    # Saves and persistent data go to a throwaway folder, never the player's own (SAFE-004).
    saves = str(work_dir / "saves")
    cmd = [str(game.python), str(game.main_script), str(game.basedir), command, "--savedir", saves]
    startup = Startup(game, work_dir, command)
    env = build_environment(events_file, settings, log_dir, show_window, startup.marker)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    result = EngineRun()
    # The file is opened before the turn is taken: a turn held by something that then failed
    # would never be given up, and the next process would wait for ever.
    with open(output_file, "w", encoding="utf-8", errors="replace") as output:
        if not startup.enter(cancel):
            result.cancelled = True
            return result
        try:
            process = subprocess.Popen(
                cmd, env=env, stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=flags)
        except BaseException:
            startup.leave()
            raise
        try:
            with open(events_file, "r", encoding="utf-8") as handle:
                last_activity = time.monotonic()
                while True:
                    startup.check()
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
                    if cancel is not None and cancel.is_set():
                        result.cancelled = True
                        break
                    if time.monotonic() - last_activity > timeout:
                        result.timed_out = True
                        break
                    time.sleep(0.02)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            startup.leave()

    result.exit_code = process.returncode
    result.output = output_file.read_text(encoding="utf-8", errors="replace")
    # What the harness reported is kept with the engine's logs: it is the first thing to read when a
    # result looks wrong (REP-008).
    with open(events_file, "rb") as source, open(log_dir / events_file.name, "ab") as kept:
        kept.write(source.read())
    return result


def run_command(game, command, arguments, work_dir, log_dir, timeout, cancel=None):
    """Runs an engine command that reports through files of its own, such as lint.

    The harness stays inert: RENPYTESTER_EVENTS is not set. Returns (exit code or None on timeout, output).
    `cancel` is an event that, once set, has the process shut down; that counts as a timeout.
    """
    work_dir = Path(work_dir)
    log_dir = Path(log_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    startup = Startup(game, work_dir, command)
    env = build_environment(work_dir / "unused.jsonl", {}, log_dir, loaded=startup.marker)
    del env["RENPYTESTER_EVENTS"]

    # A folder of its own: lint may run while the game is being played (RUN-015).
    saves = str(work_dir / ("saves-" + command))
    cmd = [str(game.python), str(game.main_script), str(game.basedir), command, *arguments, "--savedir", saves]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    output_file = log_dir / ("output-%s.txt" % command)
    code = None
    with open(output_file, "wb") as output:
        if not startup.enter(cancel):
            return None, ""
        try:
            process = subprocess.Popen(
                cmd, env=env, stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=flags)
        except BaseException:
            startup.leave()
            raise
        try:
            started = time.monotonic()
            while time.monotonic() - started <= timeout and not (cancel is not None and cancel.is_set()):
                startup.check()
                try:
                    code = process.wait(0.05)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            startup.leave()
    return code, output_file.read_text(encoding="utf-8", errors="replace")
