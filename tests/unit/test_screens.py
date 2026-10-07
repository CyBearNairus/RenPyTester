"""The orchestrator's side of the screens stage (spec 4.8): no engine needed."""

import io

import pytest

from renpytester import i18n
from renpytester.model import Report
from renpytester.report.console import Console
from renpytester.runner import SCREENS, STAGES, Options, finish_screens


def screen_error(language=None):
    params = {"screen": "preferences", "type": "NameError", "message": "name 'volume' is not defined"}
    if language:
        params["language"] = language
    return {
        "ev": "finding", "cls": "screen-error", "severity": "error", "params": params, "file": "game/screens.rpy",
        "line": 13, "stage": "screens", "language": language, "path": [],
        "message_id": "finding.screen_error.language" if language else "finding.screen_error"}


def finished(*events):
    report = Report("0", "game")
    report.stages = {SCREENS: {"status": "running"}}
    finish_screens(list(events), report)
    return report


@pytest.mark.req("UI-001", "CLI-001")
def test_menu_screens_are_checked_by_default():
    assert SCREENS in STAGES
    assert Options(game="").stages == STAGES


@pytest.mark.req("UI-001", "UI-002")
def test_what_was_built_and_what_was_found_go_into_the_report():
    report = finished(
        screen_error(), screen_error("french"),
        {"ev": "screens", "blocked": False, "screens": ["preferences", "about"], "skipped": [],
         "languages": [None, "french"], "not_switched": []},
        {"ev": "done"})
    assert report.stages[SCREENS] == {
        "status": "done", "screens": ["preferences", "about"], "skipped": [], "languages": [None, "french"],
        "not_switched": [], "findings": 2}
    assert [(f.cls, f.stage, f.language) for f in report.findings] == [
        ("screen-error", "screens", None), ("screen-error", "screens", "french")]
    # The same screen failing in a language is a finding of its own, with an id of its own.
    assert len({finding.id for finding in report.findings}) == 2
    assert report.notes == []


@pytest.mark.req("UI-001", "UI-002", "COMPAT-005")
def test_what_could_not_be_checked_is_said_in_a_note():
    report = finished({
        "ev": "screens", "blocked": False, "screens": ["about"], "skipped": ["save", "load"], "languages": [None],
        "not_switched": ["french"]})
    assert report.stages[SCREENS]["status"] == "done"
    assert report.notes == [
        {"message_id": "note.screens_skipped", "params": {"screens": "save, load"}},
        {"message_id": "note.screens_languages", "params": {"languages": "french"}}]


@pytest.mark.req("UI-001", "NFR-002")
def test_game_that_cannot_start_blocks_the_stage_and_a_stage_that_did_not_finish_stays_unfinished():
    report = finished(
        {"ev": "finding", "cls": "load-failure", "severity": "error", "message_id": "finding.load_failure",
         "params": {"message": "NameError: nothing"}, "file": "game/script.rpy", "line": 4, "stage": "screens"},
        {"ev": "screens", "blocked": True, "screens": [], "skipped": [], "languages": [], "not_switched": []})
    assert (report.stages[SCREENS]["status"], report.stages[SCREENS]["findings"]) == ("blocked", 1)

    report = Report("0", "game")
    report.stages = {SCREENS: {"status": "failed", "reason": "timeout"}}
    finish_screens(None, report)
    assert report.stages[SCREENS] == {"status": "failed", "reason": "timeout"}


@pytest.mark.req("UI-001", "REP-001", "I18N-001")
@pytest.mark.parametrize("lang, built, none", [
    ("en", "Menu screens checked: 2 (preferences, about). Languages they were checked in: 3.",
     "This game defines none of the standard menu screens"),
    ("pt-BR", "Telas de menu verificadas: 2 (preferences, about). Idiomas em que foram verificadas: 3.",
     "Este jogo não define nenhuma das telas de menu padrão")])
def test_console_summary_says_which_menu_screens_were_built(tmp_path, lang, built, none):
    i18n.set_language(lang)
    try:
        for screens, expected in ((["preferences", "about"], built), ([], none)):
            report = finished({
                "ev": "screens", "blocked": False, "screens": screens, "skipped": [],
                "languages": [None, "french", "spanish"], "not_switched": []})
            report.complete = True
            stream = io.StringIO()
            paths = {name: tmp_path / ("report." + name) for name in ("html", "json", "junit")}
            Console(stream).summary(report, paths, False)
            assert expected in stream.getvalue()
    finally:
        i18n.set_language("en")
