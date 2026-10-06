"""One test run from start to finish: find the game, prepare it, run the stages, restore it."""

import datetime
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from renpytester import __version__, discovery, lint
from renpytester.errors import ToolError, UsageError
from renpytester.launcher import default_jobs, run_command, run_engine
from renpytester.model import ERROR, Finding, Report
from renpytester.routes import Coverage, Frontier
from renpytester.workspace import PREFIX, Workspace

LINT = "lint"
ROUTES = "routes"
TRANSLATIONS = "translations"
STAGES = (LINT, ROUTES, TRANSLATIONS)
# How many times a run starts the game again after it died or hung, before giving up on what is left.
MAX_RELAUNCHES = 20
# Fewer labels than this are not worth starting another game process for.
LABELS_PER_PROCESS = 8
# Stages the specification defines that are not built yet. They are reported as not run, never as passed.
NOT_BUILT = ("screens",)

PARSE_ERROR = re.compile(r'^File "(?P<file>[^"]+)", line (?P<line>\d+): (?P<message>.*)$')
TRACEBACK_FILE = re.compile(r'File "(?P<file>game/[^"]+)", line (?P<line>\d+)')
EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Warning|Exit|Interrupt|NotFound)\w*: .+")


@dataclass
class Options:
    game: str
    sdk: str | None = None
    output: str = "renpytester-report"
    strategy: str = "explore"
    labels: bool = True
    # How many game processes may run at once; None lets the tool choose (RUN-014).
    jobs: int | None = None
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
    # The game's languages to check; None is all of them (TL-001).
    languages: tuple | None = None
    # An earlier report: findings that are in it are left out of this one (REP-007).
    baseline: str | None = None
    # From the config file (spec 4.11). `config` is the file itself, for the record.
    config: str | None = None
    severity: dict = field(default_factory=dict)
    ignore: tuple = ()
    inputs: dict = field(default_factory=dict)
    variables: dict = field(default_factory=dict)
    exclude_labels: tuple = ()


def build_options(game, given, config):
    """The settings of a run: the defaults, changed by the config file, changed by what was asked for
    on the command line or in the window (CFG-001, CFG-002). `given` holds only what was asked for."""
    values = dict(config.settings)
    values.update({name: value for name, value in given.items() if value is not None})
    if not values.get("sdk"):
        values["sdk"] = os.environ.get("RENPY_SDK") or None  # GAME-004

    if "stages" in values:
        wanted = tuple(values["stages"])
        unknown = [name for name in wanted if name not in STAGES]
        if unknown or not wanted:
            raise UsageError("error.unknown_stage", stages=", ".join(unknown) or "-", all=", ".join(STAGES))
        values["stages"] = tuple(name for name in STAGES if name in wanted)
    if values.get("jobs") is not None and values["jobs"] < 1:
        raise UsageError("error.bad_jobs")

    return Options(
        game=game, config=str(config.path) if config.path else None, severity=dict(config.severity),
        ignore=tuple(config.ignore), inputs=dict(config.inputs), variables=dict(config.variables),
        exclude_labels=tuple(config.exclude_labels), **values)


