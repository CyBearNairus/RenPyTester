"""The HTML report: one file, readable with no internet connection (spec REP-004).

It is written for the game's developer. The first screen says whether the run passed and gives the
sums; below it come the confirmed findings, grouped by script file, and then the possible issues
by themselves. Each finding is one line that opens to show how the game got there and the
engine's traceback. Everything the game or the engine wrote is escaped: it is shown, never run.
"""

import html
from pathlib import Path

from renpytester import i18n, palette
from renpytester.i18n import t
from renpytester.model import ERROR, INFO, SEVERITIES, WARNING
from renpytester.report import NOT_ASKED, choices, human_size, message, outcome

# The colours are the window's too, and are kept in one place for both (GUI-015).
STYLE = """
:root { %s }
@media (prefers-color-scheme: dark) { :root { %s } }
""" % (palette.css_variables(palette.LIGHT), palette.css_variables(palette.DARK)) + """
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.5 system-ui, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0; }
h2 { font-size: 17px; margin: 32px 0 8px; }
h3 { font-size: 14px; margin: 20px 0 6px; font-family: ui-monospace, Consolas, monospace; overflow-wrap: anywhere; }
p { margin: 6px 0; }
.soft { color: var(--soft); }
.head { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 16px; }
.result { font-weight: 700; padding: 4px 14px; border-radius: 999px; border: 2px solid currentColor; }
.result.passed { color: var(--ok); } .result.failed, .result.incomplete { color: var(--error); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 18px 0 8px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; }
.card b { display: block; font-size: 24px; line-height: 1.2; }
.card.error b { color: var(--error); } .card.warning b { color: var(--warning); }
.card.info b { color: var(--info); } .card.possible b { color: var(--possible); }
table { border-collapse: collapse; width: 100%; background: var(--card); border: 1px solid var(--line); }
th, td { text-align: left; padding: 6px 12px; border-bottom: 1px solid var(--line); }
th { font-size: 13px; color: var(--soft); font-weight: 600; }
.scroll { overflow-x: auto; }
.filters { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; margin: 12px 0;
  padding: 10px 14px; background: var(--card); border: 1px solid var(--line); border-radius: 8px; }
.filters label { white-space: nowrap; }
select { font: inherit; padding: 2px 6px; }
details.finding { background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--line);
  border-radius: 6px; margin: 6px 0; }
details.finding.error { border-left-color: var(--error); }
details.finding.warning { border-left-color: var(--warning); }
details.finding.info { border-left-color: var(--info); }
details.finding > summary { cursor: pointer; padding: 8px 12px; overflow-wrap: anywhere; }
.tag { font-size: 12px; font-weight: 700; text-transform: uppercase; margin-right: 8px; }
.tag.error { color: var(--error); } .tag.warning { color: var(--warning); } .tag.info { color: var(--info); }
.line { font-family: ui-monospace, Consolas, monospace; margin-right: 8px; color: var(--soft); }
.body { padding: 4px 12px 12px 28px; border-top: 1px solid var(--line); }
.body dl { display: grid; grid-template-columns: max-content 1fr; gap: 2px 14px; margin: 8px 0; }
.body dt { color: var(--soft); } .body dd { margin: 0; overflow-wrap: anywhere; }
.body ol { margin: 4px 0; padding-left: 22px; }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 6px; padding: 10px; overflow-x: auto;
  font: 12.5px/1.45 ui-monospace, Consolas, monospace; margin: 8px 0 0; }
[hidden] { display: none !important; }
footer { margin-top: 36px; font-size: 13px; }
"""

# Shows only the findings the filters ask for, and hides a file's heading when none of its findings are shown.
SCRIPT = """
(function () {
  var boxes = document.querySelectorAll('.filters input[type=checkbox]');
  var stage = document.getElementById('filter-stage');
  var language = document.getElementById('filter-language');
  function apply() {
    var shown = {};
    boxes.forEach(function (box) { shown[box.value] = box.checked; });
    document.querySelectorAll('details.finding').forEach(function (item) {
      var visible = shown[item.dataset.severity] !== false
        && (!stage || !stage.value || item.dataset.stage === stage.value)
        && (!language || !language.value || item.dataset.language === language.value);
      item.hidden = !visible;
    });
    document.querySelectorAll('section.file').forEach(function (group) {
      group.hidden = !group.querySelector('details.finding:not([hidden])');
    });
    var none = document.getElementById('nothing-shown');
    if (none) { none.hidden = !!document.querySelector('details.finding:not([hidden])')
      || !document.querySelector('details.finding'); }
  }
  boxes.forEach(function (box) { box.addEventListener('change', apply); });
  [stage, language].forEach(function (list) { if (list) { list.addEventListener('change', apply); } });
  apply();
})();
"""


