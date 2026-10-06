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
        files_before = sorted(p.relative_to(game).as_posix() for p in game.rglob("*"))
        output = tmp_path / "report"
        # One game process unless the test says otherwise, so that results do not depend on the machine.
        jobs = [] if "--jobs" in extra else ["--jobs", "1"]
        code = cli.main([str(game), "--sdk", str(sdk), "--output", str(output), "--lang", "en", *jobs, *extra])
        text = capsys.readouterr().out
        assert folder_digest(game) == before, "the game folder was changed by the run"
        assert sorted(p.relative_to(game).as_posix() for p in game.rglob("*")) == files_before
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

    assert report["summary"] == {"error": 0, "warning": 0, "info": 1, "possible": 1, "ignored": 0, "known": None}
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
        folders = sorted(p.name for p in logs.iterdir() if p.is_dir())
        assert folders == ["labels-%d" % i for i in range(1, jobs)] + ["translations"]
        for name in folders[:-1]:
            assert (logs / name / "events-run.jsonl").stat().st_size > 0
        assert (logs / "translations" / "events-renpytester_translations.jsonl").stat().st_size > 0

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


# --------------------------------------------------------------------- translations (spec 4.7)

TL_FILE = "game/tl/portuguese/script.rpy"


@pytest.mark.req("TL-001", "TL-002", "TL-003", "TL-004", "TL-005", "TL-006", "TL-012", "CLI-001", "NFR-003")
def test_complete_translation_has_nothing_to_report(run):
    code, report, text, _game = run("tl_clean")
    assert code == 0
    assert report["findings"] == []
    assert report["game"]["languages"] == ["portuguese"]
    assert report["stages"]["translations"] == {
        "status": "done", "findings": 0, "played": True, "languages": {"portuguese": {
            "switched": True, "dialogue": {"translated": 3, "total": 3}, "strings": {"translated": 3, "total": 3}}}}
    # Nothing is left to say, except, on an older engine, which lint checks it does not have.
    assert [note["message_id"] for note in report["notes"]] in ([], ["note.lint_options"])
    assert "portuguese: 3 of 3 lines of dialogue and 3 of 3 other texts translated" in text
    assert "PASSED" in text


@pytest.mark.req("TL-001", "CLI-001")
def test_game_in_one_language_has_no_translations_to_check(run):
    code, report, text, _game = run("clean")
    assert code == 0
    assert report["complete"] is True
    assert report["stages"]["translations"] == {"status": "done", "languages": {}}
    assert "Translations:" not in text


@pytest.mark.req("TL-002")
def test_language_that_cannot_be_switched_to_is_reported(run):
    code, report, text, _game = run("tl_switch")
    assert code == 1
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["severity"], finding["stage"]) == ("language-switch", "error", "translations")
    assert (finding["file"], finding["line"], finding["language"]) == (TL_FILE, 4, "portuguese")
    assert finding["params"] == {
        "language": "portuguese", "type": "NameError", "message": "name 'size_that_was_never_defined' is not defined"}
    assert "size_that_was_never_defined" in finding["traceback"]
    assert report["stages"]["translations"]["languages"]["portuguese"]["switched"] is False
    assert "could not be switched to portuguese" in text


@pytest.mark.req("TL-003", "ERR-005", "LINT-002")
def test_broken_text_tags_in_a_translation_are_reported_where_the_translation_is(run):
    code, report, _text, _game = run("tl_bad_text")
    assert code == 1
    found = sorted((f["line"], f["class"], f["params"]["text"]) for f in report["findings"])
    assert found == [
        (4, "bad-text", "Esta fala é {i}importante."),
        (11, "bad-text", "Pegue a porta {negrito}vermelha{/negrito}")]
    for finding in report["findings"]:
        assert (finding["file"], finding["stage"], finding["language"]) == (TL_FILE, "translations", "portuguese")
        assert finding["severity"] == "error"
        assert finding["params"]["problem"]
        # What lint says about the same line is attached, not listed a second time.
        assert all(other["stage"] == "lint" for other in finding["also"])


