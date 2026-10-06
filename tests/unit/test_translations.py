"""The orchestrator's side of the translations stage (spec 4.7): no engine needed."""

import io

import pytest

from renpytester import i18n
from renpytester.errors import UsageError
from renpytester.model import ERROR, WARNING, Finding, Report
from renpytester.report.console import UNTRANSLATED_SHOWN, Console
from renpytester.runner import ROUTES, TRANSLATIONS, Options, finish_translations, languages_to_check, to_finding


def untranslated(line, language="portuguese"):
    return Finding(
        "untranslated", WARNING, "finding.untranslated_line", {"language": language, "text": "Line %d" % line},
        "game/script.rpy", line, stage=TRANSLATIONS, language=language)


@pytest.mark.req("TL-001")
def test_every_language_is_checked_unless_some_are_named():
    known = ["french", "portuguese", "spanish"]
    assert languages_to_check(Options(game=""), known) == known
    assert languages_to_check(Options(game="", languages=("spanish", "french")), known) == ["french", "spanish"]
    assert languages_to_check(Options(game=""), []) == []


@pytest.mark.req("TL-001", "CLI-003")
def test_language_the_game_does_not_have_is_a_usage_error():
    with pytest.raises(UsageError) as raised:
        languages_to_check(Options(game="", languages=("klingon", "french")), ["french"])
    assert raised.value.exit_code == 2
    assert raised.value.params == {"languages": "klingon", "known": "french"}


@pytest.mark.req("TL-004")
def test_translation_tried_out_while_playing_belongs_to_the_translations_stage():
    event = {
        "ev": "finding", "cls": "bad-interpolation", "severity": "error", "message_id": "finding.bad_interpolation",
        "params": {"language": "portuguese"}, "file": "game/tl/portuguese/script.rpy", "line": 7,
        "stage": "translations", "language": "portuguese", "possible": True, "path": [{"kind": "label"}]}
    finding = to_finding(event, ROUTES)
    assert (finding.stage, finding.language, finding.possible) == ("translations", "portuguese", True)
    # A finding the harness does not place in a stage belongs to the one that was running.
    assert to_finding(dict(event, stage=None, language=None), ROUTES).stage == ROUTES


@pytest.mark.req("TL-012", "TL-004", "NFR-002")
def test_summary_for_each_language_and_a_note_when_the_game_was_not_played():
    report = Report("0", "game")
    report.stages = {ROUTES: {"status": "not_selected"}, TRANSLATIONS: {"status": "running", "languages": {}}}
    finish_translations([
        {"ev": "translations", "languages": ["portuguese"], "read_source": True},
        {"ev": "finding", "cls": "untranslated", "severity": "warning", "message_id": "finding.untranslated_line",
         "params": {"language": "portuguese", "text": "Hello."}, "file": "game/script.rpy", "line": 8,
         "stage": "translations", "language": "portuguese"},
        {"ev": "language", "language": "portuguese", "switched": True, "dialogue": [3, 4], "strings": [1, 2]},
        {"ev": "done"}], report)
    stage = report.stages[TRANSLATIONS]
    assert stage == {
        "status": "done", "findings": 1, "played": False, "languages": {"portuguese": {
            "switched": True, "dialogue": {"translated": 3, "total": 4}, "strings": {"translated": 1, "total": 2}}}}
    assert [note["message_id"] for note in report.notes] == ["note.translations_not_played"]
    assert report.findings[0].language == "portuguese"


@pytest.mark.req("TL-005", "NFR-002")
def test_game_with_no_script_source_says_which_texts_could_not_be_listed():
    report = Report("0", "game")
    report.stages = {ROUTES: {"status": "done"}, TRANSLATIONS: {"status": "running", "languages": {}}}
    finish_translations([{"ev": "translations", "languages": ["portuguese"], "read_source": False}], report)
    assert report.stages[TRANSLATIONS]["strings_from_source"] is False
    assert [note["message_id"] for note in report.notes] == ["note.strings_need_source"]


@pytest.mark.req("TL-004", "TL-006", "ERR-010")
def test_variable_mismatch_is_folded_into_the_failure_it_causes():
    report = Report("0", "game")
    place = ("game/tl/portuguese/script.rpy", 7)
    report.add(Finding(
        "bad-interpolation", ERROR, "finding.bad_interpolation", {"language": "portuguese"}, *place,
        stage=TRANSLATIONS, language="portuguese"))
    report.add(Finding(
        "variable-mismatch", WARNING, "finding.variable_mismatch", {"language": "portuguese", "extra": "x"}, *place,
        stage=TRANSLATIONS, language="portuguese"))
    # The same kind of mismatch on a line that did not fail stays a finding of its own.
    report.add(Finding(
        "variable-mismatch", WARNING, "finding.variable_mismatch", {"language": "portuguese", "extra": "y"},
        place[0], 12, stage=TRANSLATIONS, language="portuguese"))
    report.merge_stages()
    assert [(f.cls, f.line) for f in report.findings] == [("bad-interpolation", 7), ("variable-mismatch", 12)]
    assert [other["class"] for other in report.findings[0].also] == ["variable-mismatch"]


@pytest.mark.req("TL-005", "ERR-010")
def test_many_untranslated_lines_are_added_quickly_and_still_merged():
    report = Report("0", "game")
    for _repeat in range(2):
        for language in ("french", "portuguese"):
            for line in range(5000):
                report.add(untranslated(line, language))
    assert len(report.findings) == 10000
    assert all(finding.count == 2 for finding in report.findings)
    # Merging still works after the list was replaced, as resolving possible issues does.
    report.drop_unconfirmed(set())
    report.findings = report.findings[:10]
    report.add(untranslated(3, "french"))
    assert len(report.findings) == 10
    assert report.findings[3].count == 3


@pytest.mark.req("TL-005", "TL-012", "REP-001")
def test_console_lists_a_few_untranslated_lines_for_each_language_and_counts_the_rest(tmp_path):
    i18n.set_language("en")
    report = Report("0", "game", complete=True)
    report.stages = {TRANSLATIONS: {"status": "done", "languages": {
        "french": {
            "switched": True, "dialogue": {"translated": 1, "total": 3}, "strings": {"translated": 0, "total": 0}},
        "portuguese": {
            "switched": True, "dialogue": {"translated": 0, "total": 25}, "strings": {"translated": 4, "total": 5}}}}}
    for line in range(1, 26):
        report.add(untranslated(line))
    for line in (1, 2):
        report.add(untranslated(line, "french"))

    stream = io.StringIO()
    Console(stream).summary(report, tmp_path / "report.json", failed=False)
    text = stream.getvalue()

    assert text.count("has no portuguese translation") == UNTRANSLATED_SHOWN
    assert text.count("has no french translation") == 2
    assert "... and 15 more with no portuguese translation" in text
    assert "more with no french translation" not in text
    assert "portuguese: 0 of 25 lines of dialogue and 4 of 5 other texts translated" in text
    assert "french: 1 of 3 lines of dialogue and 0 of 0 other texts translated" in text
    assert "0 errors, 27 warnings" in text