def e(value):
    return html.escape(str(value), quote=True)


def finding_block(finding):
    severity = finding["severity"]
    rows = []
    if finding.get("label"):
        rows.append((t("html.label"), e(finding["label"])))
    rows.append((t("html.stage"), e(finding.get("stage") or "-")))
    if finding.get("language"):
        rows.append((t("html.language"), e(finding["language"])))
    if finding.get("count", 1) > 1:
        rows.append((t("html.count"), e(finding["count"])))
    for other in finding.get("also") or []:
        rows.append((t("html.also", stage=other["stage"]), e(t(other["message_id"], **other["params"]))))

    parts = ["<dl>%s</dl>" % "".join("<dt>%s</dt><dd>%s</dd>" % (e(name), value) for name, value in rows)]
    path = choices(finding)
    if path:
        parts.append("<p class=\"soft\">%s</p><ol>%s</ol>" % (
            e(t("html.path")), "".join("<li>%s</li>" % e(step) for step in path)))
    if finding.get("traceback"):
        parts.append("<p class=\"soft\">%s</p><pre>%s</pre>" % (e(t("html.traceback")), e(finding["traceback"])))

    line = "<span class=\"line\">%s</span>" % e(t("html.line", line=finding["line"])) if finding.get("line") else ""
    return (
        "<details class=\"finding %s\" data-severity=\"%s\" data-stage=\"%s\" data-language=\"%s\">"
        "<summary><span class=\"tag %s\">%s</span>%s%s</summary><div class=\"body\">%s</div></details>" % (
            e(severity), e(severity), e(finding.get("stage") or ""), e(finding.get("language") or ""),
            e(severity), e(t("html.severity." + severity)), line, e(message(finding)), "".join(parts)))


def by_file(findings):
    """The findings as sections, one per script file, in the order of the file names."""
    groups = {}
    for finding in findings:
        groups.setdefault(finding.get("file") or "", []).append(finding)
    sections = []
    for name in sorted(groups):
        items = sorted(groups[name], key=lambda f: (f.get("line") or 0, SEVERITIES.index(f["severity"])))
        sections.append("<section class=\"file\"><h3>%s <span class=\"soft\">(%d)</span></h3>%s</section>" % (
            e(name or t("console.unknown_location")), len(items), "".join(finding_block(f) for f in items)))
    return "".join(sections)


def summary_cards(data):
    summary = data.get("summary") or {}
    cards = [
        ("error", summary.get(ERROR, 0), t("html.errors")), ("warning", summary.get(WARNING, 0), t("html.warnings")),
        ("info", summary.get(INFO, 0), t("html.notes")), ("possible", summary.get("possible", 0), t("html.possible"))]
    coverage = data.get("coverage") or {}
    if coverage.get("total"):
        percent = round(100 * coverage["executed"] / coverage["total"])
        cards.append(("", "%d%%" % percent, t(
            "html.coverage", executed=coverage["executed"], total=coverage["total"])))
    paths = (data.get("stages") or {}).get("routes", {}).get("paths")
    if paths:
        cards.append(("", paths, t("html.paths")))
    return "<div class=\"cards\">%s</div>" % "".join(
        "<div class=\"card %s\"><b>%s</b>%s</div>" % (kind, e(value), e(label)) for kind, value, label in cards)


def translations_table(data):
    languages = (data.get("stages") or {}).get("translations", {}).get("languages") or {}
    if not languages:
        return ""
    problems = {}
    for finding in data.get("findings") or []:
        if finding.get("stage") == "translations" and finding.get("language"):
            problems[finding["language"]] = problems.get(finding["language"], 0) + 1
    rows = []
    for name, language in languages.items():
        dialogue, strings = language["dialogue"], language["strings"]
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            e(name), e(t("html.of", done=dialogue["translated"], total=dialogue["total"])),
            e(t("html.of", done=strings["translated"], total=strings["total"])),
            e(t("html.yes") if language.get("switched") else t("html.no")), e(problems.get(name, 0))))
    head = "".join("<th>%s</th>" % e(t(key)) for key in (
        "html.language", "html.tl_dialogue", "html.tl_strings", "html.tl_switched", "html.tl_problems"))
    return "<h2>%s</h2><div class=\"scroll\"><table><tr>%s</tr>%s</table></div>" % (
        e(t("html.translations")), head, "".join(rows))


