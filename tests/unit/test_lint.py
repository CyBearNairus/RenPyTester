import pytest

from renpytester import lint
from renpytester.model import ERROR, INFO, WARNING, Finding, Report

# Reports as the engine writes them, trimmed. The first is from Ren'Py 8.6, the second from 8.0.
NEW_ENGINE = """﻿Ren'Py 8.6.0.25112108 lint report, generated at: Tue Oct  6 12:16:30 2026

game/script.rpy:17 'unknown_picture' is not an image.

game/script.rpy:19 One or more text tags were left open at the end of the string: 'b' (in "A {b}tag.")

game/script.rpy:23 'audio/missing_song.ogg' is not loadable

game/script.rpy:25 The jump is to nonexistent label 'label_that_does_not_exist'.

game/script.rpy:28 Could not evaluate 'nobody' in the who part of a say statement.
Perhaps you forgot to define a character?
It is advised to set config.check_conflicting_properties to True.

game/screens.rpy:40 Something lint says that this tool has never heard of.

game/zzz_renpytester_harness.rpy:3 A complaint about our own file.


Unreachable Statements:

game/testcases.rpy:
    * line     1
    * line    13

Orphan Translations:

game/tl/french/tutorial_quickstart.rpy:
    * line   108 (id tutorial_dialogue_3e6b0068)
    * line   156 (id tutorial_dialogue_3e6b0068_1)
    * and 1 more.
game/tl/japanese/tutorial_quickstart.rpy:
    * line   384 (id tutorial_images_672c8cb8)


Statistics:

The game contains 1,070 dialogue blocks, containing 15,946 words and 91,197
characters, for an average of 19.4 words and 111 characters per block.

The french translation contains 829 dialogue blocks, containing 17,587 words
and 109,843 characters, for an average of 21.2 words and 133 characters per
block.

The game contains 11 menus, 36 images, and 104 screens.


Lint is not a substitute for thorough testing. Remember to update Ren'Py
before releasing. New releases fix bugs and improve compatibility.
"""

OLD_ENGINE = """﻿Ren'Py 8.0.3.22090809 lint report, generated at: Tue Oct  6 12:16:32 2026

game/script.rpy:21 Text tag 'nosuchtag' is not known. (in "This {nosuchtag}tag{/nosuchtag}.")


Statistics:

The game contains 4 dialogue blocks, containing 27 words and 157 characters,
for an average of 6.8 words and 39 characters per block.

The game contains 0 menus, 1 images, and 0 screens.

Character statistics (for default language):

 * g has 3 blocks of dialogue.
"""


def by_line(findings):
    return {(f.file, f.line): f for f in findings}


@pytest.mark.req("LINT-001")
def test_problems_become_findings_with_file_line_and_severity():
    findings, _statistics = lint.parse(NEW_ENGINE)
    found = by_line(findings)
    expected = {
        17: ("undefined-image", ERROR), 19: ("bad-text", ERROR), 23: ("missing-file", ERROR),
        25: ("missing-label", ERROR), 28: ("undefined-name", ERROR)}
    for line, (cls, severity) in expected.items():
        finding = found[("game/script.rpy", line)]
        assert (finding.cls, finding.severity, finding.stage) == (cls, severity, "lint"), line
        assert finding.message_id == "finding.lint"


@pytest.mark.req("LINT-001", "I18N-005")
def test_lint_wording_is_kept_and_explanations_are_joined():
    findings, _statistics = lint.parse(NEW_ENGINE)
    message = by_line(findings)[("game/script.rpy", 28)].params["message"]
    assert message == (
        "Could not evaluate 'nobody' in the who part of a say statement. Perhaps you forgot to define a character?")


@pytest.mark.req("LINT-001")
def test_dialogue_quoted_by_lint_does_not_decide_the_kind_of_problem():
    message = "Text tag 'nosuchtag' is not known. (in \"This file does not exist and is not an image.\")"
    assert lint.classify(message) == ("bad-text", ERROR)


