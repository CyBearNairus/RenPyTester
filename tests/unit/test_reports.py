"""The JUnit and HTML reports (spec REP-003, REP-004), made from the same data as the JSON report."""

import xml.etree.ElementTree as ElementTree
from html.parser import HTMLParser

import pytest

from renpytester import cli, i18n, report as reports
from renpytester.model import ERROR, INFO, WARNING, Finding, Report
from renpytester.report import html_report, junit_report

VOID = ("meta", "input", "br", "link")


class Page(HTMLParser):
    """Reads a page back: checks that tags are closed in order, and collects what a reader would see."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open = []
        self.text = []
        self.findings = []
        self.scripts = 0
        self.external = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in VOID:
            self.open.append(tag)
        if tag == "details":
            self.findings.append(attrs)
        if tag == "script":
            self.scripts += 1
        for name in ("src", "href"):
            if name in attrs:
                self.external.append(attrs[name])

    def handle_endtag(self, tag):
        assert self.open and self.open[-1] == tag, "closing %s inside %s" % (tag, self.open[-3:])
        self.open.pop()

    def handle_data(self, data):
        if self.open and self.open[-1] not in ("style", "script"):
            self.text.append(data)


def read_page(text):
    page = Page()
    page.feed(text)
    page.close()
    assert page.open == []
    return page, " ".join(" ".join(page.text).split())


@pytest.fixture
def data():
    i18n.set_language("en")
    report = Report(
        "0.9", "C:/games/demo", "project", settings={"seed": 7, "fail_on": "error", "stages": ["lint", "routes"]},
        complete=True, started="2026-10-06T10:00:00+00:00", finished="2026-10-06T10:00:12+00:00", name="report-demo")
    report.game = {"name": "Demo <Game>", "version": "1.0", "renpy_version": "8.6.0"}
    report.stages = {
        "lint": {"status": "done"}, "routes": {"status": "done", "paths": 3},
        "translations": {"status": "done", "languages": {"french": {
            "switched": False, "dialogue": {"translated": 8, "total": 10},
            "strings": {"translated": 1, "total": 2}}}},
        "screens": {"status": "not_implemented"}}
    report.coverage = {"executed": 9, "total": 12, "low_confidence": 2, "unreached_labels": ["attic"]}
    report.add(Finding(
        "exception", ERROR, "finding.exception", {"type": "NameError", "message": "<b>boom</b> & more"},
        "game/script.rpy", 13, "start", "routes", path=[{"kind": "menu", "choice": "Open <the> door", "index": 1}],
        traceback="Traceback:\n  File \"game/script.rpy\", line 13\x00\nNameError: <b>boom</b>",
        also=[{"stage": "lint", "class": "undefined-name", "message_id": "finding.lint", "params": {"message": "x"}}]))
    report.add(Finding(
        "untranslated", WARNING, "finding.untranslated_line", {"language": "french", "text": "Hello."},
        "game/script.rpy", 20, stage="translations", language="french"))
    report.add(Finding("unreachable", INFO, "finding.unreachable", {}, "game/extra.rpy", 5, stage="lint"))
    report.add(Finding(
        "exception", ERROR, "finding.exception", {"type": "KeyError", "message": "guess"}, "game/extra.rpy", 9,
        "attic", "routes", path=[{"kind": "label", "choice": "attic", "index": 0}], possible=True))
    report.notes.append({"message_id": "note.limited.max_time", "params": {"count": 4}})
    report.ignored = 3
    report.known = 2
    return report.to_dict()


def cases(xml):
    root = ElementTree.fromstring(xml.split("\n", 1)[1])
    found = {}
    for suite in root:
        for case in suite:
            kinds = [child.tag for child in case if child.tag in ("failure", "error", "skipped")]
            found[case.get("name")] = (suite.get("name"), kinds[0] if kinds else "passed", case)
    return root, found


@pytest.mark.req("REP-003", "EXP-013", "I18N-003")
def test_junit_has_a_failed_test_for_each_finding_that_fails_the_run(data):
    root, found = cases(junit_report.render(data))
    assert [suite.get("name") for suite in root] == [
        "renpytester.lint", "renpytester.routes", "renpytester.translations"]
    assert (root.get("tests"), root.get("failures"), root.get("errors"), root.get("skipped")) == ("7", "1", "0", "3")
    assert root.get("time") == "12.000"

    outcomes = {name.split(" [")[0]: (suite, kind) for name, (suite, kind, _case) in found.items()}
    assert outcomes == {
        "stage lint": ("renpytester.lint", "passed"), "stage routes": ("renpytester.routes", "passed"),
        "stage translations": ("renpytester.translations", "passed"),
        "exception game/script.rpy:13": ("renpytester.routes", "failure"),
        # Below the threshold, or only a possible issue: listed, but the build does not fail for it.
        "untranslated game/script.rpy:20": ("renpytester.translations", "skipped"),
        "unreachable game/extra.rpy:5": ("renpytester.lint", "skipped"),
        "exception game/extra.rpy:9": ("renpytester.routes", "skipped")}

    crash = next(case for name, (_suite, kind, case) in found.items() if kind == "failure")
    failure = crash.find("failure")
    assert failure.get("type") == "exception"
    assert failure.get("message") == "The game crashed here: NameError: <b>boom</b> & more"
    assert "choices made: Open <the> door" in failure.text
    assert "also reported by lint" in failure.text
    # A character XML cannot hold, from the traceback, does not break the file.
    assert "line 13?" in failure.text
    properties = {p.get("name"): p.get("value") for p in crash.find("properties")}
    assert properties == {"id": data["findings"][0]["id"], "severity": "error", "possible": "false"}

    guess = next(case for name, (_s, _k, case) in found.items() if name.startswith("exception game/extra.rpy:9"))
    assert guess.find("skipped").get("message").startswith("possible: ")
    assert {p.get("name"): p.get("value") for p in guess.find("properties")}["possible"] == "true"

    # Names are the same in every interface language; messages are not.
    i18n.set_language("pt-BR")
    _root, translated = cases(junit_report.render(data))
    i18n.set_language("en")
    assert set(translated) == set(found)
    assert translated[crash.get("name")][2].find("failure").get("message").startswith("O jogo quebrou aqui")


@pytest.mark.req("REP-003", "CLI-004", "EXP-013")
def test_junit_follows_the_failure_threshold(data):
    data["settings"].update(fail_on="warning", fail_on_possible=True)
    root, _found = cases(junit_report.render(data))
    assert (root.get("failures"), root.get("skipped")) == ("3", "1")
    data["settings"].update(fail_on="never")
    root, _found = cases(junit_report.render(data))
    assert (root.get("failures"), root.get("skipped")) == ("0", "4")


@pytest.mark.req("REP-003", "NFR-002")
def test_junit_shows_a_stage_that_did_not_finish_as_an_error(data):
    data["complete"] = False
    data["stages"]["routes"] = {"status": "interrupted"}
    data["stages"]["lint"] = {"status": "failed", "reason": "timeout"}
    data["stages"]["translations"] = {"status": "not_selected"}
    root, found = cases(junit_report.render(data))
    assert [suite.get("name") for suite in root] == ["renpytester.lint", "renpytester.routes"]
    assert found["stage routes"][1] == "error"
    assert found["stage lint"][1] == "error"
    assert found["stage lint"][2].find("error").text == "timeout"
    assert root.get("errors") == "2"
    # The untranslated line belongs to a stage that has no suite now; nothing else is lost.
    assert root.get("tests") == "5"


@pytest.mark.req("REP-004", "EXP-013", "TL-012")
def test_html_report_has_the_summary_then_findings_by_file_then_possible_issues(data):
    text = html_report.render(data)
    page, words = read_page(text)

    assert text.startswith("<!DOCTYPE html>")
    # One file, nothing fetched from anywhere (REP-004).
    assert page.external == []
    assert page.scripts == 1
    assert "http://" not in text and "https://" not in text

    order = [words.index(part) for part in (
        "Demo <Game> 1.0", "FAILED", "1 errors", "75%", "Translations", "french 8 of 10 1 of 2 no 1",
        "Worth knowing", "Problems found (3)", "game/extra.rpy (1)", "game/script.rpy (2)",
        "line 13 The game crashed here: NameError: <b>boom</b> & more", "Possible issues (1)",
        "The game crashed here: KeyError: guess")]
    assert order == sorted(order)

    for part in (
            "Exploration stopped at the time limit. 4 branches were not explored.", "3 problems were left out by",
            "2 problems that the baseline report already had", "Labels never reached (1): attic",
            "Not checked in this version: screens", "Choices that lead here: Open <the> door",
            "Also reported by lint", "started at label attic", "Seed: 7"):
        assert part in words, part

    # Each finding is one line that opens, and can be filtered by severity, stage and language.
    assert [(f["data-severity"], f["data-stage"], f["data-language"]) for f in page.findings] == [
        ("info", "lint", ""), ("error", "routes", ""), ("warning", "translations", "french"), ("error", "routes", "")]
    assert all("open" not in f for f in page.findings)
    for control in ('value="error" checked', 'value="warning" checked', 'value="info" checked',
                    'id="filter-stage"', 'id="filter-language"', '<option value="french">'):
        assert control in text, control


@pytest.mark.req("REP-004", "I18N-005")
def test_html_report_shows_what_the_game_wrote_without_running_it(data):
    text = html_report.render(data)
    assert "<b>boom</b>" not in text
    assert "&lt;b&gt;boom&lt;/b&gt; &amp; more" in text
    assert "Demo &lt;Game&gt;" in text
    assert "Open &lt;the&gt; door" in text


@pytest.mark.req("REP-004", "I18N-001", "I18N-004")
def test_html_report_is_written_in_the_interface_language(data):
    i18n.set_language("pt-BR")
    text = html_report.render(data)
    i18n.set_language("en")
    _page, words = read_page(text)
    assert '<html lang="pt-BR">' in text
    for part in ("FALHOU", "Problemas encontrados (3)", "O jogo quebrou aqui: NameError", "Traduções",
                 "Possíveis problemas (1)", "Escolhas que levam até aqui:"):
        assert part in words, part


@pytest.mark.req("REP-004", "NFR-002")
def test_html_report_of_a_clean_or_unfinished_run_says_so(data):
    data["findings"] = []
    data["summary"].update(error=0, warning=0, info=0, possible=0)
    _page, words = read_page(html_report.render(data))
    assert "PASSED" in words and "No problems were found." in words
    assert "Show:" not in words

    data["complete"] = False
    data["stages"]["routes"]["status"] = "interrupted"
    _page, words = read_page(html_report.render(data))
    assert "INCOMPLETE" in words
    assert "Not finished, so not fully checked: routes (interrupted)" in words


@pytest.mark.req("REP-002", "REP-003", "REP-004", "REP-009")
def test_every_format_is_written_under_the_same_name(tmp_path):
    report = Report("0", "game", name="report-demo-2026-10-06-120000", complete=True)
    paths = reports.write_all(report, tmp_path / "out")
    assert {kind: path.name for kind, path in paths.items()} == {
        "json": "report-demo-2026-10-06-120000.json", "html": "report-demo-2026-10-06-120000.html",
        "junit": "report-demo-2026-10-06-120000.xml"}
    assert all(path.is_file() for path in paths.values())


@pytest.mark.req("CLI-005")
def test_help_documents_every_option_with_its_default(capsys):
    i18n.set_language("en")
    parser = cli.build_parser()
    for action in parser._actions:
        assert action.help, action.dest
    text = " ".join(parser.format_help().split())
    for option in (
            "--sdk", "--config", "--output", "--baseline", "--stages", "--strategy", "--languages", "--no-labels",
            "--jobs", "--max-paths", "--max-time", "--max-depth", "--seed", "--timeout", "--input-value",
            "--max-steps", "--fail-on", "--fail-on-possible", "--show-window", "--lang", "--version"):
        assert option in text, option
    for default in (
            "(default: renpytester-report)", "(default: lint,routes,translations)", "(default: explore)",
            "(default: 5000)", "(default: 600)", "(default: 500)", "(default: 0)", "(default: 60)",
            "(default: Tester)", "(default: 200000)", "(default: error)"):
        # The help is wrapped to the width of the terminal, sometimes in the middle of a hyphenated word.
        assert default.replace(" ", "") in text.replace(" ", ""), default
    assert "renpytester.toml" in text and "renpytester info GAME" in text

    with pytest.raises(SystemExit) as stopped:
        cli.main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.startswith("renpytester ")
