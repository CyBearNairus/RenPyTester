"""End-to-end tests: the real command line, a real engine, the fixture games (spec 7.2)."""

import json

import pytest

from renpytester import cli
from tests.conftest import folder_digest

pytestmark = pytest.mark.e2e


@pytest.fixture
def run(sdk, game_copy, tmp_path, capsys):
    """Runs the command line on a copy of a fixture game. Returns (exit code, report, console text, game path)."""

    def run(name, *extra):
        game = game_copy(name)
        before = folder_digest(game)
        output = tmp_path / "report"
        # One game process unless the test says otherwise, so that results do not depend on the machine.
        jobs = [] if "--jobs" in extra else ["--jobs", "1"]
        code = cli.main([str(game), "--sdk", str(sdk), "--output", str(output), "--lang", "en", *jobs, *extra])
        text = capsys.readouterr().out
        assert folder_digest(game) == before, "the game folder was changed by the run"
        assert sorted(p.name for p in (game / "game").iterdir()) == ["script.rpy"]
        files = sorted(output.glob("report-*.json"), key=lambda p: p.stat().st_mtime_ns)
        report = json.loads(files[-1].read_text(encoding="utf-8")) if files else None
        return code, report, text, game

    return run


@pytest.mark.req(
    "CLI-001", "CLI-003", "GAME-004", "GAME-006", "GAME-007", "RUN-001", "RUN-002", "RUN-004", "RUN-007", "SAFE-001",
    "SAFE-002", "SAFE-004", "SAFE-013", "NFR-003")
def test_clean_game_passes(run):
    code, report, text, _game = run("clean")
    assert code == 0
    assert report["complete"] is True
    assert report["findings"] == []
    assert report["game"]["name"] == "Clean Fixture"
    assert report["game"]["version"] == "1.0"
    assert report["game"]["kind"] == "project"
    assert report["game"]["renpy_version"].startswith("8.")
    assert report["stages"]["routes"] == {
        "status": "done", "paths": 2, "end_reasons": {"end": 2}, "launches": 1, "jobs": 1, "label_runs": 0,
        "possible_dropped": 0}
    # Everything except the menu choice whose condition is never true.
    assert report["coverage"]["total"] - report["coverage"]["executed"] == 1
    assert "PASSED" in text
    assert "Clean Fixture" in text


@pytest.mark.req("RUN-003", "RUN-005", "EXP-004", "EXP-006")
def test_decisions_are_made_and_recorded(run, tmp_path):
    code, report, _text, _game = run("exception_after_choices", "--input-value", "A very long name indeed")
    assert code == 1
    path = report["findings"][0]["path"]
    assert [(step["kind"], step["choice"]) for step in path] == [("input", "A very long"), ("menu", "Left")]
    assert path[1]["index"] == 0
    assert (path[1]["file"], path[1]["line"]) == ("game/script.rpy", 12)


@pytest.mark.req("ERR-002", "RUN-011", "REP-001", "REP-006", "CLI-003")
def test_exception_is_reported_where_it_happened(run):
    code, report, text, _game = run("exception")
    assert code == 1
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["class"] == "exception"
    assert finding["severity"] == "error"
    assert (finding["file"], finding["line"], finding["label"]) == ("game/script.rpy", 13, "chapter_two")
    assert finding["params"] == {"type": "NameError", "message": "name 'undefined_function' is not defined"}
    assert "undefined_function" in finding["traceback"]
    assert finding["stage"] == "routes"
    assert "game/script.rpy:13" in text
    assert "FAILED" in text


@pytest.mark.req("ERR-002")
def test_jump_to_a_missing_label_is_reported(run):
    code, report, _text, _game = run("bad_jump")
    assert code == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["file"], finding["line"]) == ("exception", "game/script.rpy", 8)
    assert "no_such_label" in finding["params"]["message"]


@pytest.mark.req("ERR-001", "REP-008")
def test_script_that_does_not_parse_is_reported(run, tmp_path):
    code, report, _text, _game = run("parse_error")
    assert code == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["file"], finding["line"]) == ("parse-error", "game/script.rpy", 8)
    assert report["stages"]["routes"]["status"] == "blocked"
    assert len(list((tmp_path / "report").glob("report-parse-error-*-logs/errors.txt"))) == 1


