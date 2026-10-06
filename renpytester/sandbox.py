"""Testing a copy of the game instead of the game (spec SAFE-006, SAFE-009 to SAFE-012).

For a game whose own script writes or deletes files in its folder, nothing can promise to put the
folder back as it was. So the game is copied, once, into a cache folder that belongs to the user,
and the copy is tested. Nothing at all is written to the original.

The copy is kept between runs. Before each run it is made identical to the original again, the way
rsync would do it: only files that are new or have changed are copied, files that are gone from
the original are removed, and files the game altered in the copy are put back (SAFE-010).
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

from renpytester.errors import ToolError
from renpytester.workspace import PREFIX, pid_alive

# Where the cache is, when the user wants it somewhere else than the usual place.
CACHE_VARIABLE = "RENPYTESTER_CACHE"
RECORD = "sandbox.json"
LOCK = "lock.json"
COPY = "copy"


def cache_dir():
    """The per-user folder that sandbox copies are kept in (SAFE-009)."""
    if os.environ.get(CACHE_VARIABLE):
        return Path(os.environ[CACHE_VARIABLE]).expanduser()
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "RenPyTester" / "cache"
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "RenPyTester"
    return Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / "renpytester"


def folder_for(original):
    """The cache folder for one game. Two games with the same folder name still get one each."""
    original = Path(original).resolve()
    slug = re.sub(r"[^a-z0-9]+", "-", original.name.lower()).strip("-")[:40] or "game"
    digest = hashlib.sha1(os.path.normcase(str(original)).encode("utf-8")).hexdigest()[:10]
    return cache_dir() / "sandbox" / ("%s-%s" % (slug, digest))


def scan(root):
    """Maps every file under root to [size, modification time], and lists every folder.

    Anything RenPyTester itself left in a game folder is passed over: it is not part of the game.
    """
    files = {}
    folders = set()
    root = Path(root)
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if PREFIX not in name]
        for name in dirs:
            folders.add((Path(current) / name).relative_to(root).as_posix())
        for name in names:
            if PREFIX in name:
                continue
            path = Path(current) / name
            try:
                status = path.stat()
            except OSError:
                continue
            files[path.relative_to(root).as_posix()] = [status.st_size, status.st_mtime_ns]
    return files, folders


def digest(path):
    found = hashlib.sha1()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            found.update(block)
    return found.hexdigest()


def remove(path):
    """Deletes a file, including one that is marked read-only."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        path.unlink()


def remove_tree(path):
    def retry(function, name, _error):
        os.chmod(name, stat.S_IWRITE | stat.S_IREAD)
        function(name)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def synchronise(original, copy, record=None, verify=False, on_progress=None):
    """Makes `copy` identical to `original`, touching only what differs (SAFE-010).

    `record` is what the last synchronisation wrote down for each file: how the original looked,
    and how the copy looked once it had been copied. A file is left alone when both still look
    that way, by size and modification time (SAFE-011). Each side is only ever compared with
    itself, so it does not matter that two disks keep time with different precision. With
    `verify`, the contents of both files are read and compared, and the record is not trusted.

    Returns (the new record, how many files were copied, how many were removed).
    """
    original, copy = Path(original), Path(copy)
    record = record or {}
    copy.mkdir(parents=True, exist_ok=True)
    wanted, wanted_folders = scan(original)
    present, present_folders = scan_everything(copy)

    removed = 0
    for relative in present:
        if relative not in wanted:
            remove(copy / relative)
            removed += 1
    # Deepest first, so that a folder is empty by the time it is its turn.
    for relative in sorted(present_folders - wanted_folders, key=len, reverse=True):
        if (copy / relative).is_dir():
            remove_tree(copy / relative)
    for relative in sorted(wanted_folders, key=len):
        target = copy / relative
        if target.is_file():
            remove(target)
        target.mkdir(parents=True, exist_ok=True)

    copied = 0
    written = {}
    for number, (relative, source_state) in enumerate(sorted(wanted.items()), 1):
        source, target = original / relative, copy / relative
        same = relative in present and target.is_file()
        if same and verify:
            same = source_state[0] == present[relative][0] and digest(source) == digest(target)
        elif same:
            known = record.get(relative)
            same = known is not None and known["source"] == source_state and known["copy"] == present[relative]
        if not same:
            if target.is_dir():
                remove_tree(target)
            else:
                remove(target)
            shutil.copy2(source, target)
            copied += 1
        status = target.stat()
        written[relative] = {"source": source_state, "copy": [status.st_size, status.st_mtime_ns]}
        if on_progress and number % 200 == 0:
            on_progress(number, len(wanted))

    return written, copied, removed