@pytest.mark.req("TL-004", "TL-006")
def test_translation_that_fails_in_the_real_game_state_is_found_by_playing(run):
    code, report, text, _game = run("tl_bad_variable")
    assert code == 1
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["severity"], finding["stage"]) == ("bad-interpolation", "error", "translations")
    assert (finding["file"], finding["line"], finding["language"]) == (TL_FILE, 7, "portuguese")
    assert (finding["label"], finding["possible"]) == ("start", False)
    assert "nome_do_jogador" in finding["params"]["message"]
    assert finding["params"]["text"] == "É bom ver você, [nome_do_jogador]."
    # Reading the same line shows which variable is wrong; that is attached to the failure.
    mismatch = [other for other in finding["also"] if other["class"] == "variable-mismatch"]
    assert [other["params"] for other in mismatch] == [
        {"language": "portuguese", "missing": "player_name", "extra": "nome_do_jogador"}]
    # The story itself, played in its own language, has nothing wrong with it.
    assert report["stages"]["routes"]["end_reasons"] == {"end": 1}
    assert report["stages"]["translations"]["played"] is True
    assert "cannot be shown when the game gets here" in text


@pytest.mark.req("TL-004", "NFR-002")
def test_translations_are_not_tried_out_when_the_game_is_not_played_and_the_report_says_so(run):
    code, report, text, _game = run("tl_bad_variable", "--stages", "translations")
    assert code == 0
    assert [(f["class"], f["severity"], f["line"]) for f in report["findings"]] == [("variable-mismatch", "warning", 7)]
    assert report["stages"]["translations"]["played"] is False
    assert [note["message_id"] for note in report["notes"]] == ["note.translations_not_played"]
    assert "The game was not played in this run" in text


@pytest.mark.req("TL-004", "CLI-002")
def test_translations_are_left_alone_when_their_stage_is_not_selected(run):
    code, report, _text, _game = run("tl_bad_variable", "--stages", "routes")
    assert code == 0
    assert report["findings"] == []
    assert report["stages"]["translations"] == {"status": "not_selected"}


@pytest.mark.req("TL-001", "TL-005", "TL-012")
def test_untranslated_lines_and_texts_are_warnings_with_their_place_in_the_script(run):
    code, report, text, _game = run("tl_untranslated")
    assert code == 0
    assert report["game"]["languages"] == ["portuguese", "spanish"]
    found = report["findings"]
    assert [(f["class"], f["severity"], f["stage"], f["language"], f["file"]) for f in found] == [
        ("untranslated", "warning", "translations", "portuguese", "game/script.rpy")] * 2
    line, choice = found
    assert (line["line"], line["message_id"], line["params"]["text"]) == (
        10, "finding.untranslated_line", "The second line was added later.")
    assert (choice["message_id"], choice["params"]["text"]) == ("finding.untranslated_string", "A new choice")
    # Newer engines give the line of the choice, older ones the line of its menu.
    assert choice["line"] in (12, 16)
    languages = report["stages"]["translations"]["languages"]
    assert languages["portuguese"]["dialogue"] == {"translated": 3, "total": 4}
    assert languages["portuguese"]["strings"] == {"translated": 1, "total": 2}
    assert languages["spanish"]["dialogue"] == {"translated": 4, "total": 4}
    assert languages["spanish"]["strings"] == {"translated": 2, "total": 2}
    assert "This line of dialogue has no portuguese translation: The second line was added later." in text
    assert "PASSED" in text


@pytest.mark.req("TL-005", "CLI-004")
def test_untranslated_lines_fail_the_run_when_warnings_do(run):
    code, _report, text, _game = run("tl_untranslated", "--stages", "translations", "--fail-on", "warning")
    assert code == 1
    assert "FAILED" in text