@pytest.mark.req("RUN-008", "ERR-006")
def test_game_that_stops_making_progress_is_shut_down(run):
    code, report, _text, _game = run("hang", "--timeout", "3")
    assert code == 1
    finding = report["findings"][0]
    assert finding["class"] == "hang"
    assert finding["params"] == {"seconds": 3}


@pytest.mark.req("RUN-009", "ERR-006")
def test_endless_loop_ends_the_path_with_a_warning(run):
    code, report, _text, _game = run("loop", "--max-steps", "500")
    assert code == 0
    finding = report["findings"][0]
    assert (finding["class"], finding["severity"]) == ("loop", "warning")
    assert report["stages"]["routes"]["end_reasons"] == {"loop": 1}


@pytest.mark.req("RUN-007")
def test_game_that_quits_itself_is_a_normal_ending(run):
    code, report, _text, _game = run("quits")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["routes"]["end_reasons"] == {"quit": 1}


@pytest.mark.req("ERR-011")
def test_exception_the_game_catches_itself_is_not_reported(run):
    code, report, _text, _game = run("caught_exception")
    assert code == 0
    assert report["findings"] == []


@pytest.mark.req("RUN-010", "NFR-001")
def test_same_seed_gives_the_same_report(run):
    def essentials(report):
        return json.dumps([report["findings"], report["coverage"], report["statistics"]], sort_keys=True)

    _code, first, _text, _game = run("random", "--seed", "42")
    _code, second, _text, _game = run("random", "--seed", "42")
    assert essentials(first) == essentials(second)
    assert first["settings"]["seed"] == 42


@pytest.mark.req("I18N-001", "CLI-010")
def test_console_output_in_portuguese(sdk, game_copy, tmp_path, capsys):
    game = game_copy("exception")
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "pt-BR"])
    text = capsys.readouterr().out
    assert code == 1
    assert "O jogo quebrou aqui" in text
    assert "FALHOU" in text


@pytest.mark.req("GAME-005", "CLI-003")
def test_project_without_an_engine_exits_3(game_copy, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("RENPY_SDK", raising=False)
    game = game_copy("clean")
    code = cli.main([str(game), "--output", str(tmp_path / "report"), "--lang", "en"])
    assert code == 3
    assert "--sdk" in capsys.readouterr().out
    assert sorted(p.name for p in (game / "game").iterdir()) == ["script.rpy"]


@pytest.mark.req("REP-005")
def test_report_folder_inside_the_game_is_refused(sdk, game_copy, capsys):
    game = game_copy("clean")
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(game / "report"), "--lang", "en"])
    assert code == 3
    assert not (game / "report").exists()


@pytest.mark.req("NFR-003", "COMPAT-002", "ARCH-004")
@pytest.mark.parametrize("name", ["the_question", "tutorial"])
def test_reference_games_report_no_errors(sdk, tmp_path, capsys, name):
    import shutil

    game = tmp_path / name
    shutil.copytree(sdk / name, game)
    before = folder_digest(game)
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en"])
    capsys.readouterr()
    report = json.loads(next((tmp_path / "report").glob("report-*.json")).read_text(encoding="utf-8"))
    assert code == 0
    assert report["summary"]["error"] == 0
    assert report["game"]["languages"]
    assert report["stages"]["routes"]["paths"] > 1
    coverage = report["coverage"]
    if name == "the_question":
        assert coverage["total"] - coverage["executed"] <= 1
    else:
        assert coverage["executed"] / coverage["total"] > 0.9
    assert folder_digest(game) == before


