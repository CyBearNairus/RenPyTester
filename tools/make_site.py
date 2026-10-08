"""Write the project's home page, docs/index.html (spec DIST-010).

    python tools/make_site.py

GitHub Pages serves the docs/ folder of the main branch as https://cybearnairus.github.io/RenPyTester/,
so the page is live once the file this writes has been pushed. Run it again after changing the
page here, the palette or the icon, and commit what it writes: a test fails when the two differ.
The page takes its colours from renpytester/palette.py, as the report and the window do, and its
pictures are the README's.
"""

import base64
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from renpytester import __author__, __url__, palette  # noqa: E402

PAGE = ROOT / "docs" / "index.html"
ADDRESS = "https://cybearnairus.github.io/RenPyTester/"
RELEASE = __url__ + "/releases/latest"
TAGLINE = "Plays through a Ren'Py game by itself and tells you what is broken."

STYLE = """
:root { %s }
@media (prefers-color-scheme: dark) { :root { %s } }
""" % (palette.css_variables(palette.LIGHT), palette.css_variables(palette.DARK)) + """
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 17px/1.6 system-ui, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 48px 16px 64px; }
header { display: flex; align-items: center; gap: 16px; }
header img { width: 64px; height: 64px; }
h1 { font-size: 34px; line-height: 1.2; margin: 0; }
h2 { font-size: 22px; margin: 48px 0 8px; }
p { margin: 12px 0; }
.lead { font-size: 21px; margin: 24px 0; }
.soft { color: var(--soft); }
a { color: var(--accent); }
.button { display: inline-block; background: var(--accent); color: var(--accent-ink); padding: 12px 24px;
  border-radius: 8px; text-decoration: none; font-weight: 600; margin-right: 16px; }
.button:hover { background: var(--accent-hover); }
figure { margin: 24px 0; }
figure img { display: block; max-width: 100%; height: auto; margin: 0 auto; border: 1px solid var(--line);
  border-radius: 8px; }
figcaption { color: var(--soft); font-size: 15px; text-align: center; margin-top: 8px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; background: var(--card); }
th, td { text-align: left; padding: 8px 12px; border: 1px solid var(--line); }
code { background: var(--code); padding: 2px 6px; border-radius: 4px; font: 15px ui-monospace, Consolas, monospace; }
ul { padding-left: 24px; }
footer { margin-top: 56px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--soft); font-size: 15px; }
"""

BODY = """
<header>
<img src="%(icon)s" alt="">
<h1>RenPyTester</h1>
</header>

<p class="lead">RenPyTester plays through a Ren'Py game by itself and tells you what is broken: crashes, missing
pictures and sounds, broken translations and broken menu screens, each with the file and line where it happened.</p>

<p><a class="button" href="%(release)s">Download</a> <a href="%(url)s">Source and instructions on GitHub</a></p>

<figure>
<img src="images/window.png" width="840" height="618" alt="The RenPyTester window after testing a game">
<figcaption>The window after testing The Question, the small game that comes with Ren'Py.</figcaption>
</figure>

<h2>What it does</h2>
<p>You give it the folder of a game; it does the rest.
It makes every choice of every menu, and then plays each label by itself, to reach what the story never reaches.
No window of the game appears while it works, no sound plays, and the game's folder is left exactly as it was.</p>
<p>It works on any Ren'Py 8 game, finished or still being made, in a window or from a terminal or a build server.
For each language the game has, it finds the lines with no translation and the translations that are broken.</p>

<h2>What you get</h2>
<p>Every run saves a report that opens in any browser, with no internet connection needed, beside a JSON file and a
JUnit file for other programs to read.
Click a problem to see how to get to it in the game: the choices that were made on the way.</p>
<figure>
<img src="images/report.png" width="1200" height="1150" alt="The report of a game, opened in a browser">
<figcaption>The report of The Question.</figcaption>
</figure>

<h2>Get it</h2>
<p>Download the file for your system from the <a href="%(release)s">latest release</a>.
Nothing has to be installed, not even Python.</p>
<div class="scroll">
<table>
<tr><th>Your system</th><th>File to download</th></tr>
<tr><td>Windows</td><td><code>renpytester-windows-x64.exe</code></td></tr>
<tr><td>Linux</td><td><code>renpytester-linux-x64</code></td></tr>
<tr><td>macOS, Apple Silicon (M1 and later)</td><td><code>renpytester-macos-arm64</code></td></tr>
<tr><td>macOS, Intel</td><td><code>renpytester-macos-x64</code></td></tr>
</table>
</div>
<p>It can also be run from its source with Python 3.11 or later and nothing else.
The <a href="%(url)s#readme">instructions</a> take you through a first test, and
<a href="%(url)s/blob/main/docs/advanced.md">the rest</a> is described beside them.</p>

<h2 id="code-signing-policy">Code signing policy</h2>
<p>Signing is being set up: the releases so far, up to v0.1.3, are not signed.</p>
<p>Free code signing provided by <a href="https://signpath.io/">SignPath.io</a>, certificate by
<a href="https://signpath.org/">SignPath Foundation</a>.</p>
<ul>
<li>Committers and reviewers: <a href="https://github.com/%(author)s">%(author)s</a></li>
<li>Approvers: <a href="https://github.com/%(author)s">%(author)s</a></li>
</ul>
<p>The Windows programs of a release are built from the repository's source by GitHub, tested there, and signed as
they were built.</p>
<h2 id="privacy">Privacy</h2>
<p>This program will not transfer any information to other networked systems unless specifically requested by the
user or the person installing or operating it.</p>

<footer>RenPyTester is free software under the <a href="%(url)s/blob/main/LICENSE">GPL-3.0 licence</a>, made by
<a href="https://github.com/%(author)s">%(author)s</a>.
It is not part of Ren'Py and is not made by its authors.</footer>
"""


def icon(size=256):
    """The program's icon, held in the page itself so that no second copy of the picture is kept."""
    data = (ROOT / "renpytester" / "assets" / ("icon-%d.png" % size)).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def page():
    body = BODY % {"icon": icon(), "release": RELEASE, "url": __url__, "author": html.escape(__author__)}
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"color-scheme\" content=\"light dark\">\n"
        "<meta name=\"description\" content=\"%s\">\n<link rel=\"canonical\" href=\"%s\">\n"
        "<link rel=\"icon\" href=\"%s\">\n<title>RenPyTester</title>\n<style>%s</style>\n</head>\n"
        "<body>\n<main>%s</main>\n</body>\n</html>\n" % (html.escape(TAGLINE), ADDRESS, icon(32), STYLE, body))


def main():
    PAGE.write_text(page(), encoding="utf-8", newline="\n")
    print("Wrote %s" % PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
