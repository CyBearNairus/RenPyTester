"""Report writers (spec 4.9).

The JSON report is the record of a run. The JUnit and HTML reports are made from that same data,
not from anything the JSON does not have, so that all three always agree.
"""

from pathlib import Path

from renpytester.i18n import t
from renpytester.model import ERROR, SEVERITIES

# Stage statuses that mean the stage did what it was asked to. Anything else leaves the run incomplete.
FINISHED = ("done", "blocked")
# Stage statuses of stages that were never meant to run.
NOT_ASKED = ("not_selected", "not_implemented")


def message(finding):
    """The sentence shown for a finding of the JSON report, in the current interface language (I18N-004)."""
    return t(finding["message_id"], **finding["params"])


def where(finding):
    if not finding.get("file"):
        return t("console.unknown_location")
    return "%s:%s" % (finding["file"], finding["line"]) if finding.get("line") else finding["file"]


def fails(finding, settings):
    """True if this finding of the JSON report is one that makes the run fail (CLI-003, CLI-004, EXP-013)."""
    fail_on = settings.get("fail_on", ERROR)
    if fail_on == "never" or (finding.get("possible") and not settings.get("fail_on_possible")):
        return False
    return SEVERITIES.index(finding["severity"]) <= SEVERITIES.index(fail_on)


def outcome(data):
    """How the run of a JSON report ended: "incomplete", "failed" or "passed"."""
    if not data.get("complete"):
        return "incomplete"
    if any(fails(finding, data.get("settings") or {}) for finding in data.get("findings") or []):
        return "failed"
    return "passed"


def human_size(count):
    """A number of bytes as a short text, such as "12.4 MB". The units are the same in every language."""
    size = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%d %s" % (size, unit) if unit == "bytes" else "%.1f %s" % (size, unit)
        size /= 1024


def choices(finding):
    """The decisions that led to a finding, as short texts."""
    return [
        t("console.from_label", label=step["choice"]) if step.get("kind") == "label" else str(step["choice"])
        for step in finding.get("path") or [] if step.get("choice") is not None]


def write_all(report, output_dir):
    """Writes the report in every format. Returns the path of each, by format (REP-002, -003, -004, -009)."""
    from renpytester.report import html_report, json_report, junit_report

    data = report.to_dict()
    output_dir = Path(output_dir)
    return {
        "json": json_report.write(report, output_dir),
        "html": html_report.write(data, output_dir / (report.name + ".html")),
        "junit": junit_report.write(data, output_dir / (report.name + ".xml")),
    }