@pytest.mark.req("LINT-001", "ERR-003", "ERR-004", "ERR-005", "CLI-002")
def test_lint_finds_problems_the_story_never_reaches(run):
    code, report, text, _game = run("lint_problems", "--no-labels")
    assert code == 1
    found = {(f["line"], f["class"]) for f in report["findings"]}
    assert found == {
        (17, "undefined-image"), (19, "bad-text"), (21, "bad-text"), (23, "missing-file"), (25, "missing-label"),
        (28, "undefined-name")}
    assert all(f["stage"] == "lint" and f["severity"] == "error" for f in report["findings"])
    assert all(f["file"] == "game/script.rpy" for f in report["findings"])
    assert report["stages"]["lint"]["status"] == "done"
    assert "game/script.rpy:17" in text


@pytest.mark.req("LINT-003")
def test_lint_statistics_are_in_the_report(run):
    _code, report, text, _game = run("lint_problems")
    script = report["statistics"]["script"]
    assert script["dialogue"] == {"blocks": 4, "words": 27, "characters": 157}
    assert (script["menus"], script["images"], script["screens"]) == (0, 1, 0)
    assert "27 words" in text


@pytest.mark.req("LINT-002", "ERR-010")
def test_mistake_found_by_lint_and_by_playing_is_reported_once(run):
    code, report, text, _game = run("missing_label")
    assert code == 1
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["stage"], finding["class"], finding["line"]) == ("routes", "exception", 8)
    assert [(other["stage"], other["class"]) for other in finding["also"]] == [("lint", "missing-label")]
    assert "also reported by lint" in text


@pytest.mark.req("CLI-002")
def test_stages_can_be_selected(run):
    code, report, _text, _game = run("lint_problems", "--stages", "routes", "--no-labels")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["lint"]["status"] == "not_selected"
    assert report["settings"]["stages"] == ["routes"]

    code, report, _text, _game = run("exception", "--stages", "lint")
    assert code == 0
    assert report["stages"]["routes"]["status"] == "not_selected"
    assert report["coverage"] is None


@pytest.mark.req("CLI-002", "CLI-003")
def test_unknown_stage_is_a_usage_error(sdk, game_copy, tmp_path, capsys):
    game = game_copy("clean")
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(tmp_path / "r"), "--lang", "en", "--stages", "x"])
    assert code == 2
    assert "Unknown stage: x" in capsys.readouterr().out


@pytest.mark.req("REP-009", "REP-005")
def test_reports_are_named_after_the_game_and_never_overwritten(sdk, game_copy, tmp_path, capsys):
    import re
    import time

    output = tmp_path / "reports"
    for name in ("clean", "exception", "clean"):
        game = game_copy(name)
        cli.main([str(game), "--sdk", str(sdk), "--output", str(output), "--lang", "en", "--stages", "routes"])
        time.sleep(1.1)
    text = capsys.readouterr().out

    reports = sorted(p.name for p in output.glob("*.json"))
    assert len(reports) == 3
    assert len([n for n in reports if n.startswith("report-clean-fixture-")]) == 2
    assert len([n for n in reports if n.startswith("report-exception-fixture-")]) == 1
    assert all(re.fullmatch(r"report-[a-z0-9-]+-\d{4}-\d{2}-\d{2}-\d{6}\.json", n) for n in reports)
    for name in reports:
        assert name in text
        assert (output / name.replace(".json", "-logs")).is_dir()
    assert not (output / "engine-logs").exists()


def choices(finding):
    return [step["choice"] for step in finding["path"]]


@pytest.mark.req("EXP-001", "EXP-002", "EXP-004", "EXP-005")
def test_crash_behind_two_choices_is_found_with_its_path(run):
    code, report, text, _game = run("branches")
    assert code == 1
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["line"]) == ("exception", 20)
    assert choices(finding) == ["Right", "Second"]
    assert report["stages"]["routes"]["paths"] == 3
    assert report["stages"]["routes"]["end_reasons"] == {"end": 2, "exception": 1}
    coverage = report["coverage"]
    assert coverage["executed"] == coverage["total"]
    assert coverage["files"] == {"game/script.rpy": [coverage["total"], coverage["total"]]}
    assert coverage["labels"]["start"]["executed"] == coverage["labels"]["start"]["total"]
    assert coverage["unreached_labels"] == []
    assert "Right > Second" in text


