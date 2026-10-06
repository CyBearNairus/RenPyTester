"""The cached copy of a game and how it is kept identical to the original (spec SAFE-006, SAFE-009 to SAFE-012)."""

import json
import os
import stat

import pytest

from renpytester import sandbox
from renpytester.errors import ToolError
from renpytester.report import human_size
from tests.conftest import folder_digest


@pytest.fixture
def original(tmp_path):
    root = tmp_path / "My Game"
    (root / "game" / "images").mkdir(parents=True)
    (root / "game" / "empty").mkdir()
    (root / "game" / "script.rpy").write_bytes(b"label start:\n    return\n")
    (root / "game" / "images" / "room.png").write_bytes(b"x" * 5000)
    (root / "notes.txt").write_bytes(b"notes")
    return root


def same_tree(a, b):
    def folders(root):
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())

    return folder_digest(a) == folder_digest(b) and folders(a) == folders(b)


def synchronise(original, copy, record=None, verify=False):
    record, copied, removed = sandbox.synchronise(original, copy, record, verify)
    assert same_tree(original, copy)
    return record, copied, removed


@pytest.mark.req("SAFE-009")
def test_copies_are_kept_in_a_folder_of_the_users(own_cache, tmp_path, monkeypatch):
    assert sandbox.cache_dir() == own_cache
    first, second = sandbox.folder_for(tmp_path / "a" / "Game"), sandbox.folder_for(tmp_path / "b" / "Game")
    assert first.parent == own_cache / "sandbox"
    # Two games in folders of the same name do not share a copy, and one game always gets the same one.
    assert first != second and first.name.startswith("game-")
    assert first == sandbox.folder_for(tmp_path / "a" / "Game")

    monkeypatch.delenv("RENPYTESTER_CACHE")
    assert "renpytester" in str(sandbox.cache_dir()).lower()
    assert sandbox.cache_dir().is_absolute()


@pytest.mark.req("SAFE-010")
def test_first_synchronisation_copies_everything(original, tmp_path):
    record, copied, removed = synchronise(original, tmp_path / "copy")
    assert (copied, removed) == (3, 0)
    assert sorted(record) == ["game/images/room.png", "game/script.rpy", "notes.txt"]
    assert (tmp_path / "copy" / "game" / "empty").is_dir()


@pytest.mark.req("SAFE-010", "SAFE-011")
def test_only_what_changed_in_the_original_is_copied_again(original, tmp_path):
    copy = tmp_path / "copy"
    record, _copied, _removed = synchronise(original, copy)
    assert synchronise(original, copy, record)[1:] == (0, 0)

    (original / "game" / "script.rpy").write_text("label start:\n    \"A new line.\"\n    return\n")
    (original / "game" / "chapter2.rpy").write_text("label two:\n    return\n")
    (original / "game" / "images" / "room.png").unlink()
    (original / "game" / "empty").rmdir()
    (original / "game" / "audio").mkdir()
    record, copied, removed = synchronise(original, copy, record)
    assert (copied, removed) == (2, 1)
    assert not (copy / "game" / "images" / "room.png").exists()
    assert not (copy / "game" / "empty").exists()
    assert synchronise(original, copy, record)[1:] == (0, 0)


@pytest.mark.req("SAFE-010")
def test_what_the_game_did_to_the_copy_is_undone(original, tmp_path):
    copy = tmp_path / "copy"
    record, _copied, _removed = synchronise(original, copy)

    (copy / "game" / "script.rpy").write_text("changed by the game, and longer than before")
    (copy / "notes.txt").unlink()
    (copy / "game" / "saved_by_game.dat").write_bytes(b"1234")
    (copy / "game" / "made_by_game").mkdir()
    (copy / "game" / "made_by_game" / "deep.txt").write_text("deep")
    (copy / "game" / "zzz_renpytester_harness.rpy").write_text("left by a run that was killed")
    record, copied, removed = synchronise(original, copy, record)
    assert (copied, removed) == (2, 3)
    assert not (copy / "game" / "made_by_game").exists()


@pytest.mark.req("SAFE-010")
def test_a_file_and_a_folder_that_swapped_places_are_put_right(original, tmp_path):
    copy = tmp_path / "copy"
    record, _copied, _removed = synchronise(original, copy)
    (copy / "notes.txt").unlink()
    (copy / "notes.txt").mkdir()
    (copy / "notes.txt" / "inside.txt").write_text("x")
    (copy / "game" / "empty").rmdir()
    (copy / "game" / "empty").write_text("now a file")
    synchronise(original, copy, record)
    assert (copy / "notes.txt").read_text() == "notes"
    assert (copy / "game" / "empty").is_dir()


@pytest.mark.req("SAFE-011")
def test_change_that_keeps_size_and_date_is_found_only_by_comparing_contents(original, tmp_path):
    copy = tmp_path / "copy"
    record, _copied, _removed = synchronise(original, copy)

    target = copy / "game" / "images" / "room.png"
    before = target.stat()
    target.write_bytes(b"y" * 5000)
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))

    # Sizes and dates say nothing has changed.
    record, copied, _removed = sandbox.synchronise(original, copy, record)
    assert copied == 0
    assert target.read_bytes() == b"y" * 5000
    # The contents say otherwise.
    record, copied, _removed = synchronise(original, copy, record, verify=True)
    assert copied == 1
    assert synchronise(original, copy, record, verify=True)[1:] == (0, 0)


