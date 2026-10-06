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

    @property
    def id(self):
        """Stable across runs and interface languages: the same problem always gets the same id."""
        key = "|".join(str(i) for i in (self.cls, self.file, self.line, sorted(self.params.items())))
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self):
        data = asdict(self)
        data["class"] = data.pop("cls")
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

    def add(self, finding):
        """Adds a finding, merging it with an identical one already present (ERR-010)."""
        for existing in self.findings:
            if existing.id == finding.id:
                existing.count += 1
                if len(finding.path) < len(existing.path):
                    existing.path = finding.path
                return existing
        self.findings.append(finding)
        return finding

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
                twin.also.append({
                    "stage": finding.stage, "class": finding.cls, "message_id": finding.message_id,
                    "params": finding.params})
            else:
                kept.append(finding)
        self.findings = kept

    def count(self, severity):
        return sum(1 for f in self.findings if f.severity == severity)

    def failed(self, fail_on=ERROR):
        """True if any finding is at or above the threshold (CLI-003, CLI-004)."""
        if fail_on == "never":
            return False
        worst = SEVERITIES.index(fail_on)
        return any(SEVERITIES.index(f.severity) <= worst for f in self.findings)

    def to_dict(self):
        order = {name: index for index, name in enumerate(SEVERITIES)}
        findings = sorted(self.findings, key=lambda f: (order[f.severity], f.file or "", f.line or 0, f.cls))
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": {"name": "renpytester", "version": self.tool_version},
            "complete": self.complete,
            "started": self.started,
            "finished": self.finished,
            "game": {"path": self.game_path, "kind": self.game_kind, **self.game},
            "settings": self.settings,
            "stages": self.stages,
            "summary": {name: self.count(name) for name in SEVERITIES},
            "coverage": self.coverage,
            "statistics": self.statistics,
            "notes": self.notes,
            "findings": [f.to_dict() for f in findings],
        }