def load_baseline(path):
    """The ids of the findings in an earlier report (REP-007)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {finding["id"] for finding in data["findings"]}
    except (OSError, ValueError, KeyError, TypeError):
        raise UsageError("error.baseline_unreadable", path=str(path)) from None


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
    # A translation tried out while the story is played is found by the process that plays, but
    # belongs to the translations stage; the harness says so.
    return Finding(
        event["cls"], event["severity"], event["message_id"], event.get("params") or {}, event.get("file"),
        event.get("line"), event.get("label"), event.get("stage") or stage, event.get("language"),
        event.get("path") or [], event.get("traceback"), possible=bool(event.get("possible")),
        node=event.get("node"))


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
    if options.jobs is None:
        options.jobs = default_jobs()
    # Read before anything is started: a baseline that cannot be read should not cost a whole run.
    known = load_baseline(options.baseline) if options.baseline else None

    output_dir = Path(options.output).resolve()
    if output_dir == game.basedir or game.basedir in output_dir.parents:
        raise ToolError("error.output_inside_game", path=str(output_dir))
    shutil.rmtree(output_dir / "engine-logs", ignore_errors=True)
    (output_dir / "engine-logs").mkdir(parents=True, exist_ok=True)

    settings = {
        "strategy": options.strategy, "labels": options.labels, "jobs": options.jobs, "seed": options.seed,
        "timeout": options.timeout,
        "input_value": options.input_value, "max_steps": options.max_steps, "max_paths": options.max_paths,
        "max_time": options.max_time, "max_depth": options.max_depth, "show_window": options.show_window,
        "fail_on": options.fail_on, "fail_on_possible": options.fail_on_possible, "stages": list(options.stages),
        "languages": list(options.languages) if options.languages is not None else None,
        "baseline": options.baseline, "config": options.config, "severity": dict(options.severity),
        "ignore": [rule.to_dict() for rule in options.ignore], "inputs": dict(options.inputs),
        "variables": dict(options.variables), "exclude_labels": list(options.exclude_labels),
    }
    report = Report(__version__, str(game.basedir), game.kind, settings=settings, started=now())
    report.game = {"renpy_version": ".".join(str(i) for i in game.renpy_version) or None}
    report.stages = {name: {"status": "not_run" if name in options.stages else "not_selected"} for name in STAGES}
    for name in NOT_BUILT:
        report.stages[name] = {"status": "not_implemented"}

    progress_lock = threading.RLock()
    cancel = threading.Event()

    def progress(kind, **data):
        if on_progress:
            with progress_lock:
                on_progress(kind, **data)

    harness_settings = {
        "strategy": options.strategy, "labels": options.labels, "seed": options.seed,
        "input_value": options.input_value,
        "max_steps": options.max_steps, "max_paths": options.max_paths, "max_time": options.max_time,
        "max_depth": options.max_depth, "inputs": options.inputs, "variables": options.variables,
        "exclude_labels": list(options.exclude_labels)}

    workspace = Workspace(game.basedir)
    # What the routes stage has found so far; kept here so that a run that is stopped can still report it.
    partial = {}
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
                languages = languages_to_check(options, report.game["languages"])
                translating = TRANSLATIONS in options.stages
                if translating:
                    # The translations of each line are tried out as the story is played (TL-004).
                    harness_settings["languages"] = languages
                jobs = []
                translated = []
                if LINT in options.stages:
                    progress("stage", name=LINT)
                    jobs.append((run_lint, (game, options, work_dir, output_dir, report, progress)))
                if ROUTES in options.stages:
                    progress("stage", name=ROUTES)
                    jobs.append((explore_routes, (
                        game, options, harness_settings, hello.get("labels"), work_dir, output_dir, report,
                        progress, cancel, partial)))
                if translating:
                    progress("stage", name=TRANSLATIONS)
                    jobs.append((lambda *arguments: translated.append(check_translations(*arguments)), (
                        game, options, harness_settings, languages, work_dir, output_dir, report, cancel)))
                # Lint and the translation check read the script while the game is being played, unless
                # only one process may run.
                if options.jobs > 1:
                    in_parallel(jobs, lambda function, arguments: function(*arguments), cancel)
                else:
                    for function, arguments in jobs:
                        function(*arguments)
                if partial:
                    finish_routes(game, options, partial.pop("exploration"), output_dir, report)
                # Last, and from here, so that the order of the findings never depends on which
                # process finished first (NFR-001).
                if translated:
                    finish_translations(translated[0], report)
    except KeyboardInterrupt:
        # Stopped by the user. The game processes are gone and the game folder is as it was; what
        # was found up to now is still reported, marked as not complete (CLI-006).
        report.interrupted = True
        unfinished = [name for name in options.stages if report.stages[name]["status"] in ("not_run", "running")]
        if partial:
            finish_routes(game, options, partial.pop("exploration"), output_dir, report)
        for name in unfinished:
            report.stages[name]["status"] = "interrupted"
        report.notes.append({"message_id": "note.interrupted", "params": {}})
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
    # What the user asked for, last: severities of their own, findings to ignore, findings already known.
    report.set_severities(options.severity)
    report.ignore(options.ignore)
    if known is not None:
        report.leave_out_known(known)
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


def languages_to_check(options, known):
    """The game's languages that this run checks: all of them, or those asked for (TL-001)."""
    if options.languages is None:
        return list(known)
    unknown = [name for name in options.languages if name not in known]
    if unknown:
        raise UsageError("error.unknown_language", languages=", ".join(unknown), known=", ".join(known) or "-")
    return [name for name in known if name in options.languages]