@pytest.mark.req("TL-001", "CLI-011")
def test_languages_to_check_can_be_chosen(run):
    code, report, text, _game = run("tl_untranslated", "--languages", "spanish")
    assert code == 0
    assert report["findings"] == []
    assert report["game"]["languages"] == ["portuguese", "spanish"]
    assert list(report["stages"]["translations"]["languages"]) == ["spanish"]
    assert report["settings"]["languages"] == ["spanish"]
    assert "portuguese:" not in text


@pytest.mark.req("TL-001", "CLI-003")
def test_language_the_game_does_not_have_is_refused(sdk, game_copy, tmp_path, capsys):
    game = game_copy("tl_untranslated")
    before = folder_digest(game)
    code = cli.main([
        str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--languages",
        "spanish,klingon"])
    assert code == 2
    assert "The game has no language named klingon. Its languages: portuguese, spanish." in capsys.readouterr().out
    assert folder_digest(game) == before


@pytest.mark.req("TL-006")
def test_translation_that_drops_a_variable_is_a_warning(run):
    code, report, text, _game = run("tl_dropped_variable")
    assert code == 0
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert (finding["class"], finding["severity"], finding["stage"]) == ("variable-mismatch", "warning", "translations")
    assert (finding["file"], finding["line"], finding["language"]) == (TL_FILE, 4, "portuguese")
    assert finding["params"] == {"language": "portuguese", "missing": "score", "extra": "-"}
    assert "Left out: score." in text


@pytest.mark.req("TL-004", "EXP-015", "NFR-001")
def test_translation_findings_do_not_depend_on_the_number_of_processes(run):
    _code, alone, _text, _game = run("tl_bad_variable")
    _code, together, _text, _game = run("tl_bad_variable", "--jobs", "3")
    assert alone["findings"] == together["findings"]
    assert alone["stages"]["translations"] == together["stages"]["translations"]


@pytest.mark.req("TL-001", "TL-012", "NFR-003")
def test_tutorial_translations_are_summarised_for_each_language(sdk, tmp_path, capsys):
    import shutil

    game = tmp_path / "tutorial"
    shutil.copytree(sdk / "tutorial", game)
    before = folder_digest(game)
    code = cli.main([
        str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--stages",
        "translations"])
    text = capsys.readouterr().out
    report = json.loads(next((tmp_path / "report").glob("report-*.json")).read_text(encoding="utf-8"))
    assert code == 0
    assert report["summary"]["error"] == 0
    languages = report["stages"]["translations"]["languages"]
    assert list(languages) == report["game"]["languages"]
    assert len(languages) >= 8
    for name, language in languages.items():
        assert language["switched"] is True, name
        assert language["dialogue"]["translated"] / language["dialogue"]["total"] > 0.9, name
        assert language["strings"]["total"] > 100, name
        assert "%s: %d of %d lines of dialogue" % (
            name, language["dialogue"]["translated"], language["dialogue"]["total"]) in text
    # What is left untranslated is listed, each with the language it is missing from.
    untranslated = [f for f in report["findings"] if f["class"] == "untranslated"]
    assert untranslated and all(f["language"] in languages and f["severity"] == "warning" for f in untranslated)
    assert folder_digest(game) == before


# ------------------------------------------------ settings file, reports, command line (M5)


@pytest.fixture
def settings_file(tmp_path):
    """Returns a function that writes a settings file outside the game and returns its path."""

    def write(text):
        path = tmp_path / "settings.toml"
        path.write_text(text, encoding="utf-8")
        return str(path)

    return write


