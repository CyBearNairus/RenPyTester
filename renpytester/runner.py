"""One test run from start to finish: find the game, prepare it, run the stages, restore it."""

import datetime
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from renpytester import __version__, discovery, lint
from renpytester.errors import ToolError
from renpytester.launcher import run_command, run_engine
from renpytester.model import ERROR, Finding, Report
from renpytester.routes import Coverage, Frontier
from renpytester.workspace import PREFIX, Workspace

LINT = "lint"
ROUTES = "routes"
STAGES = (LINT, ROUTES)
# How many times a run starts the game again after it died or hung, before giving up on what is left.
MAX_RELAUNCHES = 20
# Stages the specification defines that are not built yet. They are reported as not run, never as passed.
NOT_BUILT = ("translations", "screens")

PARSE_ERROR = re.compile(r'^File "(?P<file>[^"]+)", line (?P<line>\d+): (?P<message>.*)$')
TRACEBACK_FILE = re.compile(r'File "(?P<file>game/[^"]+)", line (?P<line>\d+)')
EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Warning|Exit|Interrupt|NotFound)\w*: .+")


@dataclass
class Options:
    game: str
    sdk: str | None = None
    output: str = "renpytester-report"
    strategy: str = "explore"
    seed: int = 0
    timeout: float = 60.0
    input_value: str = "Tester"
    max_steps: int = 200000
    max_paths: int = 5000
    max_time: float = 600.0
    max_depth: int = 500
    show_window: bool = False
    fail_on: str = ERROR
    fail_on_possible: bool = False
    stages: tuple = STAGES


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def report_name(game_name, when=None):
    """The name a run's files are saved under: report-<game>-<date>-<time> (REP-009).

    The game's name keeps reports of different games apart, and the time keeps a later run from
    replacing an earlier one. The time is the user's local time, since it is there to be read.
    """
    when = when or datetime.datetime.now()
    # Accented letters lose their accents instead of becoming gaps: "Coração" is saved as "coracao".
    plain = unicodedata.normalize("NFKD", game_name or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return "report-%s-%s" % (slug[:60].strip("-") or "game", when.strftime("%Y-%m-%d-%H%M%S"))


def parse_errors(text, stage):
    """Turns the engine's errors.txt into findings (ERR-001)."""
    findings = []
    for line in text.splitlines():
        match = PARSE_ERROR.match(line.strip("﻿ "))
        if match:
            findings.append(Finding(
                "parse-error", ERROR, "finding.parse_error", {"message": match["message"]},
                match["file"].replace("\\", "/"), int(match["line"]), stage=stage))
    return findings


def load_failure(text, stage):
    """A finding for a game that stopped before the harness could start, from the engine's traceback."""
    lines = [i.strip() for i in text.splitlines() if i.strip()]
    named = [i for i in lines if EXCEPTION_LINE.match(i)]
    message = named[-1] if named else (lines[-1] if lines else "")
    places = TRACEBACK_FILE.findall(text)
    filename, line = (places[-1][0], int(places[-1][1])) if places else (None, None)
    if filename and PREFIX in filename:
        # Our own script failed to load. That is never the game's fault (NFR-004).
        raise ToolError("error.harness_bug", message=message, traceback=text[-4000:])
    return Finding("load-failure", ERROR, "finding.load_failure", {"message": message}, filename, line,
                   stage=stage, traceback=text[-4000:] or None)


def to_finding(event, stage):
    return Finding(
        event["cls"], event["severity"], event["message_id"], event.get("params") or {}, event.get("file"),
        event.get("line"), event.get("label"), stage, None, event.get("path") or [], event.get("traceback"),
        possible=bool(event.get("possible")))


def collect_engine_files(game, output_dir):
    """Copies the reports the engine wrote beside the game before they are cleaned away (REP-008)."""
    texts = {}
    for name in ("errors.txt", "traceback.txt"):
        source = game.basedir / name
        if source.is_file():
            texts[name] = source.read_text(encoding="utf-8", errors="replace")
            shutil.copyfile(source, output_dir / "engine-logs" / name)
    return texts


def startup_findings(game, run, output_dir, stage):
    """Explains an engine process that ended without the harness reporting in."""
    texts = collect_engine_files(game, output_dir)
    findings = parse_errors(texts.get("errors.txt", ""), stage)
    if findings:
        return findings
    evidence = texts.get("traceback.txt") or run.output
    if TRACEBACK_FILE.search(evidence):
        return [load_failure(evidence, stage)]
    return []


def run(options, on_progress=None):
    """Runs every stage and returns the report. Raises ToolError when testing is impossible."""
    game = discovery.discover(options.game, options.sdk)

    output_dir = Path(options.output).resolve()
    if output_dir == game.basedir or game.basedir in output_dir.parents:
        raise ToolError("error.output_inside_game", path=str(output_dir))
    shutil.rmtree(output_dir / "engine-logs", ignore_errors=True)
    (output_dir / "engine-logs").mkdir(parents=True, exist_ok=True)

    settings = {
        "strategy": options.strategy, "seed": options.seed, "timeout": options.timeout,
        "input_value": options.input_value, "max_steps": options.max_steps, "max_paths": options.max_paths,
        "max_time": options.max_time, "max_depth": options.max_depth, "show_window": options.show_window,
        "fail_on": options.fail_on, "fail_on_possible": options.fail_on_possible, "stages": list(options.stages),
    }
    report = Report(__version__, str(game.basedir), game.kind, settings=settings, started=now())
    report.game = {"renpy_version": ".".join(str(i) for i in game.renpy_version) or None}
    report.stages = {name: {"status": "not_run" if name in options.stages else "not_selected"} for name in STAGES}
    for name in NOT_BUILT:
        report.stages[name] = {"status": "not_implemented"}

    def progress(kind, **data):
        if on_progress:
            on_progress(kind, **data)

    harness_settings = {
        "strategy": options.strategy, "seed": options.seed, "input_value": options.input_value,
        "max_steps": options.max_steps, "max_paths": options.max_paths, "max_time": options.max_time,
        "max_depth": options.max_depth}

    workspace = Workspace(game.basedir)
    try:
        with workspace, tempfile.TemporaryDirectory(prefix="renpytester-") as work_dir:
            if workspace.repaired:
                report.notes.append({"message_id": "note.repaired", "params": {}})
                progress("note", message_id="note.repaired", params={})

            # ---- What is this game? (GAME-006) Also the first point where a broken script shows.
            logs = output_dir / "engine-logs"
            probe = run_engine(
                game, "renpytester_info", work_dir, logs, harness_settings, options.timeout,
                show_window=options.show_window)
            hello = next((e for e in probe.events if e["ev"] == "hello"), None)

            if hello is None:
                findings = startup_findings(game, probe, output_dir, ROUTES)
                if not findings:
                    raise ToolError("error.engine_failed", code=probe.exit_code, output=probe.output[-2000:].strip())
                for finding in findings:
                    report.add(finding)
                for name in options.stages:
                    report.stages[name] = {"status": "blocked"}
            else:
                report.game.update({
                    "name": hello.get("name"), "version": hello.get("version"),
                    "renpy_version": hello.get("renpy_version"), "python": hello.get("python"),
                    "languages": hello.get("languages", [])})
                progress("game", game=report.game, game_kind=game.kind)
                if LINT in options.stages:
                    progress("stage", name=LINT)
                    run_lint(game, options, work_dir, output_dir, report, progress)
                if ROUTES in options.stages:
                    progress("stage", name=ROUTES)
                    run_routes(game, options, harness_settings, work_dir, output_dir, report, progress)
    finally:
        report.finished = now()

    if workspace.changed_by_game:
        report.notes.append({"message_id": "note.game_changed_files", "params": {
            "count": len(workspace.changed_by_game), "files": workspace.changed_by_game[:20]}})

    # Until now the game's own name was not known, so the logs were collected under a working name.
    report.name = report_name(report.game.get("name") or game.basedir.name)
    logs = output_dir / (report.name + "-logs")
    shutil.rmtree(logs, ignore_errors=True)
    (output_dir / "engine-logs").rename(logs)

    report.merge_stages()
    report.complete = all(report.stages[name]["status"] in ("done", "blocked") for name in options.stages)
    return report


def run_lint(game, options, work_dir, output_dir, report, progress):
    """Runs the engine's own lint and turns its report into findings (spec 4.6)."""
    stage = report.stages[LINT]
    stage["status"] = "running"
    lint_file = output_dir / "engine-logs" / "lint.txt"
    lint_file.unlink(missing_ok=True)

    # Lint reads the whole script without playing it, so it gets a time limit, not a progress watchdog.
    timeout = max(options.timeout, 300)
    wanted = list(lint.EXTRA_OPTIONS)
    code, output = run_command(game, "lint", [str(lint_file), *wanted], work_dir, output_dir / "engine-logs", timeout)

    rejected = lint.unrecognised_options(output)
    if rejected and not lint_file.exists():
        # An older engine: run again without the options it does not have, and say so (COMPAT-005).
        wanted = [i for i in wanted if i not in rejected]
        stage["unsupported_options"] = rejected
        report.notes.append({"message_id": "note.lint_options", "params": {"options": ", ".join(rejected)}})
        code, output = run_command(
            game, "lint", [str(lint_file), *wanted], work_dir, output_dir / "engine-logs", timeout)

    if not lint_file.exists():
        stage["status"] = "failed"
        stage["reason"] = "timeout" if code is None else "exit code %s" % code
        report.notes.append({"message_id": "note.lint_failed", "params": {"reason": stage["reason"]}})
        return

    findings, statistics = lint.parse(lint_file.read_text(encoding="utf-8-sig", errors="replace"))
    for finding in findings:
        progress("finding", finding=report.add(finding))
    if statistics:
        report.statistics["script"] = statistics
    stage["status"] = "done"
    stage["findings"] = len(findings)


def run_routes(game, options, harness_settings, work_dir, output_dir, report, progress):
    """Plays the game, exploring its branches (spec 4.3, 4.4)."""
    stage = report.stages[ROUTES]
    stage["status"] = "running"
    coverage = Coverage()
    waiting = set()
    reasons = {}
    totals = {"paths": 0, "statements": 0, "interactions": 0}
    limit = None
    launches = 0
    resume = None

    while True:
        launches += 1
        frontier = Frontier(coverage, waiting)

        def on_event(event, frontier=frontier):
            frontier.feed(event)
            kind = event["ev"]
            if kind == "finding":
                progress("finding", finding=report.add(to_finding(event, ROUTES)))
            elif kind in ("heartbeat", "path_end"):
                progress(
                    "step", paths=totals["paths"] + frontier.paths, waiting=len(frontier.waiting),
                    percent=coverage.percent())

        settings = dict(harness_settings, resume=[list(i) for i in resume]) if resume else harness_settings
        result = run_engine(
            game, "run", work_dir, output_dir / "engine-logs", settings, options.timeout, on_event,
            options.show_window)

        bug = next((e for e in result.events if e["ev"] == "harness_error"), None)
        if bug:
            raise ToolError("error.harness_bug", message=bug.get("message"), traceback=bug.get("traceback"))

        waiting = frontier.waiting
        totals["paths"] += frontier.paths
        totals["statements"] += frontier.steps
        totals["interactions"] += frontier.interactions
        for reason, count in frontier.reasons.items():
            reasons[reason] = reasons.get(reason, 0) + count

        if frontier.done is not None:
            limit = frontier.done.get("limit")
            break

        # The process died or was shut down without finishing.
        findings = [] if frontier.started else startup_findings(game, result, output_dir, ROUTES)
        if not findings:
            if result.timed_out:
                cls, message_id, params, trace = "hang", "finding.hang", {"seconds": int(options.timeout)}, None
            else:
                cls, message_id, params = "engine-crash", "finding.engine_crash", {"code": result.exit_code}
                trace = result.output[-4000:] or None
            findings = [Finding(
                cls, ERROR, message_id, params, frontier.last.get("file"), frontier.last.get("line"), stage=ROUTES,
                path=list(frontier.path), traceback=trace)]
            totals["paths"] += 1
            reasons[cls] = reasons.get(cls, 0) + 1
        for finding in findings:
            progress("finding", finding=report.add(finding))

        if not waiting:
            break
        if launches > MAX_RELAUNCHES:
            limit = {"kind": "relaunches", "unexplored": len(waiting)}
            break
        # Carry on with the branches the dead process had announced but not started (RUN-012).
        resume = sorted(waiting)

    stage["status"] = "done"
    stage["paths"] = totals["paths"]
    stage["end_reasons"] = dict(sorted(reasons.items()))
    stage["launches"] = launches
    if limit:
        stage["limited"] = limit
        report.notes.append({"message_id": "note.limited." + limit["kind"], "params": {"count": limit["unexplored"]}})
    report.coverage = coverage.report()
    report.statistics.update(statements=totals["statements"], interactions=totals["interactions"])
    collect_engine_files(game, output_dir)