@pytest.mark.req("RUN-011")
def test_every_crash_is_found_in_one_run(run):
    code, report, _text, _game = run("two_bugs")
    assert code == 1
    found = sorted((choices(f), f["params"]["message"]) for f in report["findings"])
    assert found == [
        (["Alpha"], "name 'undefined_alpha' is not defined"), (["Beta"], "name 'undefined_beta' is not defined")]
    assert report["stages"]["routes"]["end_reasons"] == {"end": 1, "exception": 2}


@pytest.mark.req("EXP-002")
def test_branches_do_not_see_each_others_state(run):
    code, report, _text, _game = run("stateful")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["routes"]["paths"] == 2


@pytest.mark.req("EXP-001", "EXP-006")
def test_hub_menu_is_covered_without_looping(run):
    code, report, _text, _game = run("hub")
    assert code == 0
    assert report["findings"] == []
    coverage = report["coverage"]
    assert coverage["executed"] == coverage["total"]
    # The story takes four paths, and the label run that starts at the hub takes the same four.
    assert report["stages"]["routes"]["paths"] <= 8


@pytest.mark.req("EXP-006")
def test_first_strategy_plays_a_single_path(run):
    code, report, _text, _game = run("branches", "--strategy", "first")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["routes"]["paths"] == 1
    assert report["coverage"]["executed"] < report["coverage"]["total"]


@pytest.mark.req("EXP-003")
def test_path_limit_stops_exploration_and_says_so(run):
    code, report, text, _game = run("branches", "--max-paths", "1")
    assert code == 0
    routes = report["stages"]["routes"]
    assert routes["paths"] == 1
    assert routes["limited"] == {"kind": "max_paths", "unexplored": 1, "labels": 0}
    assert report["coverage"]["executed"] < report["coverage"]["total"]
    assert "--max-paths" in text
    assert report["settings"]["max_paths"] == 1


@pytest.mark.req("EXP-003")
def test_depth_limit_stops_branching_but_not_playing(run):
    code, report, _text, _game = run("branches", "--max-depth", "1")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["routes"]["paths"] == 2


@pytest.mark.req("RUN-012", "ERR-006")
def test_engine_crash_on_one_branch_does_not_stop_the_others(run):
    code, report, _text, _game = run("crash_branch")
    assert code == 1
    found = {f["class"]: f for f in report["findings"]}
    assert set(found) == {"engine-crash", "exception"}
    assert choices(found["engine-crash"]) == ["Trapdoor"]
    assert found["engine-crash"]["params"] == {"code": 7}
    assert choices(found["exception"]) == ["Broken door"]
    routes = report["stages"]["routes"]
    assert routes["launches"] == 2
    assert routes["end_reasons"] == {"end": 1, "engine-crash": 1, "exception": 1}
    # Everything except the statement that killed the engine, which never got to report itself.
    assert report["coverage"]["total"] - report["coverage"]["executed"] == 1


@pytest.mark.req("RUN-008", "RUN-012", "ERR-006")
def test_hang_on_one_branch_does_not_stop_the_others(run):
    code, report, _text, _game = run("hang_branch", "--timeout", "3")
    assert code == 1
    found = {f["class"]: f for f in report["findings"]}
    assert set(found) == {"hang", "exception"}
    assert choices(found["hang"]) == ["Endless corridor"]
    assert choices(found["exception"]) == ["Broken door"]
    assert report["stages"]["routes"]["launches"] == 2


def by_line(report):
    return sorted((f["line"], f["class"]) for f in report["findings"])


@pytest.mark.req("ERR-004", "ARCH-007")
def test_undefined_image_is_found_by_playing(run):
    code, report, text, _game = run("undefined_image", "--stages", "routes")
    assert code == 1
    assert by_line(report) == [(12, "undefined-image")]
    finding = report["findings"][0]
    assert finding["params"] == {"name": "stranger smiling"}
    assert (finding["stage"], finding["severity"], finding["label"]) == ("routes", "error", "start")
    assert report["stages"]["routes"]["end_reasons"] == {"end": 1}
    assert "stranger smiling" in text


