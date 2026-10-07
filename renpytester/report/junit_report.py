"""The JUnit XML report, for CI systems that show test results (spec REP-003).

One test suite per stage, one test case per finding. A finding that makes the run fail is a failed
test. A finding that does not, such as a warning or a possible issue under the default settings,
is a skipped test: CI systems list those with their message, without failing the build.
Each stage also has a test case of its own, which is in error when the stage did not finish, so
that a run that checked nothing is never shown as a run that passed (NFR-002).

Names and attributes are the same in every interface language (I18N-003); only the messages are
in the language of the run.
"""

import datetime
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from renpytester.i18n import t
from renpytester.report import FINISHED, NOT_ASKED, choices, fails, message, where

# Characters XML 1.0 does not allow, which a traceback or a game's text may contain.
NOT_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def clean(text):
    return NOT_XML.sub("?", str(text))


def details(finding):
    lines = [where(finding), message(finding)]
    if finding.get("label"):
        lines.append(t("console.in_label", label=finding["label"]))
    path = choices(finding)
    if path:
        lines.append(t("console.path", path=" > ".join(path)))
    for other in finding.get("also") or []:
        lines.append(t("console.also", stage=other["stage"], message=t(other["message_id"], **other["params"])))
    if finding.get("traceback"):
        lines.extend(["", finding["traceback"]])
    return clean("\n".join(lines))


def seconds(data):
    try:
        started, finished = (datetime.datetime.fromisoformat(data[name]) for name in ("started", "finished"))
        return max((finished - started).total_seconds(), 0.0)
    except (KeyError, TypeError, ValueError):
        return 0.0


def render(data):
    """Returns the JUnit XML for a JSON report, as text."""
    settings = data.get("settings") or {}
    root = ElementTree.Element("testsuites", name="renpytester", time="%.3f" % seconds(data))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    for stage, state in (data.get("stages") or {}).items():
        if state.get("status") in NOT_ASKED:
            continue
        counts = {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}
        suite = ElementTree.SubElement(root, "testsuite", name="renpytester." + stage)
        if data.get("started"):
            suite.set("timestamp", data["started"][:19])

        # The stage itself: did it do what it was asked to?
        case = ElementTree.SubElement(suite, "testcase", classname="renpytester." + stage, name="stage " + stage)
        if state.get("status") not in FINISHED:
            counts["errors"] += 1
            error = ElementTree.SubElement(
                case, "error", type=str(state.get("status")), message=clean(t("junit.stage_unfinished", stage=stage)))
            error.text = clean(state.get("reason") or state.get("status"))

        for finding in data.get("findings") or []:
            if finding.get("stage") != stage:
                continue
            counts["tests"] += 1
            name = "%s %s [%s]" % (finding["class"], finding.get("file") or "-", finding["id"])
            if finding.get("line"):
                name = "%s %s:%s [%s]" % (finding["class"], finding["file"], finding["line"], finding["id"])
            case = ElementTree.SubElement(suite, "testcase", classname="renpytester." + stage, name=clean(name))
            properties = ElementTree.SubElement(case, "properties")
            for key in ("id", "severity", "possible", "language"):
                if finding.get(key) is not None:
                    value = str(finding[key]).lower() if isinstance(finding[key], bool) else str(finding[key])
                    ElementTree.SubElement(properties, "property", name=key, value=clean(value))
            if fails(finding, settings):
                counts["failures"] += 1
                result = ElementTree.SubElement(case, "failure", type=finding["class"], message=clean(message(finding)))
                result.text = details(finding)
            else:
                counts["skipped"] += 1
                kind = "possible" if finding.get("possible") else finding["severity"]
                ElementTree.SubElement(case, "skipped", message=clean("%s: %s" % (kind, message(finding))))
                ElementTree.SubElement(case, "system-out").text = details(finding)

        for key, value in counts.items():
            suite.set(key, str(value))
            totals[key] += value

    for key, value in totals.items():
        root.set(key, str(value))
    ElementTree.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"


def write(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(data), encoding="utf-8")
    return path
