"""The configuration file and how it combines with the command line (spec 4.11)."""

import pytest

from renpytester import config, i18n
from renpytester.errors import UsageError
from renpytester.model import ERROR, INFO, WARNING, Finding, Report
from renpytester.runner import Options, build_options, load_baseline


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("en")


def write(tmp_path, text, name=config.FILE_NAME):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def finding(cls="exception", file="game/script.rpy", line=13, label="start", language=None, message="x"):
    return Finding(
        cls, ERROR, "finding.exception", {"type": "NameError", "message": message}, file, line, label, "routes",
        language)


@pytest.mark.req("CFG-001")
def test_no_config_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("RENPY_SDK", raising=False)
    assert config.find(tmp_path) is None
    empty = config.load(None)
    assert build_options("game", {}, empty) == Options(game="game")
    assert (empty.ignore, empty.severity, empty.inputs, empty.variables, empty.exclude_labels) == ([], {}, {}, {}, [])


@pytest.mark.req("CFG-002")
def test_config_file_is_found_in_the_game_folder_or_named(tmp_path):
    with pytest.raises(UsageError) as raised:
        config.find(tmp_path, tmp_path / "missing.toml")
    assert raised.value.message_id == "error.config_missing"

    in_game = write(tmp_path, "seed = 3\n")
    assert config.find(tmp_path) == in_game
    other = write(tmp_path, "seed = 4\n", "other.toml")
    assert config.find(tmp_path, other) == other.resolve()


@pytest.mark.req("CFG-002", "I18N-002")
def test_every_kind_of_setting_is_read(tmp_path):
    loaded = config.load(write(tmp_path, """
lang = "pt-BR"
sdk = "sdk"
output = "reports"
stages = ["routes", "lint"]
languages = ["french"]
strategy = "first"
labels = false
jobs = 2
seed = 7
timeout = 30
max_time = 12.5
fail_on = "warning"
exclude_labels = ["pong*"]

[severity]
untranslated = "error"

[inputs]
"Your name?" = "Ana"

[variables]
points = 10
"shop.open" = true

[[ignore]]
class = "untranslated"
language = "french"

[[ignore]]
file = "game/old/*"
message = "undefined_\\\\w+"
"""))
    assert loaded.lang == "pt-BR"
    assert loaded.settings["sdk"] == str((tmp_path / "sdk").resolve())
    assert loaded.settings["output"] == str((tmp_path / "reports").resolve())
    assert loaded.severity == {"untranslated": "error"}
    assert loaded.inputs == {"Your name?": "Ana"}
    assert loaded.variables == {"points": 10, "shop.open": True}
    assert loaded.exclude_labels == ["pong*"]
    assert [rule.to_dict() for rule in loaded.ignore] == [
        {"class": "untranslated", "language": "french"}, {"file": "game/old/*", "message": "undefined_\\w+"}]

    options = build_options("game", {}, loaded)
    assert options.stages == ("lint", "routes")
    assert (options.strategy, options.labels, options.jobs, options.seed) == ("first", False, 2, 7)
    assert (options.timeout, options.max_time, options.fail_on) == (30, 12.5, "warning")
    assert options.languages == ("french",)
    assert options.config == str(loaded.path)
    assert options.exclude_labels == ("pong*",)


@pytest.mark.req("CFG-002", "GAME-004")
def test_command_line_wins_over_the_file_and_the_file_over_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("RENPY_SDK", "from-environment")
    loaded = config.load(write(tmp_path, "seed = 7\nmax_paths = 20\nlabels = false\n"))
    options = build_options("game", {"seed": 9, "labels": None, "sdk": None}, loaded)
    assert (options.seed, options.max_paths, options.labels) == (9, 20, False)
    assert options.max_depth == Options(game="").max_depth
    # With no --sdk and none in the file, the environment says where the SDK is.
    assert options.sdk == "from-environment"
    assert build_options("game", {"sdk": "given"}, loaded).sdk == "given"


@pytest.mark.req("CFG-004", "CLI-003")
@pytest.mark.parametrize("text, message_id, key", [
    ("sed = 7\n", "error.config_unknown_key", "sed"),
    ("[run]\nseed = 7\n", "error.config_unknown_key", "run"),
    ("[[ignore]]\nclas = \"x\"\n", "error.config_unknown_key", "ignore[1].clas"),
    ("seed = \"seven\"\n", "error.config_bad_value", "seed"),
    ("jobs = 0\n", "error.config_bad_value", "jobs"),
    ("labels = \"no\"\n", "error.config_bad_value", "labels"),
    ("stages = \"routes\"\n", "error.config_bad_value", "stages"),
    ("fail_on = \"fatal\"\n", "error.config_bad_value", "fail_on"),
    ("lang = \"fr\"\n", "error.config_bad_value", "lang"),
    ("[severity]\nuntranslated = \"fatal\"\n", "error.config_bad_value", "severity"),
    ("[variables]\nwhen = 2026-10-06\n", "error.config_bad_value", "variables"),
    ("[[ignore]]\n", "error.config_bad_value", "ignore[1]"),
    ("[[ignore]]\nmessage = \"(\"\n", "error.config_bad_value", "ignore[1].message"),
    ("seed = \n", "error.config_unreadable", None),
])
def test_anything_wrong_in_the_file_is_an_error_that_names_it(tmp_path, text, message_id, key):
    with pytest.raises(UsageError) as raised:
        config.load(write(tmp_path, text))
    error = raised.value
    assert (error.exit_code, error.message_id) == (2, message_id)
    if key is not None:
        assert error.params["key"] == key
    # The message can be shown: every part it needs is there.
    assert "{" not in i18n.t(error.message_id, **error.params).replace("{ ", "")


