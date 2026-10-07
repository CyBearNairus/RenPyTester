"""End-to-end tests of the screens stage: the menu screens a story never opens (spec 4.8)."""

import pytest

pytestmark = pytest.mark.e2e

# What the stage records when it built every screen it found, in the game's own language only.
OWN_LANGUAGE = {"skipped": [], "languages": [None], "not_switched": []}


@pytest.mark.req("UI-001", "ERR-002", "REP-006")
def test_menu_screen_that_cannot_be_shown_is_reported_where_it_fails(run):
    code, report, text, _game = run("screen_error")
    assert code == 1
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["severity"], finding["stage"]) == ("screen-error", "error", "screens")
    assert (finding["file"], finding["line"], finding["language"]) == ("game/screens.rpy", 13, None)
    assert finding["params"] == {
        "screen": "preferences", "type": "NameError", "message": "name 'volume_level' is not defined"}
    assert "volume_level" in finding["traceback"]
    # The screen that works is built too, and says nothing.
    assert report["stages"]["screens"] == dict(
        OWN_LANGUAGE, status="done", screens=["preferences", "about"], findings=1)
    assert "game/screens.rpy:13" in text
    assert "The 'preferences' screen cannot be shown: NameError" in text
    assert "Menu screens checked: 2 (preferences, about)." in text


@pytest.mark.req("UI-001", "ERR-003", "ERR-013")
def test_picture_missing_from_a_menu_screen_is_reported(run):
    code, report, _text, _game = run("screen_missing_image")
    assert code == 1
    assert [(f["class"], f["severity"], f["stage"], f["file"], f["line"]) for f in report["findings"]] == [
        ("missing-file", "error", "screens", "game/screens.rpy", 7)]
    assert report["findings"][0]["params"] == {"file": "pictures/studio_logo.png"}


@pytest.mark.req("UI-001", "ERR-005", "ERR-013")
def test_broken_text_tag_in_a_menu_screen_is_reported(run):
    code, report, _text, _game = run("screen_bad_text")
    assert code == 1
    assert [(f["class"], f["severity"], f["stage"], f["file"], f["line"]) for f in report["findings"]] == [
        ("bad-text", "error", "screens", "game/screens.rpy", 7)]
    assert report["findings"][0]["params"]["text"] == "Press {b}Enter to go on."


@pytest.mark.req("UI-002", "UI-001")
def test_menu_screen_that_fails_only_in_a_translation_is_reported_for_that_language(run):
    code, report, text, _game = run("tl_screen")
    assert code == 1
    found = {f["class"]: f for f in report["findings"]}
    # The translations stage reads the same mistake where it was written, as a difference in variables.
    assert sorted(found) == ["screen-error", "variable-mismatch"]
    finding = found["screen-error"]
    assert (finding["severity"], finding["stage"], finding["language"]) == ("error", "screens", "portuguese")
    assert (finding["file"], finding["line"]) == ("game/screens.rpy", 3)
    assert (finding["params"]["screen"], finding["params"]["language"]) == ("about", "portuguese")
    assert "estudio" in finding["params"]["message"]
    assert report["stages"]["screens"] == {
        "status": "done", "screens": ["about"], "skipped": [], "languages": [None, "portuguese"],
        "not_switched": [], "findings": 1}
    assert "The 'about' screen cannot be shown in portuguese" in text
    assert "Languages they were checked in: 2." in text


@pytest.mark.req("UI-002", "TL-001")
def test_menu_screens_are_built_only_in_the_languages_asked_for(run):
    # The game has one other language, which is not asked for here: the screen works in the game's own.
    code, report, _text, _game = run("tl_screen", "--stages", "screens", "--languages", "")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["screens"] == dict(OWN_LANGUAGE, status="done", screens=["about"], findings=0)


@pytest.mark.req("UI-001", "COMPAT-005", "NFR-002")
def test_screen_that_asks_for_values_of_its_own_is_left_out_and_the_report_says_so(run):
    code, report, text, _game = run("screen_arguments")
    assert code == 0
    assert report["findings"] == []
    # The confirm screen is given what the engine gives it; nobody can tell what this save screen wants.
    assert report["stages"]["screens"] == {
        "status": "done", "screens": ["confirm"], "skipped": ["save"], "languages": [None], "not_switched": [],
        "findings": 0}
    assert {"message_id": "note.screens_skipped", "params": {"screens": "save"}} in report["notes"]
    assert "so they were not checked: save" in text


@pytest.mark.req("UI-001", "CLI-002")
def test_game_with_no_menu_screens_has_none_to_check(run):
    code, report, text, _game = run("clean", "--stages", "screens")
    assert code == 0
    assert report["stages"]["screens"] == dict(OWN_LANGUAGE, status="done", screens=[], findings=0)
    assert report["stages"]["routes"] == {"status": "not_selected"}
    assert "defines none of the standard menu screens" in text

    _code, report, _text, _game = run("clean", "--stages", "routes")
    assert report["stages"]["screens"] == {"status": "not_selected"}


@pytest.mark.req("UI-002", "TL-002", "COMPAT-005")
def test_language_that_cannot_be_switched_to_has_its_screens_left_unchecked_and_said_so(run):
    code, report, _text, _game = run("tl_switch", "--stages", "screens")
    assert code == 0
    stage = report["stages"]["screens"]
    assert (stage["languages"], stage["not_switched"]) == ([None], ["portuguese"])
    assert {"message_id": "note.screens_languages", "params": {"languages": "portuguese"}} in report["notes"]
    # Why it cannot be switched to is the translation stage's to say, and it is said once.
    assert report["findings"] == []


@pytest.mark.req("UI-001", "NFR-001", "RUN-015")
def test_screen_findings_do_not_depend_on_the_number_of_processes(run, tmp_path):
    _code, alone, _text, _game = run("screen_error")
    _code, together, _text, _game = run("screen_error", "--jobs", "3")
    assert alone["findings"] == together["findings"]
    assert alone["stages"]["screens"] == together["stages"]["screens"]
    # The process that builds the screens has a folder of its own for what it writes.
    logs = sorted((tmp_path / "report").glob("report-*-logs"))[-1]
    assert (logs / "screens" / "events-run.jsonl").stat().st_size > 0
