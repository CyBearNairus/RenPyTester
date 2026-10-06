"""Bookkeeping for the routes stage: what has been covered, and what is still waiting to be explored.

The harness explores inside the game process (spec ARCH-008). This side only adds up what the
harness reports, possibly from several processes one after another, and remembers which branches
were announced but never started, so that they can be handed to a new process if one dies (RUN-012).
"""

DECISION_FIELDS = ("kind", "file", "line", "choice", "index")


class Coverage:
    """Statement coverage, merged from any number of engine processes (EXP-005)."""

    def __init__(self):
        self.files = {}
        self.labels = {}
        self.executed = set()
        # Statements reached only in a state the tool made up, after a skipped interaction (EXP-014).
        self.low = set()

    def add_map(self, script_map):
        for filename, ids in script_map.get("files", {}).items():
            self.files.setdefault(filename, set()).update(ids)
        for name, label in script_map.get("labels", {}).items():
            entry = self.labels.setdefault(name, {"file": label["file"], "line": label["line"], "ids": set()})
            entry["ids"].update(label["ids"])

    def add_executed(self, ids, low=()):
        self.executed.update(ids or ())
        self.low.update(low or ())

    @property
    def low_count(self):
        return sum(len((ids & self.low) - self.executed) for ids in self.files.values())

    @property
    def total(self):
        return sum(len(ids) for ids in self.files.values())

    @property
    def count(self):
        return sum(len(ids & self.executed) for ids in self.files.values())

    def percent(self):
        return round(100 * self.count / self.total) if self.total else 0

    def report(self):
        if not self.files:
            return None
        labels = {}
        for name, label in self.labels.items():
            labels[name] = {
                "file": label["file"], "line": label["line"], "executed": len(label["ids"] & self.executed),
                "low_confidence": len((label["ids"] & self.low) - self.executed), "total": len(label["ids"])}
        unreached = sorted(
            (name for name, label in labels.items() if not label["executed"] and not label["low_confidence"]),
            key=lambda name: (labels[name]["file"], labels[name]["line"]))
        return {
            "executed": self.count,
            "low_confidence": self.low_count,
            "total": self.total,
            "files": {f: [len(ids & self.executed), len(ids)] for f, ids in sorted(self.files.items())},
            "labels": dict(sorted(labels.items())),
            "unreached_labels": unreached,
        }


class Frontier:
    """Follows one engine process through its event stream."""

    def __init__(self, coverage, waiting=()):
        self.coverage = coverage
        # Branches announced but not yet started, as tuples of decision indices from the game's start.
        self.waiting = set(tuple(i) for i in waiting)
        # The decisions of the path being played right now.
        self.path = []
        self.last = {}
        self.reasons = {}
        self.paths = 0
        self.steps = 0
        self.interactions = 0
        self.started = False
        self.done = None

    def feed(self, event):
        kind = event["ev"]
        if "covered" in event:
            self.coverage.add_executed(event["covered"], event.get("covered_low"))
        if event.get("steps") is not None:
            self.steps = event["steps"]

        if kind == "start":
            self.started = True
            self.coverage.add_map(event.get("map") or {})
        elif kind == "decision":
            self.path.append({name: event.get(name) for name in DECISION_FIELDS})
            self.last = {"file": event.get("file"), "line": event.get("line")}
        elif kind == "heartbeat":
            self.last = {"file": event.get("file"), "line": event.get("line")}
        elif kind == "branch":
            self.waiting.add(tuple(event["prefix"]))
        elif kind == "branch_start":
            self.waiting.discard(tuple(event["prefix"]))
            self.path = [{name: step.get(name) for name in DECISION_FIELDS} for step in event.get("path") or []]
        elif kind == "path_end":
            self.paths += 1
            self.reasons[event["reason"]] = self.reasons.get(event["reason"], 0) + 1
            self.path = []
        elif kind == "done":
            self.done = event
            self.interactions = event.get("interactions") or 0