@pytest.mark.req("CLI-002", "CLI-003")
def test_stages_and_jobs_are_checked_whichever_way_they_were_given(tmp_path):
    for given, loaded in (({"stages": ("routes", "x")}, config.load(None)),
                          ({}, config.load(write(tmp_path, "stages = [\"x\"]\n")))):
        with pytest.raises(UsageError) as raised:
            build_options("game", given, loaded)
        assert raised.value.message_id == "error.unknown_stage"
    with pytest.raises(UsageError) as raised:
        build_options("game", {"jobs": 0}, config.load(None))
    assert raised.value.message_id == "error.bad_jobs"


@pytest.mark.req("CFG-003")
def test_ignore_rule_matches_on_every_part_it_has():
    rule = config.Rule(cls="exception", file="game/tl/*/script.rpy", label="debug_*", language="french")
    matching = finding(file="game/tl/french/script.rpy", label="debug_room", language="french")
    assert rule.matches(matching)
    assert not rule.matches(finding(cls="hang", file=matching.file, label="debug_room", language="french"))
    assert not rule.matches(finding(file="game/script.rpy", label="debug_room", language="french"))
    assert not rule.matches(finding(file=matching.file, label="start", language="french"))
    assert not rule.matches(finding(file=matching.file, label="debug_room", language="spanish"))
    assert not rule.matches(finding(file=matching.file, label=None, language="french"))
    assert config.Rule(cls="exception").matches(finding())


@pytest.mark.req("CFG-003", "I18N-003")
def test_message_pattern_works_whatever_the_interface_language():
    english_words = config.Rule(message="^The game crashed here: NameError")
    portuguese_words = config.Rule(message="O jogo quebrou aqui")
    for language in i18n.LANGUAGES:
        i18n.set_language(language)
        assert english_words.matches(finding())
        assert portuguese_words.matches(finding())
        assert config.Rule(message="undefined_\\w+").matches(finding(message="name 'undefined_alpha' is not defined"))
        assert not config.Rule(message="no such words").matches(finding())


@pytest.mark.req("CFG-003")
def test_ignored_findings_are_counted_not_dropped():
    report = Report("0", "game")
    report.add(finding(line=1))
    report.add(finding(line=2, label="debug_room"))
    report.add(finding(line=3, label="debug_cellar"))
    rules = [config.Rule(label="debug_*"), config.Rule(cls="hang")]
    report.ignore(rules)
    assert [f.line for f in report.findings] == [1]
    data = report.to_dict()
    assert data["summary"]["ignored"] == 2
    assert data["ignored_by"] == [{"rule": {"label": "debug_*"}, "count": 2}, {"rule": {"class": "hang"}, "count": 0}]


@pytest.mark.req("TL-005", "CFG-007")
def test_severity_of_a_class_can_be_set(tmp_path):
    report = Report("0", "game")
    untranslated = Finding("untranslated", WARNING, "finding.untranslated_line", {"language": "french", "text": "Hi"})
    report.add(untranslated)
    report.add(finding())
    assert not report.failed(ERROR) or report.count(ERROR) == 1
    report.set_severities({"untranslated": "error", "exception": "info"})
    assert (report.count(ERROR), report.count(WARNING), report.count(INFO)) == (1, 0, 1)
    assert untranslated.severity == ERROR


@pytest.mark.req("REP-007")
def test_findings_the_baseline_already_has_are_left_out_and_counted(tmp_path):
    from renpytester.report import json_report

    earlier = Report("0", "game", name="earlier")
    earlier.add(finding(line=1))
    earlier.add(finding(line=2))
    known = load_baseline(json_report.write(earlier, tmp_path))
    assert len(known) == 2

    report = Report("0", "game")
    for line in (1, 2, 3):
        report.add(finding(line=line))
    assert report.to_dict()["summary"]["known"] is None
    report.leave_out_known(known)
    assert [f.line for f in report.findings] == [3]
    assert report.to_dict()["summary"]["known"] == 2
    assert report.failed(ERROR)


@pytest.mark.req("REP-007", "CLI-003")
def test_baseline_that_is_not_a_report_is_a_usage_error(tmp_path):
    for text in ("not json", "{}", "{\"findings\": [{}]}"):
        path = tmp_path / "baseline.json"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(UsageError) as raised:
            load_baseline(path)
        assert raised.value.message_id == "error.baseline_unreadable"
    with pytest.raises(UsageError):
        load_baseline(tmp_path / "missing.json")
