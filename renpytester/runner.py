"""One test run from start to finish: find the game, prepare it, run the stages, restore it."""

import datetime
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from renpytester import __version__, discovery
from renpytester.errors import ToolError
from renpytester.launcher import run_engine
from renpytester.model import ERROR, Finding, Report
from renpytester.workspace import PREFIX, Workspace

ROUTES = "routes"
# Stages the specification defines that are not built yet. They are reported as not run, never as passed.
NOT_BUILT = ("lint", "translations", "screens")

PARSE_ERROR = re.compile(r'^File "(?P<file>[^"]+)", line (?P<line>\d+): (?P<message>.*)$')
TRACEBACK_FILE = re.compile(r'File "(?P<file>game/[^"]+)", line (?P<line>\d+)')
EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Warning|Exit|Interrupt|NotFound)\w*: .+")


@dataclass
class Options:
    game: str
    sdk: str | None = None
    output: str = "renpytester-report"
    strategy: str = "first"
    seed: int = 0
    timeout: float = 60.0
    input_value: str = "Tester"
    max_steps: int = 200000
    show_window: bool = False
    fail_on: str = ERROR


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


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
        event.get("line"), event.get("label"), stage, None, event.get("path") or [], event.get("traceback"))


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
        "input_value": options.input_value, "max_steps": options.max_steps, "show_window": options.show_window,
        "fail_on": options.fail_on,
    }
    report = Report(__version__, str(game.basedir), game.kind, settings=settings, started=now())
    report.game = {"renpy_version": ".".join(str(i) for i in game.renpy_version) or None}
    report.stages = {ROUTES: {"status": "not_run"}}
    for name in NOT_BUILT:
        report.stages[name] = {"status": "not_implemented"}

    def progress(kind, **data):
        if on_progress:
            on_progress(kind, **data)

    harness_settings = {
        "seed": options.seed, "input_value": options.input_value, "max_steps": options.max_steps}

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
                report.stages[ROUTES] = {"status": "blocked"}
            else:
                report.game.update({
                    "name": hello.get("name"), "version": hello.get("version"),
                    "renpy_version": hello.get("renpy_version"), "python": hello.get("python"),
                    "languages": hello.get("languages", [])})
                progress("game", game=report.game, game_kind=game.kind)
                run_routes(game, options, harness_settings, work_dir, output_dir, report, progress)
    finally:
        report.finished = now()

    if workspace.changed_by_game:
        report.notes.append({"message_id": "note.game_changed_files", "params": {
            "count": len(workspace.changed_by_game), "files": workspace.changed_by_game[:20]}})

    report.complete = report.stages[ROUTES]["status"] in ("done", "blocked")
    return report


def run_routes(game, options, harness_settings, work_dir, output_dir, report, progress):
    """Plays the game (spec 4.3, 4.4). In this milestone: one path, first choice everywhere (EXP-006)."""
    stage = report.stages[ROUTES]
    stage["status"] = "running"
    last = {}

    def on_event(event):
        kind = event["ev"]
        if kind in ("heartbeat", "decision"):
            last.update(file=event.get("file"), line=event.get("line"))
            progress("step", steps=event.get("steps"), file=event.get("file"), line=event.get("line"))
        elif kind == "finding":
            progress("finding", finding=report.add(to_finding(event, ROUTES)))

    result = run_engine(
        game, "run", work_dir, output_dir / "engine-logs", harness_settings, options.timeout, on_event,
        options.show_window)

    bug = next((e for e in result.events if e["ev"] == "harness_error"), None)
    if bug:
        raise ToolError("error.harness_bug", message=bug.get("message"), traceback=bug.get("traceback"))

    done = next((e for e in result.events if e["ev"] == "done"), None)
    ends = [e for e in result.events if e["ev"] == "path_end"]

    if result.timed_out:
        finding = Finding(
            "hang", ERROR, "finding.hang", {"seconds": int(options.timeout)}, last.get("file"), last.get("line"),
            stage=ROUTES, path=[
                {k: e.get(k) for k in ("kind", "file", "line", "choice", "index")}
                for e in result.events if e["ev"] == "decision"])
        progress("finding", finding=report.add(finding))
        stage["status"] = "done"
    elif done is None:
        findings = startup_findings(game, result, output_dir, ROUTES)
        if not findings:
            findings = [Finding(
                "engine-crash", ERROR, "finding.engine_crash", {"code": result.exit_code}, last.get("file"),
                last.get("line"), stage=ROUTES, traceback=result.output[-4000:] or None)]
        for finding in findings:
            progress("finding", finding=report.add(finding))
        stage["status"] = "done"
    else:
        stage["status"] = "done"
        report.coverage = done.get("coverage")
        report.statistics = {"statements": done.get("steps"), "interactions": done.get("interactions")}

    stage["paths"] = len(ends)
    stage["end_reasons"] = [e.get("reason") for e in ends]
    collect_engine_files(game, output_dir)