def check_translations(game, options, harness_settings, languages, work_dir, output_dir, report, cancel):
    """Checks every language by reading the script, in a game process that plays nothing (spec 4.7).

    Returns the events that process wrote, or None when there was nothing to check or it did not finish.
    """
    stage = report.stages[TRANSLATIONS]
    stage["status"] = "running"
    stage["languages"] = {}
    if not languages:
        stage["status"] = "done"  # A game in one language: nothing to check, and nothing left unchecked.
        return None

    # A folder of its own: this runs while the game is being played (RUN-015).
    result = run_engine(
        game, "renpytester_translations", Path(work_dir) / TRANSLATIONS,
        Path(output_dir) / "engine-logs" / TRANSLATIONS, harness_settings, max(options.timeout, 300),
        show_window=options.show_window, cancel=cancel)
    if result.cancelled:
        return None

    bug = next((e for e in result.events if e["ev"] == "harness_error"), None)
    if bug:
        raise ToolError("error.harness_bug", message=bug.get("message"), traceback=bug.get("traceback"))
    if not any(e["ev"] == "done" for e in result.events):
        if PREFIX in result.output:
            raise ToolError("error.harness_bug", message="", traceback=result.output[-4000:])
        stage["status"] = "failed"
        stage["reason"] = "timeout" if result.timed_out else "exit code %s" % result.exit_code
        report.notes.append({"message_id": "note.translations_failed", "params": {"reason": stage["reason"]}})
        return None
    return result.events


def finish_translations(events, report):
    """Puts what the translation check found into the report (spec 4.7)."""
    stage = report.stages[TRANSLATIONS]
    if events is None:
        return

    for event in events:
        if event["ev"] == "finding":
            report.add(to_finding(event, TRANSLATIONS))
        elif event["ev"] == "language":
            stage["languages"][event["language"]] = {
                "switched": bool(event["switched"]),
                "dialogue": dict(zip(("translated", "total"), event["dialogue"])),
                "strings": dict(zip(("translated", "total"), event["strings"]))}
        elif event["ev"] == "translations" and not event.get("read_source"):
            stage["strings_from_source"] = False
            report.notes.append({"message_id": "note.strings_need_source", "params": {}})

    stage["status"] = "done"
    stage["findings"] = sum(1 for finding in report.findings if finding.stage == TRANSLATIONS)
    # Trying translations out in the state the game is really in needs the game to be played (TL-004).
    stage["played"] = report.stages[ROUTES]["status"] == "done"
    if not stage["played"]:
        report.notes.append({"message_id": "note.translations_not_played", "params": {}})