def events_of(tmp_path):
    log = next((tmp_path / "report").glob("report-*-logs/events-run.jsonl"))
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.req("CFG-002", "CFG-005", "CFG-006")
def test_settings_file_in_the_game_folder_is_used(run, tmp_path):
    code, report, _text, game = run("configured", "--stages", "routes")
    assert code == 0
    assert report["findings"] == []
    settings = report["settings"]
    assert settings["config"] == str(game / "renpytester.toml")
    assert (settings["seed"], settings["variables"], settings["inputs"]) == (
        5, {"tickets": 2}, {"What is the door code?": "4721"})

    # The variable was set before the first statement, a menu, so the choice that needs it was offered.
    decisions = [e for e in events_of(tmp_path) if e["ev"] == "decision"]
    assert decisions[0]["options"] == ["Go in", "Stay out"]
    # The prompt named in the file got its own answer; the other one got the usual one.
    typed = {(e["line"], e["choice"]) for e in decisions if e["kind"] == "input"}
    assert typed == {(22, "4721"), (23, "Tester")}

    # Excluded labels are not played, not started at, and not counted. A call to one returns at
    # once, and a jump to one ends the story.
    routes = report["stages"]["routes"]
    assert routes["excluded_labels"] == ["arcade", "credits_roll"]
    assert routes["label_runs"] == 2
    assert routes["end_reasons"] == {"end": 3, "label end": 1}
    coverage = report["coverage"]
    assert sorted(coverage["labels"]) == ["hall", "start", "vault"]
    assert coverage["labels"]["vault"]["executed"] == coverage["labels"]["vault"]["total"]
    # All but what follows the wrong door code.
    assert coverage["total"] - coverage["executed"] == 2


@pytest.mark.req("CFG-001", "CFG-002")
def test_settings_file_named_on_the_command_line_replaces_the_one_in_the_game_folder(run, settings_file):
    code, report, _text, _game = run("configured", "--stages", "routes", "--config", settings_file(""))
    assert code == 0
    # Without its settings the game cannot be entered, and the labels left out before now fail.
    assert report["settings"]["seed"] == 0
    assert "excluded_labels" not in report["stages"]["routes"]
    assert sorted((f["line"], f["possible"]) for f in report["findings"]) == [(41, True), (46, True)]
    assert report["coverage"]["labels"]["hall"]["executed"] == 0


@pytest.mark.req("CFG-002")
def test_command_line_wins_over_the_settings_file(run):
    _code, report, _text, _game = run("configured", "--stages", "routes", "--seed", "9")
    assert report["settings"]["seed"] == 9
    assert report["settings"]["variables"] == {"tickets": 2}


@pytest.mark.req("CFG-003")
def test_ignored_findings_are_left_out_and_counted(run, settings_file):
    rule = '[[ignore]]\nclass = "exception"\nmessage = "undefined_alpha"\n'
    code, report, text, _game = run("two_bugs", "--stages", "routes", "--config", settings_file(rule))
    assert code == 1
    assert [f["params"]["message"] for f in report["findings"]] == ["name 'undefined_beta' is not defined"]
    assert report["summary"]["ignored"] == 1
    assert report["ignored_by"] == [{"rule": {"class": "exception", "message": "undefined_alpha"}, "count": 1}]
    assert "1 problems were left out by the ignore rules" in text

    code, report, text, _game = run(
        "two_bugs", "--stages", "routes", "--config", settings_file('[[ignore]]\nfile = "game/*.rpy"\n'))
    assert code == 0
    assert (report["findings"], report["summary"]["ignored"]) == ([], 2)
    assert "PASSED" in text and "2 problems were left out" in text


@pytest.mark.req("TL-005", "CFG-007")
def test_untranslated_lines_can_be_made_errors_in_the_settings_file(run, settings_file):
    code, report, _text, _game = run(
        "tl_untranslated", "--stages", "translations", "--config",
        settings_file('[severity]\nuntranslated = "error"\n'))
    assert code == 1
    assert [f["severity"] for f in report["findings"]] == ["error", "error"]
    assert report["summary"]["error"] == 2


@pytest.mark.req("CFG-004", "CLI-003")
def test_unknown_setting_stops_the_run_before_anything_is_started(sdk, game_copy, tmp_path, capsys, settings_file):
    game = game_copy("clean")
    before = folder_digest(game)
    code = cli.main([
        str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--config",
        settings_file("max_path = 10\n")])
    text = capsys.readouterr().out
    assert code == 2
    assert "has a setting this version does not know: max_path" in text
    assert "max_paths" in text
    assert not (tmp_path / "report").exists()
    assert folder_digest(game) == before