@pytest.mark.req("ERR-003", "ARCH-007")
def test_missing_image_file_is_found_by_playing(run):
    code, report, _text, _game = run("missing_image_file", "--stages", "routes")
    assert code == 1
    assert by_line(report) == [(10, "missing-file")]
    assert report["findings"][0]["params"] == {"file": "images/room_that_was_deleted.png"}
    assert report["coverage"]["executed"] == report["coverage"]["total"]


@pytest.mark.req("ERR-003", "ARCH-007")
def test_missing_audio_files_are_found_by_playing(run):
    code, report, _text, _game = run("missing_audio", "--stages", "routes")
    assert code == 1
    found = sorted((f["line"], f["class"], f["params"]["file"]) for f in report["findings"])
    assert found == [
        (8, "missing-file", "audio/theme_that_was_renamed.ogg"),
        (12, "missing-file", "audio/click_that_was_deleted.ogg")]
    assert report["stages"]["routes"]["end_reasons"] == {"end": 1}


@pytest.mark.req("ERR-005", "ARCH-007")
def test_bad_text_tags_are_found_by_playing(run):
    code, report, _text, _game = run("bad_text", "--stages", "routes")
    assert code == 1
    assert by_line(report) == [(10, "bad-text"), (12, "bad-text"), (14, "bad-text"), (14, "bad-text")]
    texts = sorted(f["params"]["text"] for f in report["findings"])
    assert texts == [
        "First {colour=#f00}choice{/colour}", "Pick {b}one.", "This tag is {i}never closed.",
        "This tag is {wobble}not a real one{/wobble}."]
    assert all(f["params"]["problem"] for f in report["findings"])


@pytest.mark.req("ERR-008")
def test_menu_with_nothing_to_choose_is_reported(run):
    code, report, _text, _game = run("no_choice", "--stages", "routes")
    assert code == 1
    assert by_line(report) == [(11, "no-choice")]


@pytest.mark.req("ERR-012", "NFR-003")
def test_need_for_a_real_screen_is_a_note_not_an_error(run):
    code, report, _text, _game = run("needs_display", "--stages", "routes")
    assert code == 0
    assert by_line(report) == [(8, "needs-display")]
    assert report["findings"][0]["severity"] == "info"


@pytest.mark.req("LINT-002", "ERR-010")
def test_asset_problem_found_by_lint_and_by_playing_is_reported_once(run):
    code, report, _text, _game = run("undefined_image")
    assert code == 1
    assert by_line(report) == [(12, "undefined-image")]
    finding = report["findings"][0]
    assert finding["stage"] == "routes"
    assert [other["stage"] for other in finding["also"]] == ["lint"]


@pytest.mark.req("RUN-017", "RUN-019", "RUN-021", "EXP-013", "EXP-014")
def test_minigame_is_skipped_and_each_outcome_the_script_checks_is_tried(run):
    code, report, text, _game = run("minigame", "--stages", "routes")
    assert code == 0
    found = {f["class"]: f for f in report["findings"]}
    assert set(found) == {"stuck", "exception"}

    skipped = found["stuck"]
    assert (skipped["line"], skipped["severity"], skipped["possible"]) == (11, "info", False)

    crash = found["exception"]
    assert (crash["line"], crash["possible"]) == (18, True)
    assert [(step["kind"], step["choice"]) for step in crash["path"]] == [("skip", "result = 'failed'")]

    assert report["summary"] == {"error": 0, "warning": 0, "info": 1, "possible": 1}
    assert report["stages"]["routes"]["paths"] == 3
    coverage = report["coverage"]
    assert coverage["executed"] + coverage["low_confidence"] == coverage["total"]
    assert coverage["low_confidence"] > 0
    assert "Possible issues (1)" in text
    assert "PASSED" in text


@pytest.mark.req("EXP-013", "CLI-003")
def test_possible_issues_fail_the_run_only_when_asked(run):
    code, _report, _text, _game = run("minigame", "--stages", "routes", "--fail-on-possible")
    assert code == 1


