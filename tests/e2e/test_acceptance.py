"""What the acceptance for 1.0 asks for beyond the fixture games (spec 7.4, 5, ARCH-004).

Items 2 and 3 of the acceptance are the test of the reference games in test_fixtures.py, item 4 is
that whole file, item 5 is its sandbox tests, item 6 is this suite run with RENPYTESTER_EXE, and
item 7 is the window's test of a run in both languages. Item 8, and the speed asked for in
section 5, are here.
"""

import ctypes
import json
import pickle
import shutil
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

import pytest

from renpytester import cli, discovery, launcher
from tests.conftest import folder_digest
from tests.e2e.big_game import write_big_game

pytestmark = pytest.mark.e2e

# What the specification asks of a mid-range desktop with four cores (NFR-005, RUN-013).
SECONDS_ALLOWED = 300
STATEMENTS_PER_SECOND = 500


def read_report(folder):
    files = sorted(Path(folder).glob("report-*.json"), key=lambda p: p.stat().st_mtime_ns)
    return json.loads(files[-1].read_text(encoding="utf-8"))


# ------------------------------------------------------------ a game with no script source


def write_archive(path, files):
    """Writes an archive of the kind Ren'Py games are shipped in, holding `files` (name -> bytes)."""
    key = 0x42424242
    index = {}
    with open(path, "wb") as archive:
        archive.write(b" " * 34)  # Where the first line goes, once the place of the index is known.
        for name, data in files.items():
            index[name] = [(archive.tell() ^ key, len(data) ^ key, b"")]
            archive.write(data)
        index_at = archive.tell()
        archive.write(zlib.compress(pickle.dumps(index, 2)))
        archive.seek(0)
        archive.write(b"RPA-3.0 %016x %08x\n" % (index_at, key))


@pytest.mark.req("ARCH-004", "ERR-002", "SAFE-001")
def test_game_whose_scripts_exist_only_compiled_inside_an_archive_is_tested_the_same(sdk, game_copy, tmp_path, capsys):
    game = game_copy("exception")
    folder = game / "game"
    # The engine compiles the script, as it does when a developer builds the game for players.
    with tempfile.TemporaryDirectory() as work:
        code, output = launcher.run_command(
            discovery.discover(game, str(sdk)), "compile", [], work, Path(work) / "logs", 300)
    assert code == 0, output
    compiled = {path.name: path.read_bytes() for path in folder.glob("*.rpyc")}
    assert sorted(compiled) == ["script.rpyc"]
    shutil.rmtree(folder)
    folder.mkdir()
    write_archive(folder / "scripts.rpa", compiled)
    assert [path.name for path in folder.iterdir()] == ["scripts.rpa"]

    before = folder_digest(game)
    output = tmp_path / "report"
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(output), "--lang", "en", "--jobs", "1"])
    capsys.readouterr()
    report = read_report(output)
    assert code == 1
    assert report["game"]["name"] == "Exception Fixture"
    errors = [f for f in report["findings"] if f["severity"] == "error"]
    assert [(f["class"], f["file"], f["line"], f["label"]) for f in errors] == [
        ("exception", "game/script.rpy", 13, "chapter_two")]
    assert report["coverage"]["total"] > 0
    assert folder_digest(game) == before
    assert [path.name for path in folder.iterdir()] == ["scripts.rpa"]


# ------------------------------------------------------------------------ nothing on screen


