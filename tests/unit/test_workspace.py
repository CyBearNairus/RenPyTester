import json
import os

import pytest

from renpytester.errors import ToolError
from renpytester.workspace import PREFIX, RUN_DIR, Workspace
from tests.conftest import folder_digest


@pytest.fixture
def game(tmp_path):
    base = tmp_path / "Game"
    (base / "game" / "cache").mkdir(parents=True)
    (base / "game" / "script.rpy").write_text("label start:\n    return\n")
    (base / "game" / "script.rpyc").write_bytes(b"compiled")
    (base / "game" / "cache" / "bytecode-312.rpyb").write_bytes(b"cache")
    (base / "game" / "art.png").write_bytes(b"x" * 2048)
    return base


def stamps(game):
    return {p: p.stat().st_mtime_ns for p in game.rglob("*") if p.is_file()}


@pytest.mark.req("SAFE-001")
def test_only_prefixed_files_are_added(game):
    before = {p.relative_to(game).as_posix() for p in game.rglob("*")}
    with Workspace(game):
        added = {p.relative_to(game).as_posix() for p in game.rglob("*")} - before
        assert added
        assert all(PREFIX in name for name in added), added
        assert (game / "game" / (PREFIX + "harness.rpy")).is_file()


@pytest.mark.req("SAFE-001", "SAFE-002", "SAFE-013")
def test_folder_is_identical_after_the_engine_has_written_into_it(game):
    before = folder_digest(game)
    before_stamps = stamps(game)
    with Workspace(game):
        # What a real engine launch does to a game folder.
        (game / "game" / "cache" / "bytecode-312.rpyb").write_bytes(b"rewritten by the engine")
        (game / "game" / "cache" / "screens.rpyb").write_bytes(b"new")
        (game / "game" / "script.rpyc").unlink()
        (game / "game" / (PREFIX + "harness.rpyc")).write_bytes(b"compiled harness")
        (game / "game" / "saves").mkdir()
        (game / "log.txt").write_text("log")
        (game / "traceback.txt").write_text("trace")
    assert folder_digest(game) == before
    assert not (game / "game" / "saves").exists()
    assert not (game / RUN_DIR).exists()
    assert stamps(game) == before_stamps


@pytest.mark.req("SAFE-002")
def test_folder_is_restored_when_the_run_fails(game):
    before = folder_digest(game)
    with pytest.raises(RuntimeError):
        with Workspace(game):
            (game / "log.txt").write_text("log")
            raise RuntimeError("the run blew up")
    assert folder_digest(game) == before


@pytest.mark.req("SAFE-003")
def test_leftovers_of_a_killed_run_are_repaired(game):
    before = folder_digest(game)
    abandoned = Workspace(game)
    abandoned.__enter__()
    (game / "game" / "cache" / "bytecode-312.rpyb").write_bytes(b"rewritten")
    (game / "log.txt").write_text("log")
    # The process dies here with no cleanup. Give the record a process id that belongs to nobody.
    state = json.loads(abandoned.state_file.read_text())
    state["pid"] = 2 ** 22 + 12345
    abandoned.state_file.write_text(json.dumps(state))

    with Workspace(game) as fresh:
        assert fresh.repaired
    assert folder_digest(game) == before


@pytest.mark.req("SAFE-003")
def test_stray_harness_file_without_a_record_is_removed(game):
    before = folder_digest(game)
    (game / "game" / (PREFIX + "harness.rpy")).write_text("old")
    with Workspace(game) as workspace:
        assert workspace.repaired
    assert folder_digest(game) == before


@pytest.mark.req("SAFE-005")
def test_second_run_on_the_same_game_is_refused(game):
    with Workspace(game) as first:
        state = json.loads(first.state_file.read_text())
        state["pid"] = os.getppid()  # A different process that is certainly alive.
        first.state_file.write_text(json.dumps(state))
        with pytest.raises(ToolError) as error:
            Workspace(game).__enter__()
        assert error.value.message_id == "error.already_running"
        state["pid"] = os.getpid()
        first.state_file.write_text(json.dumps(state))


@pytest.mark.req("SAFE-007")
def test_files_the_game_changed_itself_are_reported(game):
    (game / "game" / "old.txt").write_text("to be deleted")
    with Workspace(game) as workspace:
        (game / "game" / "art.png").write_bytes(b"y" * 4096)
        (game / "game" / "old.txt").unlink()
        (game / "game" / "diary.txt").write_text("written by the game")
        # What the engine and the tool leave behind is not the game's doing.
        (game / "game" / "script.rpyc").write_bytes(b"compiled")
        (game / "log.txt").write_text("engine log")
    assert workspace.game_wrote == {
        "created": ["game/diary.txt"], "changed": ["game/art.png"], "deleted": ["game/old.txt"]}
    # What was created is removed again; what was changed or deleted had no backup and stays so.
    assert not (game / "game" / "diary.txt").exists()
    assert not (game / "game" / "old.txt").exists()
    assert not (game / "log.txt").exists()


@pytest.mark.req("SAFE-013")
def test_a_file_that_was_only_touched_is_not_reported(game):
    art = game / "game" / "art.png"
    stamp = art.stat().st_mtime_ns
    with Workspace(game) as workspace:
        art.write_bytes(art.read_bytes())
        os.utime(art, ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    assert workspace.game_wrote == {"created": [], "changed": [], "deleted": []}
    assert art.stat().st_mtime_ns == stamp