@pytest.mark.req("RUN-020")
def test_minigame_with_nothing_to_infer_tries_each_place_the_script_goes(run):
    code, report, _text, _game = run("minigame_score", "--stages", "routes")
    assert code == 0
    assert report["coverage"]["unreached_labels"] == []
    labels = report["coverage"]["labels"]
    assert labels["victory"]["low_confidence"] == labels["victory"]["total"]
    assert labels["defeat"]["low_confidence"] == labels["defeat"]["total"]
    assert report["summary"]["possible"] == 0


def steps(finding):
    return [(step["kind"], step["choice"]) for step in finding["path"]]


@pytest.mark.req("EXP-007", "EXP-012", "EXP-013", "EXP-014", "EXP-019", "EXP-020")
def test_labels_the_story_never_reaches_are_played_by_themselves(run):
    code, report, text, _game = run("labels", "--stages", "routes")
    assert code == 1
    found = {f["line"]: f for f in report["findings"]}
    assert sorted(found) == [31, 40]

    # Reached by playing and by its own label run: one confirmed finding.
    assert (found[40]["possible"], found[40]["count"], found[40]["path"]) == (False, 2, [])
    # Only reachable by starting at its label: a possible issue, with the way there.
    assert found[31]["possible"] is True
    assert steps(found[31]) == [("label", "secret"), ("menu", "Open the box")]

    routes = report["stages"]["routes"]
    # Every label but the story's own start and the one that needs an argument.
    assert routes["label_runs"] == 4
    # "chapter" fails when started by itself, but the story plays it without trouble.
    assert routes["possible_dropped"] == 1
    # A label run stops where its label hands over to another.
    assert routes["end_reasons"] == {"end": 1, "exception": 4, "label end": 1}

    coverage = report["coverage"]
    assert coverage["unreached_labels"] == []
    assert coverage["labels"]["secret"]["executed"] == 0
    assert coverage["labels"]["secret"]["low_confidence"] == coverage["labels"]["secret"]["total"]
    assert coverage["labels"]["ending"]["low_confidence"] == coverage["labels"]["ending"]["total"]
    # All but the jump whose condition is never true and the return after the line that fails.
    assert coverage["executed"] + coverage["low_confidence"] == coverage["total"] - 2
    assert "started at label secret > Open the box" in text


@pytest.mark.req("EXP-007")
def test_label_runs_can_be_turned_off(run):
    code, report, _text, _game = run("labels", "--stages", "routes", "--no-labels")
    assert code == 1
    assert [(f["line"], f["possible"]) for f in report["findings"]] == [(40, False)]
    assert "label_runs" not in report["stages"]["routes"]
    assert report["coverage"]["unreached_labels"] == ["secret", "ending"]
    assert report["coverage"]["low_confidence"] == 0


@pytest.mark.req("EXP-011")
def test_label_runs_start_only_after_the_story_is_explored(run, tmp_path):
    run("labels", "--stages", "routes")
    log = next((tmp_path / "report").glob("report-*-logs/events-run.jsonl"))
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    first_label_run = next(i for i, e in enumerate(events) if e["ev"] == "label_start")
    ends = [(i, [step["kind"] for step in e["path"]][:1]) for i, e in enumerate(events) if e["ev"] == "path_end"]
    story = [i for i, kinds in ends if kinds != ["label"]]
    assert story and max(story) < first_label_run
    assert [kinds for i, kinds in ends if i > first_label_run] == [["label"]] * 5


@pytest.mark.req("EXP-015", "NFR-001")
def test_label_runs_give_the_same_report_every_time(run):
    _code, first, _text, _game = run("labels", "--stages", "routes")
    _code, second, _text, _game = run("labels", "--stages", "routes")
    assert first["findings"] == second["findings"]
    assert first["coverage"] == second["coverage"]
    assert first["stages"] == second["stages"]