@pytest.mark.req("LINT-001")
def test_unknown_kind_of_problem_is_a_warning_not_an_error():
    findings, _statistics = lint.parse(NEW_ENGINE)
    finding = by_line(findings)[("game/screens.rpy", 40)]
    assert (finding.cls, finding.severity) == ("lint", WARNING)


@pytest.mark.req("NFR-004")
def test_complaints_about_our_own_file_are_dropped():
    findings, _statistics = lint.parse(NEW_ENGINE)
    assert not [f for f in findings if "zzz_renpytester" in f.file]


@pytest.mark.req("LINT-001", "TL-007", "ERR-007")
def test_sections_become_informational_findings():
    findings, _statistics = lint.parse(NEW_ENGINE)
    unreachable = [f for f in findings if f.cls == "unreachable"]
    assert [(f.file, f.line, f.severity) for f in unreachable] == [
        ("game/testcases.rpy", 1, INFO), ("game/testcases.rpy", 13, INFO)]

    orphans = [f for f in findings if f.cls == "orphan-translation"]
    assert [(f.file, f.line, f.language, f.params["id"]) for f in orphans] == [
        ("game/tl/french/tutorial_quickstart.rpy", 108, "french", "tutorial_dialogue_3e6b0068"),
        ("game/tl/french/tutorial_quickstart.rpy", 156, "french", "tutorial_dialogue_3e6b0068_1"),
        ("game/tl/japanese/tutorial_quickstart.rpy", 384, "japanese", "tutorial_images_672c8cb8")]
    assert all(f.severity == INFO for f in orphans)


@pytest.mark.req("LINT-003")
def test_statistics_are_read():
    _findings, statistics = lint.parse(NEW_ENGINE)
    assert statistics == {
        "dialogue": {"blocks": 1070, "words": 15946, "characters": 91197},
        "menus": 11, "images": 36, "screens": 104,
        "translations": {"french": {"blocks": 829, "words": 17587, "characters": 109843}}}


@pytest.mark.req("LINT-001", "COMPAT-002")
def test_report_from_the_oldest_engine_is_read():
    findings, statistics = lint.parse(OLD_ENGINE)
    assert [(f.file, f.line, f.cls) for f in findings] == [("game/script.rpy", 21, "bad-text")]
    assert statistics["dialogue"] == {"blocks": 4, "words": 27, "characters": 157}
    assert statistics["menus"] == 0


@pytest.mark.req("COMPAT-005")
def test_options_an_engine_rejects_are_recognised():
    output = "usage: renpy.py ...\nrenpy.py: error: unrecognized arguments: --all-problems --check-unclosed-tags\n"
    assert lint.unrecognised_options(output) == ["--all-problems", "--check-unclosed-tags"]
    assert lint.unrecognised_options("all fine") == []


@pytest.mark.req("LINT-002", "ERR-010")
def test_lint_finding_is_folded_into_the_crash_at_the_same_line():
    report = Report("0", "game")
    crash = report.add(Finding(
        "exception", ERROR, "finding.exception", {"type": "LabelNotFound", "message": "x"}, "game/script.rpy", 9,
        stage="routes", path=[{"choice": "Left"}]))
    report.add(Finding(
        "missing-label", ERROR, "finding.lint", {"message": "The jump is to nonexistent label 'x'."},
        "game/script.rpy", 9, stage="lint"))
    elsewhere = report.add(Finding(
        "missing-file", ERROR, "finding.lint", {"message": "'a.ogg' is not loadable"}, "game/script.rpy", 30,
        stage="lint"))
    note = report.add(Finding("unreachable", INFO, "finding.unreachable", {}, "game/script.rpy", 9, stage="lint"))

    report.merge_stages()

    assert report.findings == [crash, elsewhere, note]
    assert crash.also == [{
        "stage": "lint", "class": "missing-label", "message_id": "finding.lint",
        "params": {"message": "The jump is to nonexistent label 'x'."}}]
    assert crash.path == [{"choice": "Left"}]
