"""What a run produces: findings and the report that holds them (spec 4.5, 4.9)."""

import hashlib
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1

ERROR = "error"
WARNING = "warning"
INFO = "info"
SEVERITIES = (ERROR, WARNING, INFO)


@dataclass
class Finding:
    """One reported problem. The text is kept as an identifier plus parameters (I18N-004)."""

    cls: str
    severity: str
    message_id: str
    params: dict = field(default_factory=dict)
    file: str | None = None
    line: int | None = None
    label: str | None = None
    stage: str | None = None
    language: str | None = None
    path: list = field(default_factory=list)
    traceback: str | None = None
    count: int = 1
    # The same problem as seen by other stages: each entry has stage, class, message_id and params (LINT-002).
    also: list = field(default_factory=list)
    # True when the problem was only seen in a game state the tool made up: in a label run, or after
    # skipping an interaction it could not play. A real player may never reach it (RUN-021, EXP-013).
    possible: bool = False
    # The statement the problem was seen at, as the harness names it. Not part of the report.
    node: str | None = None

    @property
    def id(self):
        """Stable across runs and interface languages: the same problem always gets the same id."""
        key = "|".join(str(i) for i in (self.cls, self.file, self.line, sorted(self.params.items())))
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self):
        data = asdict(self)
        data["class"] = data.pop("cls")
        del data["node"]
        return {"id": self.id, **data}


@dataclass
class Report:
    tool_version: str
    game_path: str
    game_kind: str | None = None
    game: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    coverage: dict | None = None
    statistics: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    complete: bool = False
    started: str | None = None
    finished: str | None = None
    # File name, without extension, that this run's report and log folder are saved under (REP-009).
    name: str = "report"
    # True when the user stopped the run before it finished (CLI-006).
    interrupted: bool = False
    # Findings left out because an ignore rule matched them, in all and for each rule (CFG-003).
    ignored: int = 0
    ignored_by: list = field(default_factory=list)
    # Findings left out because the baseline report already had them; None when no baseline was given (REP-007).
    known: int | None = None
    # The findings by their id, for add(). Rebuilt there whenever the list was changed by other means.
    _by_id: dict = field(default_factory=dict, repr=False, compare=False)

    def add(self, finding):
        """Adds a finding, merging it with an identical one already present (ERR-010)."""
        # A half-translated game has a finding for every line with no translation, in every language:
        # too many to compare each new one with all the others.
        if len(self._by_id) != len(self.findings):
            self._by_id = {existing.id: existing for existing in self.findings}
        key = finding.id
        existing = self._by_id.get(key)
        if existing is not None:
            existing.count += 1
            # Seen once in a real state is enough to confirm it (EXP-012).
            existing.possible = existing.possible and finding.possible
            existing.node = existing.node or finding.node
            if len(finding.path) < len(existing.path):
                existing.path = finding.path
            return existing
        self.findings.append(finding)
        self._by_id[key] = finding
        return finding

    def drop_unconfirmed(self, executed):
        """Removes possible issues at statements that real play ran without that problem (EXP-012).

        `executed` holds the statements played in a real state. A problem seen at one of them only in
        a made-up state comes from the made-up state, not from the game. Returns how many were removed.
        """
        real = set(f.node for f in self.findings if not f.possible and f.node)
        kept = [f for f in self.findings if not (f.possible and f.node in executed and f.node not in real)]
        dropped = len(self.findings) - len(kept)
        self.findings = kept
        return dropped

    def merge_stages(self):
        """Folds a static finding into a finding another stage made at the same place (LINT-002, ERR-010).

        Lint and a playthrough often report one mistake twice: lint from reading the line, the
        playthrough from crashing on it. The playthrough's finding is kept, because it carries the
        path and the traceback, and lint's wording is attached to it.
        """
        played = {(f.file, f.line): f for f in self.findings if f.stage != "lint" and f.severity == ERROR and f.file}
        kept = []
        for finding in self.findings:
            twin = played.get((finding.file, finding.line))
            if finding.stage == "lint" and finding.severity == ERROR and twin is not None:
                twin.possible = False  # Lint read it straight from the script: it is real.
                twin.also.append({
                    "stage": finding.stage, "class": finding.cls, "message_id": finding.message_id,
                    "params": finding.params})
            else:
                kept.append(finding)

        # A translation that names a variable the original does not is seen twice in the same way: by
        # reading it, and when it fails as its line is played (TL-004, TL-006). The failure is kept.
        failed = {(f.file, f.line, f.language): f for f in kept if f.cls == "bad-interpolation" and f.file}
        self.findings = []
        for finding in kept:
            twin = failed.get((finding.file, finding.line, finding.language))
            if finding.cls == "variable-mismatch" and twin is not None:
                twin.also.append({
                    "stage": finding.stage, "class": finding.cls, "message_id": finding.message_id,
                    "params": finding.params})
            else:
                self.findings.append(finding)

    def set_severities(self, severities):
        """Gives the findings of some classes the severity the config file asks for (TL-005, CFG-007)."""
        for finding in self.findings:
            if finding.cls in severities:
                finding.severity = severities[finding.cls]

    def ignore(self, rules):
        """Takes out the findings that an ignore rule of the config file matches, and counts them:
        they are left out of the list, never out of the sums (CFG-003)."""
        counts = [0] * len(rules)
        kept = []
        for finding in self.findings:
            matched = next((index for index, rule in enumerate(rules) if rule.matches(finding)), None)
            if matched is None:
                kept.append(finding)
            else:
                counts[matched] += 1
        self.findings = kept
        self.ignored = sum(counts)
        self.ignored_by = [{"rule": rule.to_dict(), "count": count} for rule, count in zip(rules, counts)]

    def leave_out_known(self, known):
        """Takes out the findings an earlier report already had, by their ids, and counts them (REP-007)."""
        kept = [finding for finding in self.findings if finding.id not in known]
        self.known = len(self.findings) - len(kept)
        self.findings = kept

    def count(self, severity):
        """Confirmed findings of one severity. Possible issues are counted apart (EXP-013)."""
        return sum(1 for f in self.findings if f.severity == severity and not f.possible)

    def count_possible(self):
        return sum(1 for f in self.findings if f.possible)

    def failed(self, fail_on=ERROR, fail_on_possible=False):
        """True if any finding is at or above the threshold (CLI-003, CLI-004)."""
        if fail_on == "never":
            return False
        worst = SEVERITIES.index(fail_on)
        counted = [f for f in self.findings if fail_on_possible or not f.possible]
        return any(SEVERITIES.index(f.severity) <= worst for f in counted)

    def to_dict(self):
        order = {name: index for index, name in enumerate(SEVERITIES)}
        findings = sorted(
            self.findings,
            key=lambda f: (f.possible, order[f.severity], f.file or "", f.line or 0, f.cls, f.language or ""))
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": {"name": "renpytester", "version": self.tool_version},
            "complete": self.complete,
            "interrupted": self.interrupted,
            "name": self.name,
            "started": self.started,
            "finished": self.finished,
            "game": {"path": self.game_path, "kind": self.game_kind, **self.game},
            "settings": self.settings,
            "stages": self.stages,
            "summary": {
                **{name: self.count(name) for name in SEVERITIES}, "possible": self.count_possible(),
                "ignored": self.ignored, "known": self.known},
            "ignored_by": self.ignored_by,
            "coverage": self.coverage,
            "statistics": self.statistics,
            "notes": self.notes,
            "findings": [f.to_dict() for f in findings],
        }
