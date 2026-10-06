"""Preparing a game folder for a run and putting it back exactly as it was (spec 4.2).

RenPyTester adds only its harness, but the engine itself writes into the game folder on every
launch: compiled caches, an empty saves folder, error reports. So the folder is recorded before
the run, the files the engine is known to rewrite are backed up, and afterwards everything new is
removed and everything changed is restored (SAFE-013). The record lives inside the game folder so
that a run that was killed can be repaired by the next one (SAFE-003).
"""

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from renpytester.errors import ToolError

PREFIX = "zzz_renpytester_"
RUN_DIR = PREFIX + "run"
HARNESS = Path(__file__).resolve().parent / "harness" / (PREFIX + "harness.rpy")

COMPILED = (".rpyc", ".rpymc", ".rpyb")
SCRIPTS = (".rpy", ".rpym")
# Files up to this size are fingerprinted, so a file that was only touched is told from one that changed.
HASH_LIMIT = 1024 * 1024


def fingerprint(path):
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def pid_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not process:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(process)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def scan(basedir, fingerprints=False):
    """Maps every file under basedir to [size, modification time, fingerprint], ignoring our own run folder."""
    found = {}
    for root, dirs, files in os.walk(basedir):
        if RUN_DIR in dirs:
            dirs.remove(RUN_DIR)
        for name in files:
            path = Path(root) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            digest = fingerprint(path) if fingerprints and stat.st_size <= HASH_LIMIT else None
            found[path.relative_to(basedir).as_posix()] = [stat.st_size, stat.st_mtime_ns, digest]
    return found


def scan_dirs(basedir):
    found = set()
    for root, dirs, _files in os.walk(basedir):
        if RUN_DIR in dirs:
            dirs.remove(RUN_DIR)
        for name in dirs:
            found.add((Path(root) / name).relative_to(basedir).as_posix())
    return found


def engine_rewrites(relative):
    """True for files the engine may rewrite by itself, which are backed up before a run."""
    parts = relative.split("/")
    if len(parts) == 1:
        return relative.endswith(".txt")
    if parts[0] != "game":
        return False
    # Scripts are included because engine tools, such as the interactive director, can rewrite them.
    return parts[1] in ("cache", "saves") or relative.endswith(COMPILED) or relative.endswith(SCRIPTS)


class Workspace:
    """Context manager: the game folder is ready for testing inside, and untouched outside."""

    def __init__(self, basedir):
        self.basedir = Path(basedir)
        self.run_dir = self.basedir / RUN_DIR
        self.state_file = self.run_dir / "state.json"
        self.repaired = False
        self.changed_by_game = []
        self.active = False

    # ------------------------------------------------------------------------------ entering

    def __enter__(self):
        self.repair_leftovers()

        files = scan(self.basedir, fingerprints=True)
        dirs = sorted(scan_dirs(self.basedir))

        self.run_dir.mkdir()
        backup = self.run_dir / "backup"
        for relative in files:
            if engine_rewrites(relative):
                target = backup / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.basedir / relative, target)

        state = {"pid": os.getpid(), "started": time.time(), "files": files, "dirs": dirs}
        self.state_file.write_text(json.dumps(state), encoding="utf-8")
        self.active = True

        shutil.copyfile(HARNESS, self.basedir / "game" / HARNESS.name)
        return self

    def repair_leftovers(self):
        """Cleans up after a run that was killed, or refuses if one is still going (SAFE-003, SAFE-005)."""
        if self.run_dir.exists():
            try:
                state = json.loads(self.state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = None

            if state and state.get("pid") != os.getpid() and pid_alive(int(state.get("pid", 0))):
                raise ToolError("error.already_running", path=str(self.basedir), pid=state["pid"])

            if state:
                self.restore(state)
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.repaired = True

        # Harness files with no record: an older version, or a state file that was lost.
        for stray in (self.basedir / "game").glob(PREFIX + "*"):
            if stray.is_file():
                stray.unlink()
                self.repaired = True

    # ------------------------------------------------------------------------------- leaving

    def __exit__(self, *exc_info):
        if not self.active:
            return False
        self.active = False
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.changed_by_game = self.restore(state)
        shutil.rmtree(self.run_dir, ignore_errors=True)
        return False

    def restore(self, state):
        """Returns the folder to its recorded state. Lists files that changed and had no backup (SAFE-007)."""
        before = state["files"]
        before_dirs = set(state["dirs"])
        backup = self.run_dir / "backup"
        unrestored = []

        now = scan(self.basedir)

        for relative in now:
            if relative not in before:
                self._remove(self.basedir / relative)

        for relative, recorded in before.items():
            current = now.get(relative)
            if current is not None and current[:2] == recorded[:2]:
                continue
            target = self.basedir / relative
            saved = backup / relative
            if saved.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, target)
            elif current is not None and recorded[2] is not None and fingerprint(target) == recorded[2]:
                # Rewritten with identical content: only the timestamp needs putting back.
                os.utime(target, ns=(recorded[1], recorded[1]))
            else:
                unrestored.append(relative)

        for relative in sorted(scan_dirs(self.basedir) - before_dirs, key=len, reverse=True):
            try:
                (self.basedir / relative).rmdir()
            except OSError:
                pass

        return sorted(unrestored)

    @staticmethod
    def _remove(path):
        for _attempt in range(20):
            try:
                path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                time.sleep(0.1)  # The engine process may take a moment to let go of its files.