def split_labels(labels, jobs):
    """Shares the labels out between the game processes that play nothing but label runs.

    The story is explored by one process, because what it finds depends on the order it is explored
    in; label runs do not depend on each other (EXP-019), so they are what is spread over the other
    processes. A process takes a few seconds to start, which is not worth it for a handful of labels.
    """
    workers = min(jobs - 1, -(-len(labels) // LABELS_PER_PROCESS))
    return [labels[index::workers] for index in range(workers)] if workers > 0 else []


class Exploration:
    """What the game processes of one routes stage add up to. Shared between their threads."""

    def __init__(self, labels):
        self.lock = threading.RLock()
        self.coverage = Coverage()
        self.label_order = {name: index for index, name in enumerate(labels)}
        self.findings = []
        self.reasons = {}
        self.totals = {"paths": 0, "statements": 0, "interactions": 0, "label_runs": 0, "launches": 0}
        self.waiting = {}
        self.limits = []
        self.relaunches = 0
        self.started = time.monotonic()
        self.jobs = 1
        # Labels the config file said not to play, as the game named them (CFG-006).
        self.excluded = []

    def collect(self, finding, lane, launch):
        """Keeps a finding with its place in an order that does not depend on timing (NFR-001):
        the story's findings first, then those of label runs, label by label."""
        first = finding.path[0] if finding.path else {}
        if first.get("kind") == "label":
            key = (1, self.label_order.get(first.get("choice"), len(self.label_order)), lane, launch)
        else:
            key = (0, 0, lane, launch)
        self.findings.append((key + (len(self.findings),), finding))

    def end(self, reason, count=1):
        self.reasons[reason] = self.reasons.get(reason, 0) + count


def run_lane(lane, game, options, settings, exploration, work_dir, log_dir, progress, cancel):
    """One game process exploring, started again for as long as it dies with work left (RUN-012)."""
    waiting = set()
    labels = None
    launch = 0

    while True:
        launch += 1
        frontier = Frontier(exploration.coverage, waiting, labels)

        def on_event(event, frontier=frontier, launch=launch):
            with exploration.lock:
                frontier.feed(event)
                kind = event["ev"]
                if kind == "start":
                    exploration.excluded = list(event.get("excluded") or [])
                elif kind == "finding":
                    finding = to_finding(event, ROUTES)
                    exploration.collect(finding, lane, launch)
                    progress("finding", finding=finding)
                elif kind in ("heartbeat", "path_end"):
                    if kind == "path_end":
                        exploration.totals["paths"] += 1
                        exploration.end(event["reason"])
                    exploration.waiting[lane] = len(frontier.waiting)
                    progress(
                        "step", paths=exploration.totals["paths"], waiting=sum(exploration.waiting.values()),
                        percent=exploration.coverage.percent())

        # The time limit is for the whole stage, not for each process started during it (EXP-003).
        left = max(options.max_time - (time.monotonic() - exploration.started), 1)
        result = run_engine(
            game, "run", work_dir, log_dir, dict(settings, max_time=left), options.timeout, on_event,
            options.show_window, cancel)
        if result.cancelled:
            return

        bug = next((e for e in result.events if e["ev"] == "harness_error"), None)
        if bug:
            raise ToolError("error.harness_bug", message=bug.get("message"), traceback=bug.get("traceback"))

        with exploration.lock:
            waiting = frontier.waiting
            labels = frontier.labels
            exploration.waiting[lane] = len(waiting)
            exploration.totals["launches"] += 1
            exploration.totals["label_runs"] += frontier.label_runs
            exploration.totals["statements"] += frontier.steps
            exploration.totals["interactions"] += frontier.interactions

            if frontier.done is not None:
                if frontier.done.get("limit"):
                    exploration.limits.append(frontier.done["limit"])
                return

            # The process died or was shut down without finishing.
            findings = [] if frontier.started else startup_findings(game, result, log_dir.parent, ROUTES)
            if not findings:
                if result.timed_out:
                    cls, message_id, params, trace = "hang", "finding.hang", {"seconds": int(options.timeout)}, None
                else:
                    cls, message_id, params = "engine-crash", "finding.engine_crash", {"code": result.exit_code}
                    trace = result.output[-4000:] or None
                findings = [Finding(
                    cls, ERROR, message_id, params, frontier.last.get("file"), frontier.last.get("line"),
                    stage=ROUTES, path=list(frontier.path), traceback=trace, possible=frontier.made_up)]
                exploration.totals["paths"] += 1
                exploration.end(cls)
            for finding in findings:
                exploration.collect(finding, lane, launch)
                progress("finding", finding=finding)

            if not waiting and not labels:
                return
            exploration.relaunches += 1
            if exploration.relaunches > MAX_RELAUNCHES:
                exploration.limits.append({
                    "kind": "relaunches", "unexplored": len(waiting), "labels": len(labels or [])})
                return

        # Carry on with the branches the dead process had announced but not started (RUN-012), the
        # story's own before those of label runs (EXP-011), and with the labels not yet started at.
        resume = sorted(waiting, key=lambda branch: (branch[0] or "", branch[1]))
        settings = dict(
            settings, resume=[[label, list(prefix)] for label, prefix in resume], story_done=True,
            label_list=list(labels or []))


def explore_routes(game, options, harness_settings, labels, work_dir, output_dir, report, progress, cancel, partial):
    """Plays the game, exploring its branches (spec 4.3, 4.4). What is found is left in `partial`,
    not yet reported."""
    report.stages[ROUTES]["status"] = "running"
    label_runs = options.labels and options.strategy == "explore"
    labels = list(labels or []) if label_runs else []
    shares = split_labels(labels, options.jobs)
    exploration = partial["exploration"] = Exploration(labels)
    logs = Path(output_dir) / "engine-logs"
    work_dir = Path(work_dir)

    # The story's own process comes first and waits for nothing (EXP-011). With no other process to
    # give them to, it plays the labels too, once the story is explored.
    lanes = [(0, dict(harness_settings, label_list=[] if shares else labels), work_dir, logs)]
    for number, share in enumerate(shares, 1):
        name = "labels-%d" % number
        lanes.append((
            number, dict(harness_settings, label_list=share, story_done=True), work_dir / name, logs / name))
    exploration.jobs = len(lanes)

    def lane(number, settings, lane_work, lane_logs):
        run_lane(number, game, options, settings, exploration, lane_work, lane_logs, progress, cancel)

    in_parallel(lanes, lane, cancel)


def in_parallel(jobs, function, cancel):
    """Runs function(*job) for each job at the same time, and raises the first error any of them raised."""
    if len(jobs) == 1:
        return function(*jobs[0])
    errors = []

    def guarded(job):
        try:
            function(*job)
        except BaseException as error:
            errors.append(error)
            cancel.set()

    threads = [threading.Thread(target=guarded, args=(job,), daemon=True) for job in jobs]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            while thread.is_alive():
                thread.join(0.2)
    except BaseException:
        cancel.set()
        for thread in threads:
            thread.join()
        raise
    if errors:
        raise errors[0]


def finish_routes(game, options, exploration, output_dir, report):
    """Puts what the game processes found into the report, in an order that does not depend on timing."""
    stage = report.stages[ROUTES]
    for _key, finding in sorted(exploration.findings, key=lambda item: item[0]):
        report.add(finding)

    totals = exploration.totals
    stage["status"] = "done"
    stage["paths"] = totals["paths"]
    stage["end_reasons"] = dict(sorted(exploration.reasons.items()))
    stage["launches"] = totals["launches"]
    stage["jobs"] = exploration.jobs
    if exploration.excluded:
        stage["excluded_labels"] = exploration.excluded
    if options.labels and options.strategy == "explore":
        stage["label_runs"] = totals["label_runs"]
    # Now that everything has been played: what real play ran without trouble is not a problem (EXP-012).
    stage["possible_dropped"] = report.drop_unconfirmed(exploration.coverage.executed)

    if exploration.limits:
        limit = {
            "kind": exploration.limits[0]["kind"],
            "unexplored": sum(i.get("unexplored") or 0 for i in exploration.limits),
            "labels": sum(i.get("labels") or 0 for i in exploration.limits)}
        stage["limited"] = limit
        if limit["unexplored"] or not limit["labels"]:
            report.notes.append({
                "message_id": "note.limited." + limit["kind"], "params": {"count": limit["unexplored"]}})
        if limit["labels"]:
            report.notes.append({"message_id": "note.limited.labels", "params": {"count": limit["labels"]}})
    report.coverage = exploration.coverage.report()
    report.statistics.update(statements=totals["statements"], interactions=totals["interactions"])
    collect_engine_files(game, output_dir)
