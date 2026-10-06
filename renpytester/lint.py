"""Turning the engine's lint report into findings (spec 4.6).

Lint is run by the game's own engine (ARCH-003); this module only reads what it wrote. The report
is plain text meant for people, and its layout differs a little between engine versions, so the
parser accepts what it recognises and ignores the rest instead of failing.
"""

import re

from renpytester.model import ERROR, INFO, WARNING, Finding
from renpytester.workspace import PREFIX

STAGE = "lint"

# Options that make lint report more, tried on every engine and dropped where they do not exist.
EXTRA_OPTIONS = ("--all-problems", "--check-unclosed-tags")

PROBLEM = re.compile(r"^(?P<file>\S[^:]*\.rpym?):(?P<line>\d+) (?P<message>.+)$")
SECTION_FILE = re.compile(r"^(?P<file>\S.*\.rpym?):$")
SECTION_ITEM = re.compile(r"^\s+\* line\s+(?P<line>\d+)\s*(?:\(id (?P<id>[^)]+)\))?\s*$")
LANGUAGE = re.compile(r"(?:^|/)tl/(?P<language>[^/]+)/")
QUOTED_CONTEXT = re.compile(r'\s*\(in ".*"\)\s*$')
UNRECOGNISED = re.compile(r"unrecognized arguments: (?P<options>.+)")

SECTIONS = {
    "Unreachable Statements:": ("unreachable", INFO, "finding.unreachable"),
    "Orphan Translations:": ("orphan-translation", INFO, "finding.orphan_translation"),
}

# What each kind of lint message means, most specific first (LINT-001). Lint's exit code is not
# used: it counts informational items as failures. Anything not listed here is a warning.
KINDS = (
    (re.compile(r"[Tt]ext tag|text tags|closing tag"), "bad-text", ERROR),
    (re.compile(r"is not an image|is not a known image|not an image\b"), "undefined-image", ERROR),
    (re.compile(r"is not loadable|could not be loaded|does not exist"), "missing-file", ERROR),
    (re.compile(r"nonexistent label|to non-?existent label|undefined label"), "missing-label", ERROR),
    (re.compile(r"Could not evaluate|is not defined"), "undefined-name", ERROR),
    (re.compile(r"substitut|interpolat"), "bad-text", ERROR),
)

BLOCKS = re.compile(
    r"The (?:game|(?P<language>\S+) translation) contains (?P<blocks>[\d,]+) dialogue blocks?, containing "
    r"(?P<words>[\d,]+) words? and (?P<characters>[\d,]+) characters?")
COUNTS = re.compile(
    r"The game contains (?P<menus>[\d,]+) menus?, (?P<images>[\d,]+) images?, and (?P<screens>[\d,]+) screens?")


def classify(message):
    # Lint quotes the line of dialogue it is talking about; the game's own words must not decide the kind.
    message = QUOTED_CONTEXT.sub("", message)
    for pattern, cls, severity in KINDS:
        if pattern.search(message):
            return cls, severity
    return "lint", WARNING


def language_of(filename):
    match = LANGUAGE.search(filename)
    return match["language"] if match and match["language"] != "None" else None


def number(text):
    return int(text.replace(",", ""))


def parse_statistics(text):
    """Reads the word and block counts from the statistics part of the report (LINT-003)."""
    text = " ".join(text.split())
    statistics = {}
    translations = {}
    for match in BLOCKS.finditer(text):
        counts = {name: number(match[name]) for name in ("blocks", "words", "characters")}
        if match["language"]:
            translations[match["language"]] = counts
        else:
            statistics["dialogue"] = counts
    match = COUNTS.search(text)
    if match:
        statistics.update({name: number(match[name]) for name in ("menus", "images", "screens")})
    if translations:
        statistics["translations"] = translations
    return statistics


def parse(text):
    """Returns (findings, statistics) for a lint report."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    findings = []
    statistics_text = []

    section = None
    section_file = None
    current = None
    in_statistics = False

    for line in lines:
        stripped = line.strip()

        if in_statistics:
            statistics_text.append(stripped)
            continue

        if stripped == "Statistics:":
            in_statistics = True
            current = None
            continue

        if stripped in SECTIONS:
            section, section_file, current = SECTIONS[stripped], None, None
            continue

        if not stripped:
            current = None
            continue

        if section is not None:
            item = SECTION_ITEM.match(line)
            header = SECTION_FILE.match(line)
            if item and section_file:
                cls, severity, message_id = section
                params = {"id": item["id"]} if item["id"] else {}
                findings.append(Finding(
                    cls, severity, message_id, params, section_file, int(item["line"]), stage=STAGE,
                    language=language_of(section_file)))
                continue
            if header:
                section_file = header["file"].replace("\\", "/")
                continue
            if line.startswith(" "):
                continue  # "* and 3 more." and similar.
            section = None  # Anything else at the left margin ends the section.

        problem = PROBLEM.match(line)
        if problem:
            filename = problem["file"].replace("\\", "/")
            cls, severity = classify(problem["message"])
            current = Finding(
                cls, severity, "finding.lint", {"message": problem["message"]}, filename, int(problem["line"]),
                stage=STAGE, language=language_of(filename))
            if PREFIX not in filename:
                findings.append(current)
            continue

        if stripped.startswith("It is advised"):
            current = None  # General advice about the project, not part of the problem above it.
            continue

        if current is not None:
            # A problem's explanation can run over several lines.
            current.params["message"] += " " + stripped
            cls, severity = classify(current.params["message"])
            if current.cls == "lint":
                current.cls, current.severity = cls, severity

    return findings, parse_statistics("\n".join(statistics_text))


def unrecognised_options(output):
    """The lint options this engine rejected, from its error message, or an empty list."""
    match = UNRECOGNISED.search(output)
    return match["options"].split() if match else []