@pytest.mark.req("REP-007")
def test_baseline_leaves_only_new_findings(run, tmp_path):
    code, _first, _text, _game = run("two_bugs", "--stages", "routes")
    assert code == 1
    baseline = next((tmp_path / "report").glob("report-*.json"))
    earlier = tmp_path / "baseline.json"
    earlier.write_bytes(baseline.read_bytes())

    code, report, text, _game = run("two_bugs", "--stages", "routes", "--baseline", str(earlier))
    assert code == 0
    assert (report["findings"], report["summary"]["known"]) == ([], 2)
    assert "2 problems that the baseline report already had were left out" in text

    # A game with other problems than the baseline's still fails.
    code, report, _text, _game = run("exception", "--stages", "routes", "--baseline", str(earlier))
    assert code == 1
    assert (len(report["findings"]), report["summary"]["known"]) == (1, 0)


@pytest.mark.req("REP-002", "REP-003", "REP-004", "REP-005", "REP-009")
def test_every_run_writes_json_junit_and_html_reports(run, tmp_path):
    import xml.etree.ElementTree as ElementTree

    code, report, text, _game = run("exception", "--stages", "routes")
    assert code == 1
    stem = report["name"]
    written = sorted(p.name for p in (tmp_path / "report").iterdir() if p.is_file())
    assert written == [stem + ".html", stem + ".json", stem + ".xml"]
    for name in written:
        assert name in text

    suites = ElementTree.parse(tmp_path / "report" / (stem + ".xml")).getroot()
    assert (suites.get("tests"), suites.get("failures"), suites.get("errors")) == ("2", "1", "0")
    failure = suites.find("testsuite/testcase/failure")
    assert failure.get("type") == "exception"
    assert "undefined_function" in failure.get("message")
    assert "game/script.rpy:13" in failure.text

    page = (tmp_path / "report" / (stem + ".html")).read_text(encoding="utf-8")
    assert "Exception Fixture" in page and "FAILED" in page
    assert "undefined_function" in page and "line 13" in page
    assert 'data-severity="error" data-stage="routes"' in page


@pytest.mark.req("CLI-006", "SAFE-002", "NFR-002")
def test_stopping_a_run_restores_the_game_and_still_writes_what_was_found(run, monkeypatch):
    from renpytester.report.console import Console

    original = Console.progress

    def stop_at_the_first_path(self, kind, **data):
        original(self, kind, **data)
        if kind == "step":
            raise KeyboardInterrupt  # What Ctrl+C does, at a moment the test can choose.

    monkeypatch.setattr(Console, "progress", stop_at_the_first_path)
    code, report, text, _game = run("two_bugs", "--stages", "routes")

    assert code == 3
    assert (report["complete"], report["interrupted"]) == (False, True)
    assert report["stages"]["routes"]["status"] == "interrupted"
    assert report["stages"]["routes"]["paths"] == 1
    assert [f["class"] for f in report["findings"]] == ["exception"]
    assert [note["message_id"] for note in report["notes"]] == ["note.interrupted"]
    assert "Stopped. The game folder has been restored." in text
    assert "INCOMPLETE" in text


