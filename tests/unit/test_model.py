import json

import pytest

from renpytester import i18n
from renpytester.model import ERROR, INFO, SCHEMA_VERSION, WARNING, Finding, Report
from renpytester.report import json_report
from renpytester.runner import load_failure, parse_errors


def crash(line=13, path=()):
    return Finding(
        "exception", ERROR, "finding.exception", {"type": "NameError", "message": "x"}, "game/script.rpy", line,
        "start", "routes", path=list(path))


@pytest.mark.req("ERR-010")
def test_same_problem_is_reported_once_with_the_shortest_path():
    report = Report("0", "game")
    report.add(crash(path=[{"choice": "a"}, {"choice": "b"}]))
    report.add(crash(path=[{"choice": "c"}]))
    report.add(crash(line=20))
    assert len(report.findings) == 2
    assert report.findings[0].count == 2
    assert report.findings[0].path == [{"choice": "c"}]


@pytest.mark.req("CLI-003", "CLI-004")
def test_failure_threshold():
    report = Report("0", "game")
    assert not report.failed(ERROR)
    report.add(Finding("stuck", WARNING, "finding.stuck"))
    assert not report.failed(ERROR)
    assert report.failed(WARNING)
    assert report.failed(INFO)
    assert not report.failed("never")
    report.add(crash())
    assert report.failed(ERROR)
    assert not report.failed("never")


@pytest.mark.req("REP-002", "I18N-003", "I18N-004")
def test_json_report_is_complete_and_language_neutral(tmp_path):
    def written(language):
        i18n.set_language(language)
        report = Report("0.1.0", "game", "project", settings={"seed": 7}, complete=True)
        report.add(crash(path=[{"kind": "menu", "choice": "Left", "index": 0}]))
        return json_report.write(report, tmp_path / language).read_text(encoding="utf-8")

    english, portuguese = written("en"), written("pt-BR")
    i18n.set_language("en")
    assert english == portuguese

    data = json.loads(english)
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["settings"]["seed"] == 7
    assert data["summary"] == {"error": 1, "warning": 0, "info": 0}
    finding = data["findings"][0]
    expected = (
        "id", "class", "severity", "message_id", "params", "file", "line", "label", "stage", "language", "path",
        "traceback", "count")
    assert set(finding) == set(expected)
    assert i18n.t(finding["message_id"], **finding["params"]).startswith("The game crashed here")
    assert i18n.t(finding["message_id"], "pt-BR", **finding["params"]).startswith("O jogo quebrou aqui")


@pytest.mark.req("ERR-001")
def test_engine_parse_errors_become_findings():
    text = (
        "﻿I'm sorry, but errors were detected in your script.\n\n"
        'File "game/script.rpy", line 8: expected \':\' not found.\n    menu\n        ^\n\n'
        'File "game/other.rpy", line 3: unknown statement\n')
    findings = parse_errors(text, "routes")
    assert [(f.file, f.line) for f in findings] == [("game/script.rpy", 8), ("game/other.rpy", 3)]
    assert findings[0].params == {"message": "expected ':' not found."}
    assert all(f.cls == "parse-error" and f.severity == ERROR for f in findings)


@pytest.mark.req("ERR-001")
def test_startup_traceback_becomes_a_finding():
    text = (
        'Traceback:\n  File "renpy/main.py", line 1, in x\n  File "game/options.rpy", line 12, in <module>\n'
        "NameError: name 'oops' is not defined\n")
    finding = load_failure(text, "routes")
    assert (finding.file, finding.line) == ("game/options.rpy", 12)
    assert finding.params["message"] == "NameError: name 'oops' is not defined"