@pytest.mark.req("SAFE-010", "SAFE-011")
def test_copy_with_no_record_is_not_trusted(original, tmp_path):
    copy = tmp_path / "copy"
    synchronise(original, copy)
    assert synchronise(original, copy, record=None)[1] == 3
    # Comparing contents needs no record: identical files are left alone.
    assert synchronise(original, copy, record=None, verify=True)[1] == 0


@pytest.mark.req("SAFE-010")
def test_read_only_files_do_not_stop_the_synchronisation(original, tmp_path):
    copy = tmp_path / "copy"
    script = original / "game" / "script.rpy"
    os.chmod(script, stat.S_IREAD)
    try:
        record, _copied, _removed = synchronise(original, copy)
        os.chmod(script, stat.S_IREAD | stat.S_IWRITE)
        script.write_text("label start:\n    \"Edited.\"\n    return\n")
        os.chmod(script, stat.S_IREAD)
        (original / "notes.txt").unlink()
        os.chmod(copy / "notes.txt", stat.S_IREAD)
        assert synchronise(original, copy, record)[1:] == (1, 1)
    finally:
        os.chmod(script, stat.S_IREAD | stat.S_IWRITE)
        for path in copy.rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.req("SAFE-006")
def test_leftovers_of_the_tool_in_the_original_are_not_copied(original, tmp_path):
    (original / "zzz_renpytester_run").mkdir()
    (original / "zzz_renpytester_run" / "state.json").write_text("{}")
    (original / "game" / "zzz_renpytester_harness.rpy").write_text("left by a run that was killed")
    before = folder_digest(original)
    _record, copied, _removed = sandbox.synchronise(original, tmp_path / "copy")
    assert copied == 3
    assert not list((tmp_path / "copy").rglob("zzz_renpytester_*"))
    assert folder_digest(original) == before


@pytest.mark.req("SAFE-006", "SAFE-009", "SAFE-010", "SAFE-012")
def test_sandbox_is_made_once_and_then_only_brought_up_to_date(original):
    before = folder_digest(original)
    with sandbox.Sandbox(original) as first:
        assert same_tree(original, first.copy)
        assert first.copy == sandbox.folder_for(original) / "copy"
        (first.copy / "game" / "written_while_testing.txt").write_text("x" * 100)
    assert first.describe() == {
        "path": str(first.copy), "bytes": 5000 + 24 + 5 + 100, "files": 4, "copied": 3, "removed": 0,
        "verified": False}

    (original / "notes.txt").write_text("new notes")
    with sandbox.Sandbox(original) as second:
        assert same_tree(original, second.copy)
    assert (second.copied, second.removed, second.files) == (1, 1, 3)
    # The original was only ever read.
    (original / "notes.txt").write_bytes(b"notes")
    assert folder_digest(original) == before


@pytest.mark.req("SAFE-005")
def test_copy_that_is_being_tested_is_not_given_to_a_second_run(original):
    with sandbox.Sandbox(original) as first:
        lock = first.folder / "lock.json"
        # As if another RenPyTester process, one that is alive, held the copy.
        lock.write_text(json.dumps({"pid": os.getppid()}))
        with pytest.raises(ToolError) as raised:
            sandbox.Sandbox(original).__enter__()
        assert raised.value.message_id == "error.already_running"
        assert raised.value.params["pid"] == os.getppid()
        assert sandbox.clear() == (0, 0, 1)
        lock.write_text(json.dumps({"pid": os.getpid()}))
    assert not lock.exists()
    # A lock left by a process that is gone does not block anything.
    lock.write_text(json.dumps({"pid": 0}))
    with sandbox.Sandbox(original):
        pass


@pytest.mark.req("SAFE-012")
def test_copies_can_be_listed_and_cleared(original, tmp_path):
    other = tmp_path / "Other Game"
    (other / "game").mkdir(parents=True)
    (other / "game" / "script.rpy").write_text("x" * 10)
    assert sandbox.listing() == []
    for game in (original, other):
        with sandbox.Sandbox(game):
            pass

    listed = sandbox.listing()
    assert [(entry["original"], entry["bytes"], entry["files"], entry["in_use"]) for entry in listed] == [
        (str(original.resolve()), 5029, 3, False), (str(other.resolve()), 10, 1, False)]
    assert all(entry["last_used"] for entry in listed)

    assert sandbox.clear(other) == (1, 10, 0)
    assert [entry["original"] for entry in sandbox.listing()] == [str(original.resolve())]
    assert sandbox.clear(other) == (0, 0, 0)
    assert sandbox.clear() == (1, 5029, 0)
    assert sandbox.listing() == []


def test_sizes_are_shown_in_units_people_read():
    assert [human_size(n) for n in (0, 999, 1024, 1536, 5 * 1024 ** 2, 3 * 1024 ** 3, 2000 * 1024 ** 3)] == [
        "0 bytes", "999 bytes", "1.0 KB", "1.5 KB", "5.0 MB", "3.0 GB", "2000.0 GB"]