class Watcher:
    """Looks, many times a second, for a window on screen that belongs to a process this one started.

    Windows only: it is the one system where invisible operation is confirmed (spec 9.1), and the
    one whose windows the standard library can list.
    """

    def __init__(self):
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_void_p), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", ctypes.c_long), ("flags", wintypes.DWORD),
                ("name", ctypes.c_wchar * 260)]

        self.Entry = Entry
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.dword = wintypes.DWORD
        self.own = self.kernel.GetCurrentProcessId()
        # Whatever is running already was not started by this run. Without this, a program whose
        # long-gone parent had the number that one of the game's processes is given later would be
        # taken for that process's child: on a build machine, the terminal the tests run in.
        self.before = set(self.running()[0])
        self.processes = {}
        self.windows = set()
        self.looks = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def running(self):
        """Every process there is: ({pid: its parent's pid}, {pid: program name})."""
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        entry = self.Entry()
        entry.size = ctypes.sizeof(entry)
        parents, names = {}, {}
        more = self.kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            parents[entry.pid], names[entry.pid] = entry.parent, entry.name
            more = self.kernel.Process32NextW(snapshot, ctypes.byref(entry))
        self.kernel.CloseHandle(snapshot)
        return parents, names

    def started_by_us(self):
        """The processes this one started since the watch began, and those they started: {pid: program name}."""
        parents, names = self.running()
        found = {}
        for pid in parents:
            if pid in self.before:
                continue
            ancestor, steps = parents.get(pid), 0
            while ancestor and ancestor != self.own and ancestor not in self.before and steps < 32:
                ancestor, steps = parents.get(ancestor), steps + 1
            if ancestor == self.own:
                found[pid] = names[pid]
        return found

    def look(self):
        ours = self.started_by_us()
        self.processes.update(ours)

        def window(handle, _extra):
            pid = self.dword()
            self.user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            if pid.value in ours and self.user.IsWindowVisible(handle):
                title = ctypes.create_unicode_buffer(200)
                self.user.GetWindowTextW(handle, title, 200)
                self.windows.add((ours[pid.value], title.value))
            return True

        self.user.EnumWindows(self.callback_type(window), 0)
        self.looks += 1

    def watch(self):
        while not self.stop.is_set():
            self.look()
            time.sleep(0.01)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_error):
        self.stop.set()
        self.thread.join()


@pytest.mark.skipif(sys.platform != "win32", reason="windows on screen can only be listed on Windows")
@pytest.mark.req("NFR-007", "ARCH-006", "GAME-007")
def test_no_window_appears_on_screen_while_a_game_is_tested(sdk, tmp_path, capsys):
    """Item 8 of the acceptance for 1.0 (spec 7.4), for what can be seen. That no sound is played
    rests on the engine being given no sound device, which the launcher's unit tests check."""
    game = tmp_path / "the_question"
    shutil.copytree(sdk / "the_question", game)
    with Watcher() as watcher:
        code = cli.main([
            str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--jobs", "3"])
    capsys.readouterr()
    assert code == 0
    # The watcher did see the game's processes come and go, so it would have seen their windows.
    assert watcher.looks > 20
    assert watcher.processes, "no game process was seen"
    assert watcher.windows == set()


# --------------------------------------------------------------------------------- speed


@pytest.mark.req("NFR-005", "RUN-013", "NFR-003")
def test_game_of_fifty_thousand_words_is_tested_within_five_minutes(sdk, tmp_path, capsys):
    import os

    game = tmp_path / "big"
    words, lines, chapters = write_big_game(game)
    assert words >= 50000

    # The limits are for a desktop computer, which a shared build machine is not: there, the run is
    # given all the time it needs, and only what it found is checked.
    shared = bool(os.environ.get("CI"))
    started = time.monotonic()
    # One game process at a time: the slowest way a run can be made, on any number of cores.
    code = cli.main([
        str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--jobs", "1",
        *(["--max-time", "3600"] if shared else [])])
    seconds = time.monotonic() - started
    capsys.readouterr()
    report = read_report(tmp_path / "report")

    assert code == 0
    assert report["complete"] is True and report["findings"] == []
    assert report["statistics"]["script"]["dialogue"] == {
        "blocks": lines, "words": words, "characters": report["statistics"]["script"]["dialogue"]["characters"]}
    routes = report["stages"]["routes"]
    # The whole game was played, not a part of it cut short by a limit.
    assert "limited" not in routes and routes["label_runs"] == chapters
    assert report["coverage"]["executed"] == report["coverage"]["total"]

    # Each line of dialogue played is one interaction. The time is that of the whole run, with
    # starting the engine, lint and the other stages in it, so the true rate is higher than this.
    rate = report["statistics"]["interactions"] / seconds
    print("\n%d words, %d interactions in %.0f seconds: %.0f a second" % (
        words, report["statistics"]["interactions"], seconds, rate))
    if shared:
        return
    assert seconds < SECONDS_ALLOWED
    assert rate >= STATEMENTS_PER_SECOND
