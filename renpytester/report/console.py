"""Terminal output: live progress, then a summary (spec REP-001, REP-006)."""

import os
import sys
import time

from renpytester.i18n import t
from renpytester.model import ERROR, INFO, SEVERITIES, WARNING

COLOURS = {ERROR: "31", WARNING: "33", INFO: "36", "ok": "32", "dim": "2", "bold": "1"}


def message(finding):
    """The sentence shown for a finding, in the current interface language (I18N-004)."""
    return t(finding.message_id, **finding.params)


def where(finding):
    if not finding.file:
        return t("console.unknown_location")
    return "%s:%s" % (finding.file, finding.line) if finding.line else finding.file


class Console:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.live = self.stream.isatty()
        self.colour = self.live and "NO_COLOR" not in os.environ
        if self.colour and sys.platform == "win32":
            os.system("")  # Switches the Windows console into a mode that understands colour codes.
        self.bar_shown = False
        self.last_line = time.monotonic()
        self.findings = 0
        self.stage = ""

    def paint(self, text, colour):
        return "\033[%sm%s\033[0m" % (COLOURS[colour], text) if self.colour else text

    def write(self, text=""):
        self.clear_bar()
        self.stream.write(text + "\n")
        self.stream.flush()

    def clear_bar(self):
        if self.bar_shown:
            self.stream.write("\r\033[K")
            self.bar_shown = False

    # ------------------------------------------------------------------------------ progress

    def progress(self, kind, **data):
        if kind == "game":
            game = data["game"]
            self.write(t("console.game", name=game.get("name") or "?", version=game.get("version") or "").rstrip())
            self.write(t("console.engine", renpy=game.get("renpy_version") or "?", kind=t("kind." + data["game_kind"])))
            languages = game.get("languages") or []
            self.write(t("console.languages", count=len(languages), names=", ".join(languages) or "-"))
        elif kind == "stage":
            self.stage = t("console.stage." + data["name"])
            self.status(self.stage, force=True)
        elif kind == "note":
            self.write(t(data["message_id"], **data["params"]))
        elif kind == "finding":
            self.findings += 1
        elif kind == "step":
            self.status(t(
                "console.progress", paths=data.get("paths") or 0, waiting=data.get("waiting") or 0,
                percent=data.get("percent") or 0, findings=self.findings))

    def status(self, text, force=False):
        if self.live:
            self.stream.write("\r\033[K" + text[:100])
            self.stream.flush()
            self.bar_shown = True
        elif force or time.monotonic() - self.last_line > 5:
            # Not a terminal (a CI log): occasional plain lines instead of a bar.
            self.last_line = time.monotonic()
            self.write(text)

    # ------------------------------------------------------------------------------- summary

    def listing(self, findings):
        for finding in sorted(findings, key=lambda f: (f.file or "", f.line or 0)):
            self.write("  %s  %s" % (self.paint(where(finding), "bold"), message(finding)))
            if finding.label:
                self.write("      " + self.paint(t("console.in_label", label=finding.label), "dim"))
            choices = [str(step.get("choice")) for step in finding.path if step.get("choice") is not None]
            if choices:
                shown = " > ".join(choices[-8:])
                if len(choices) > 8:
                    shown = "... " + shown
                self.write("      " + self.paint(t("console.path", path=shown), "dim"))
            if finding.count > 1:
                self.write("      " + self.paint(t("console.count", count=finding.count), "dim"))
            for other in finding.also:
                text = t("console.also", stage=other["stage"], message=t(other["message_id"], **other["params"]))
                self.write("      " + self.paint(text, "dim"))
        self.write()

    def summary(self, report, json_path, failed):
        self.write()
        for severity in SEVERITIES:
            findings = [f for f in report.findings if f.severity == severity and not f.possible]
            if findings:
                self.write(self.paint(t("severity.%s.title" % severity, count=len(findings)), severity))
                self.listing(findings)

        possible = [f for f in report.findings if f.possible]
        if possible:
            self.write(self.paint(t("console.possible.title", count=len(possible)), WARNING))
            self.write(self.paint("  " + t("console.possible.why"), "dim"))
            self.listing(possible)

        for note in report.notes:
            if note["message_id"] != "note.repaired":
                self.write(t(note["message_id"], **note["params"]))

        if report.coverage and report.coverage.get("total"):
            executed, total = report.coverage["executed"], report.coverage["total"]
            self.write(t("console.coverage", executed=executed, total=total, percent=round(100 * executed / total)))
            if report.coverage.get("low_confidence"):
                self.write(t("console.coverage_low", count=report.coverage["low_confidence"]))
            unreached = report.coverage.get("unreached_labels") or []
            if unreached:
                shown = ", ".join(unreached[:12]) + (", ..." if len(unreached) > 12 else "")
                self.write(t("console.unreached", count=len(unreached), labels=shown))
            routes = report.stages.get("routes", {})
            if routes.get("paths"):
                self.write(t("console.paths", paths=routes["paths"]))

        script = report.statistics.get("script", {})
        if script.get("dialogue"):
            self.write(t(
                "console.script", words=script["dialogue"]["words"], blocks=script["dialogue"]["blocks"],
                menus=script.get("menus", 0), languages=len(script.get("translations", {}))))

        not_run = [name for name, stage in report.stages.items() if stage["status"] == "not_implemented"]
        if not_run:
            self.write(self.paint(t("console.not_checked", stages=", ".join(not_run)), "dim"))

        counts = t("console.totals", errors=report.count(ERROR), warnings=report.count(WARNING),
                   infos=report.count(INFO))
        if report.count_possible():
            counts += ", " + t("console.totals_possible", count=report.count_possible())
        if not report.complete:
            self.write(self.paint(t("console.incomplete") + "  " + counts, ERROR))
        elif failed:
            self.write(self.paint(t("console.failed") + "  " + counts, ERROR))
        else:
            self.write(self.paint(t("console.passed") + "  " + counts, "ok"))
        self.write(t("console.report", path=str(json_path)))