def scan_everything(root):
    """Like scan, but of a sandbox copy: there, what RenPyTester left behind is to be cleaned away too."""
    files = {}
    folders = set()
    root = Path(root)
    for current, dirs, names in os.walk(root):
        for name in dirs:
            folders.add((Path(current) / name).relative_to(root).as_posix())
        for name in names:
            path = Path(current) / name
            try:
                status = path.stat()
            except OSError:
                continue
            files[path.relative_to(root).as_posix()] = [status.st_size, status.st_mtime_ns]
    return files, folders


def size_of(folder):
    """(bytes, files) under a folder."""
    total = count = 0
    for current, _dirs, names in os.walk(folder):
        for name in names:
            try:
                total += (Path(current) / name).stat().st_size
                count += 1
            except OSError:
                pass
    return total, count


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def user_of(folder):
    """The process that is testing the copy in this cache folder right now, or None."""
    pid = read_json(Path(folder) / LOCK).get("pid")
    if isinstance(pid, int) and pid != os.getpid() and pid_alive(pid):
        return pid
    return None


class Sandbox:
    """Context manager: inside, `copy` is a folder identical to the game that may be tested freely."""

    def __init__(self, original, verify=False, on_progress=None):
        self.original = Path(original).resolve()
        self.folder = folder_for(self.original)
        self.copy = self.folder / COPY
        self.verify = verify
        self.on_progress = on_progress
        self.copied = 0
        self.removed = 0
        self.bytes = 0
        self.files = 0

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        pid = user_of(self.folder)
        if pid is not None:
            # Two runs in one copy would each clean up what the other is using (SAFE-005).
            raise ToolError("error.already_running", path=str(self.original), pid=pid)
        (self.folder / LOCK).write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        try:
            record = read_json(self.folder / RECORD)
            written, self.copied, self.removed = synchronise(
                self.original, self.copy, record.get("files"), self.verify, self.on_progress)
            self.write_record(written)
        except BaseException:
            remove(self.folder / LOCK)
            raise
        return self

    def write_record(self, written=None):
        record = read_json(self.folder / RECORD)
        if written is not None:
            record["files"] = written
        self.bytes, self.files = size_of(self.copy)
        record.update(
            original=str(self.original), bytes=self.bytes, count=self.files,
            last_used=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
        (self.folder / RECORD).write_text(json.dumps(record), encoding="utf-8")

    def __exit__(self, *exc_info):
        try:
            self.write_record()
        finally:
            remove(self.folder / LOCK)
        return False

    def describe(self):
        """What the report says about the copy (SAFE-012)."""
        return {
            "path": str(self.copy), "bytes": self.bytes, "files": self.files, "copied": self.copied,
            "removed": self.removed, "verified": self.verify}


def listing():
    """Every sandbox copy in the cache, as dictionaries, in the order of the games' paths (SAFE-012)."""
    found = []
    root = cache_dir() / "sandbox"
    if not root.is_dir():
        return found
    for folder in sorted(root.iterdir()):
        if not (folder / COPY).is_dir():
            continue
        record = read_json(folder / RECORD)
        total, count = size_of(folder / COPY)
        found.append({
            "folder": folder, "original": record.get("original") or "?", "bytes": total, "files": count,
            "last_used": record.get("last_used"), "in_use": user_of(folder) is not None})
    return sorted(found, key=lambda entry: entry["original"])


def clear(original=None):
    """Deletes the copy of one game, or every copy. Copies being tested right now are left alone.

    Returns (how many were deleted, the bytes that freed, how many were in use and kept).
    """
    wanted = folder_for(original) if original is not None else None
    deleted = freed = kept = 0
    for entry in listing():
        if wanted is not None and entry["folder"] != wanted:
            continue
        if entry["in_use"]:
            kept += 1
            continue
        remove_tree(entry["folder"])
        deleted += 1
        freed += entry["bytes"]
    return deleted, freed, kept