@pytest.mark.req("CLI-008", "GAME-006")
def test_info_says_what_the_game_is_without_playing_it(sdk, game_copy, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    game = game_copy("tl_untranslated")
    before = folder_digest(game)
    code = cli.main(["info", str(game), "--sdk", str(sdk), "--lang", "en"])
    text = capsys.readouterr().out
    assert code == 0
    for part in ("Game: Untranslated Fixture", "Engine: Ren'Py 8.", "Languages: 2 (portuguese, spanish)",
                 "Python: 3."):
        assert part in text, part
    assert "Playing" not in text and "PASSED" not in text
    assert folder_digest(game) == before
    # Nothing is left behind where the command was run.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["game-1"]


@pytest.mark.req("CLI-008", "ERR-001")
def test_info_on_a_game_that_cannot_start_says_why(sdk, game_copy, capsys):
    code = cli.main(["info", str(game_copy("parse_error")), "--sdk", str(sdk), "--lang", "en"])
    text = capsys.readouterr().out
    assert code == 1
    assert "game/script.rpy:8" in text


@pytest.mark.req("GAME-004")
def test_sdk_is_taken_from_the_environment_when_not_given(sdk, game_copy, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("RENPY_SDK", str(sdk))
    code = cli.main([
        str(game_copy("clean")), "--output", str(tmp_path / "report"), "--lang", "en", "--stages", "routes"])
    assert code == 0
    assert "PASSED" in capsys.readouterr().out


@pytest.mark.req("I18N-002")
def test_interface_language_can_be_set_in_the_settings_file(sdk, game_copy, tmp_path, capsys, settings_file):
    arguments = [
        str(game_copy("exception")), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--stages", "routes",
        "--config", settings_file('lang = "pt-BR"\n')]
    assert cli.main(arguments) == 1
    assert "O jogo quebrou aqui" in capsys.readouterr().out
    # The command line still has the last word.
    assert cli.main([*arguments, "--lang", "en"]) == 1
    assert "The game crashed here" in capsys.readouterr().out


# ------------------------------------------------------------- sandbox (spec 4.2, M6)

WRITTEN = "game/data/counter.txt, game/data/old_notes.txt, game/data/visit_log.txt"


@pytest.mark.req("SAFE-007")
def test_files_the_game_writes_in_its_own_folder_are_reported(sdk, game_copy, tmp_path, capsys):
    game = game_copy("writes_files")
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--jobs", "1"])
    text = capsys.readouterr().out
    report = json.loads(next((tmp_path / "report").glob("report-*.json")).read_text(encoding="utf-8"))
    assert code == 0
    assert report["findings"] == []
    assert report["game_wrote"] == {
        "created": ["game/data/visit_log.txt"], "changed": ["game/data/counter.txt"],
        "deleted": ["game/data/old_notes.txt"]}
    assert report["notes"][-1] == {"message_id": "note.game_wrote_files", "params": {
        "created": 1, "changed": 1, "deleted": 1, "files": WRITTEN}}
    assert "Use --sandbox to test a copy of the game instead." in text
    # In place, what the game created is removed again; the rest cannot be put back, as the note says.
    data = game / "game" / "data"
    assert sorted(p.name for p in data.iterdir()) == ["counter.txt"]
    assert "one more visit" in (data / "counter.txt").read_text(encoding="utf-8")
    assert sorted(p.name for p in (game / "game").iterdir()) == ["data", "script.rpy"]


@pytest.mark.req("SAFE-006", "SAFE-009", "SAFE-010", "SAFE-012")
def test_sandbox_tests_a_copy_and_never_writes_to_the_game(run, own_cache):
    # The run fixture checks that the game folder is byte-for-byte what it was.
    code, report, text, game = run("writes_files", "--sandbox")
    assert code == 0
    assert report["findings"] == []
    assert report["complete"] is True
    assert report["game"]["path"] == str(game)
    assert report["game"]["name"] == "Writing Fixture"
    assert report["settings"]["sandbox"] is True

    box = report["sandbox"]
    copy = own_cache / "sandbox"
    assert box["path"].startswith(str(copy)) and box["path"].endswith("copy")
    assert (box["copied"], box["removed"], box["verified"]) == (3, 0, False)
    # The game deleted one of its three files in the copy; what it created was cleaned away.
    assert box["files"] == 2 and box["bytes"] > 0
    assert report["notes"][-1] == {"message_id": "note.game_wrote_files.sandbox", "params": {
        "created": 1, "changed": 1, "deleted": 1, "files": WRITTEN}}
    assert "A copy of the game was tested, and the game itself was not touched." in text
    assert "3 files were copied and 0 removed" in text
    assert "Use --sandbox" not in text
    # Nothing of the tool's is left in the copy either.
    assert not [p for p in (copy.rglob("*")) if "zzz_renpytester_" in p.name]


@pytest.mark.req("SAFE-009", "SAFE-010", "SAFE-011")
def test_second_sandbox_run_copies_only_what_changed_in_between(sdk, game_copy, tmp_path, capsys):
    game = game_copy("writes_files")

    def sandbox_run(*extra):
        code = cli.main([
            str(game), "--sdk", str(sdk), "--output", str(tmp_path / "report"), "--lang", "en", "--jobs", "1",
            "--stages", "routes", "--sandbox", *extra])
        capsys.readouterr()
        files = sorted((tmp_path / "report").glob("report-*.json"), key=lambda p: p.stat().st_mtime_ns)
        report = json.loads(files[-1].read_text(encoding="utf-8"))
        assert code == 0
        return report["sandbox"]

    before = folder_digest(game)
    assert sandbox_run()["copied"] == 3
    # Nothing changed in the game: only the two files the game altered in the copy are put back.
    assert (sandbox_run()["copied"], folder_digest(game)) == (2, before)

    script = game / "game" / "script.rpy"
    script.write_text(script.read_text(encoding="utf-8") + "\n# Edited between runs.\n", encoding="utf-8")
    (game / "game" / "data" / "old_notes.txt").unlink()
    (game / "game" / "data" / "new_notes.txt").write_text("added between runs", encoding="utf-8")
    after_edit = folder_digest(game)
    # The edited script, the new file, and the one file the game altered that is still in the game.
    box = sandbox_run()
    assert (box["copied"], box["removed"], folder_digest(game)) == (3, 0, after_edit)

    # Comparing contents gives the same answer, and says that it did.
    box = sandbox_run("--sandbox-verify")
    assert (box["copied"], box["verified"]) == (1, True)


@pytest.mark.req("SAFE-006", "SAFE-011", "ERR-002")
def test_problems_found_in_the_copy_are_reported_as_the_games(run):
    code, report, text, game = run("exception", "--stages", "routes", "--sandbox-verify")
    assert code == 1
    # Asking for contents to be compared is asking for the sandbox.
    assert (report["settings"]["sandbox"], report["sandbox"]["verified"]) == (True, True)
    finding = report["findings"][0]
    assert (finding["class"], finding["file"], finding["line"]) == ("exception", "game/script.rpy", 13)
    assert report["game"]["path"] == str(game)
    assert report["name"].startswith("report-exception-fixture-")
    assert "game/script.rpy:13" in text


@pytest.mark.req("RUN-014", "RUN-015", "SAFE-006", "SAFE-007")
def test_several_processes_share_the_one_copy_and_the_report_says_what_that_can_mean(run):
    code, report, _text, _game = run("writes_files", "--sandbox", "--jobs", "3")
    assert code == 0
    assert report["findings"] == []
    assert [note["message_id"] for note in report["notes"]][-2:] == [
        "note.game_wrote_files.sandbox", "note.game_wrote_files.jobs"]


@pytest.mark.req("SAFE-012")
def test_cached_copies_can_be_listed_and_cleared(run, capsys, own_cache):
    _code, _report, _text, first = run("writes_files", "--sandbox", "--stages", "routes")
    _code, _report, _text, second = run("clean", "--sandbox", "--stages", "routes")
    capsys.readouterr()

    assert cli.main(["cache", "list", "--lang", "en"]) == 0
    text = capsys.readouterr().out
    assert "Copies of games are kept in %s" % own_cache in text
    assert str(first) in text and str(second) in text
    assert "2 copies," in text

    assert cli.main(["cache", "clear", str(second / "game"), "--lang", "en"]) == 0
    assert "Deleted 1 copies" in capsys.readouterr().out
    assert cli.main(["cache", "list", "--lang", "en"]) == 0
    text = capsys.readouterr().out
    assert str(first) in text and str(second) not in text

    assert cli.main(["cache", "clear", "--lang", "en"]) == 0
    assert "Deleted 1 copies" in capsys.readouterr().out
    assert cli.main(["cache", "list", "--lang", "en"]) == 0
    assert "There are none." in capsys.readouterr().out
    assert not list((own_cache / "sandbox").iterdir())