@pytest.mark.req("RUN-012", "EXP-007", "EXP-013")
def test_engine_crash_in_a_label_run_does_not_stop_the_others(run):
    code, report, _text, _game = run("crash_label", "--stages", "routes")
    assert code == 0
    found = {f["class"]: f for f in report["findings"]}
    assert set(found) == {"engine-crash", "exception"}
    assert (found["engine-crash"]["possible"], steps(found["engine-crash"])) == (True, [("label", "trap")])
    assert (found["exception"]["possible"], steps(found["exception"])) == (True, [("label", "zeta")])
    routes = report["stages"]["routes"]
    assert (routes["launches"], routes["label_runs"]) == (2, 3)
    assert report["coverage"]["labels"]["alpha"]["low_confidence"] == 3


def comparable(report):
    """The parts of a report that must not depend on how many game processes were used (NFR-001)."""
    return report["findings"], report["coverage"], report["summary"], report["stages"]["routes"]["end_reasons"]


@pytest.mark.req("RUN-014", "RUN-015", "EXP-015", "NFR-001")
def test_several_game_processes_give_the_same_report_as_one(sdk, tmp_path, capsys):
    reports = {}
    for jobs in (1, 3):
        output = tmp_path / ("report-%d" % jobs)
        code = cli.main([
            str(sdk / "tutorial"), "--sdk", str(sdk), "--output", str(output), "--lang", "en", "--jobs", str(jobs)])
        capsys.readouterr()
        assert code == 0
        reports[jobs] = json.loads(next(output.glob("report-*.json")).read_text(encoding="utf-8"))
        logs = next(output.glob("report-*-logs"))
        # Each process keeps its own event file and its own engine log.
        assert sorted(p.name for p in logs.iterdir() if p.is_dir()) == ["labels-%d" % i for i in range(1, jobs)]
        for folder in (p for p in logs.iterdir() if p.is_dir()):
            assert (folder / "events-run.jsonl").stat().st_size > 0

    assert reports[1]["stages"]["routes"]["jobs"] == 1
    assert reports[3]["stages"]["routes"]["jobs"] == 3
    assert reports[3]["stages"]["routes"]["launches"] == 3
    assert comparable(reports[1]) == comparable(reports[3])


@pytest.mark.req("RUN-014", "EXP-011", "EXP-012")
def test_label_runs_in_a_process_of_their_own_are_resolved_the_same_way(run):
    _code, alone, _text, _game = run("labels")
    code, together, _text, _game = run("labels", "--jobs", "2")
    assert code == 1
    assert together["stages"]["routes"]["jobs"] == 2
    assert together["stages"]["routes"]["possible_dropped"] == 1
    assert comparable(alone) == comparable(together)


@pytest.mark.req("RUN-012", "RUN-014")
def test_engine_crash_in_one_process_does_not_stop_the_others(run):
    _code, alone, _text, _game = run("crash_label", "--stages", "routes")
    code, together, _text, _game = run("crash_label", "--stages", "routes", "--jobs", "2")
    assert code == 0
    # The story's process, the label process that died, and the one that took over from it.
    assert together["stages"]["routes"]["launches"] == 3
    assert comparable(alone) == comparable(together)


@pytest.mark.req("RUN-014", "CLI-003")
def test_jobs_must_be_at_least_one(sdk, game_copy, tmp_path, capsys):
    code = cli.main([str(game_copy("clean")), "--sdk", str(sdk), "--output", str(tmp_path / "out"), "--jobs", "0"])
    assert code == 2
    assert "--jobs" in capsys.readouterr().out


@pytest.mark.req("RUN-004", "RUN-016")
def test_nothing_waits_on_real_time(run):
    import datetime

    code, report, _text, _game = run("waits", "--stages", "routes")
    assert code == 0
    assert report["coverage"]["executed"] == report["coverage"]["total"]
    started, finished = (datetime.datetime.fromisoformat(report[name]) for name in ("started", "finished"))
    # The script asks for two minutes of waiting.
    assert (finished - started).total_seconds() < 30


@pytest.mark.req("RUN-025", "EXP-018")
def test_engine_safe_mode_does_not_replace_the_story(run):
    code, report, _text, _game = run("safe_mode", "--stages", "routes")
    assert code == 0
    assert report["stages"]["routes"]["end_reasons"] == {"end": 1}
    assert report["coverage"]["executed"] == report["coverage"]["total"]