def remarks(data):
    """Things worth knowing that are not findings: notes, what was left out, what was not checked."""
    lines = [t(note["message_id"], **note["params"]) for note in data.get("notes") or []]
    summary = data.get("summary") or {}
    box = data.get("sandbox")
    if box:
        lines.append(t(
            "console.sandbox", path=box["path"], size=human_size(box["bytes"]), files=box["files"],
            copied=box["copied"], removed=box["removed"]))
    if summary.get("ignored"):
        lines.append(t("console.ignored", count=summary["ignored"]))
    if summary.get("known"):
        lines.append(t("console.known", count=summary["known"]))
    coverage = data.get("coverage") or {}
    if coverage.get("low_confidence"):
        lines.append(t("console.coverage_low", count=coverage["low_confidence"]))
    unreached = coverage.get("unreached_labels") or []
    if unreached:
        lines.append(t("console.unreached", count=len(unreached), labels=", ".join(unreached)))
    unfinished = [
        "%s (%s)" % (name, stage.get("status")) for name, stage in (data.get("stages") or {}).items()
        if stage.get("status") not in NOT_ASKED and stage.get("status") not in ("done", "blocked")]
    if unfinished:
        lines.append(t("html.unfinished", stages=", ".join(unfinished)))
    not_built = [name for name, stage in (data.get("stages") or {}).items() if stage.get("status") == "not_implemented"]
    if not_built:
        lines.append(t("console.not_checked", stages=", ".join(not_built)))
    if not lines:
        return ""
    return "<h2>%s</h2>%s" % (e(t("html.remarks")), "".join("<p>%s</p>" % e(line) for line in lines))


def filters(findings):
    if not findings:
        return ""
    parts = ["<span class=\"soft\">%s</span>" % e(t("html.filter.show"))]
    for severity in SEVERITIES:
        parts.append("<label><input type=\"checkbox\" value=\"%s\" checked> %s</label>" % (
            severity, e(t("html.severity." + severity))))
    for key, field in (("stage", "stage"), ("language", "language")):
        values = sorted({finding.get(field) for finding in findings if finding.get(field)})
        if values:
            options = "".join("<option value=\"%s\">%s</option>" % (e(value), e(value)) for value in values)
            parts.append("<label>%s <select id=\"filter-%s\"><option value=\"\">%s</option>%s</select></label>" % (
                e(t("html.filter." + key)), key, e(t("html.filter.all")), options))
    return "<div class=\"filters\">%s</div><p id=\"nothing-shown\" class=\"soft\" hidden>%s</p>" % (
        "".join(parts), e(t("html.filter.nothing")))


def render(data):
    """Returns the HTML page for a JSON report, as text, in the current interface language."""
    game = data.get("game") or {}
    findings = data.get("findings") or []
    confirmed = [finding for finding in findings if not finding.get("possible")]
    possible = [finding for finding in findings if finding.get("possible")]
    result = outcome(data)
    name = game.get("name") or Path(game.get("path") or "").name
    title = " ".join(part for part in (name, game.get("version")) if part)

    body = [
        "<div class=\"head\"><h1>%s</h1><span class=\"result %s\">%s</span></div>" % (
            e(title), result, e(t("console." + result))),
        "<p class=\"soft\">%s</p>" % e(t(
            "html.about", renpy=game.get("renpy_version") or "?", when=(data.get("finished") or "")[:19].replace(
                "T", " "), path=game.get("path") or "")),
        summary_cards(data), translations_table(data), remarks(data), filters(findings),
        "<h2>%s</h2>" % e(t("html.findings", count=len(confirmed))),
        by_file(confirmed) if confirmed else "<p class=\"soft\">%s</p>" % e(t("html.no_findings")),
    ]
    if possible:
        body.append("<h2>%s</h2><p class=\"soft\">%s</p>%s" % (
            e(t("console.possible.title", count=len(possible))), e(t("console.possible.why")), by_file(possible)))
    tool = data.get("tool") or {}
    settings = data.get("settings") or {}
    body.append("<footer class=\"soft\">%s</footer>" % e(t(
        "html.footer", version=tool.get("version") or "?", seed=settings.get("seed"),
        stages=", ".join(settings.get("stages") or []))))

    return (
        "<!DOCTYPE html>\n<html lang=\"%s\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>%s</title>\n"
        "<style>%s</style>\n</head>\n<body>\n<main>\n%s\n</main>\n<script>%s</script>\n</body>\n</html>\n" % (
            e(i18n.get_language()), e(t("html.title", game=title)), STYLE, "\n".join(part for part in body if part),
            SCRIPT))


def write(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(data), encoding="utf-8")
    return path
