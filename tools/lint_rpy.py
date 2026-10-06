"""Lint Ren'Py script files (.rpy).

Two layers of checks:

1. Ren'Py layout rules, the ones the Ren'Py editor extension reports: spaces only, indentation in
   multiples of four, no trailing whitespace, lines no longer than the limit in .flake8.
2. Flake8 on the Python inside ``python:`` blocks, with line numbers that match the .rpy file.

    python tools/lint_rpy.py [PATH ...]

With no paths, every tracked or untracked .rpy file outside ignored folders is checked.
Exits 1 if anything is reported.
"""

import configparser
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".cache", ".venv", "venv", "build", "dist", "__pycache__"}

PYTHON_BLOCK = re.compile(r"^(\s*)(init\s+(-?\d+\s+)?)?python(\s+(early|hide|in\s+\w+))*\s*:\s*(#.*)?$")

# Names the engine puts in scope for every python block.
RENPY_BUILTINS = "renpy,config,store,persistent,ui,im,build,define,gui,preferences,style,layout,_,__,_p,_preferences"

# Checks that make no sense once a block is lifted out of its file: blank-line counts are distorted
# by the padding that keeps line numbers aligned, and blocks in one file share a namespace.
RPY_IGNORE = "E301,E302,E303,E305,E306,W391,E402"


def max_line_length():
    parser = configparser.ConfigParser()
    parser.read(ROOT / ".flake8")
    return parser.getint("flake8", "max-line-length", fallback=120)


def find_files(args):
    if args:
        return [Path(a) for a in args]
    return sorted(p for p in ROOT.rglob("*.rpy") if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts))


def layout_problems(lines, limit):
    for number, line in enumerate(lines, 1):
        if "\t" in line[: len(line) - len(line.lstrip())]:
            yield number, "R001 tab in indentation; Ren'Py scripts must be indented with spaces"
        indent = len(line) - len(line.lstrip(" "))
        if line.strip() and indent % 4:
            yield number, "R002 indentation of %d spaces is not a multiple of 4" % indent
        if line != line.rstrip():
            yield number, "R003 trailing whitespace"
        if len(line) > limit:
            yield number, "R004 line too long (%d > %d characters)" % (len(line), limit)


def extract_python(lines):
    """Returns Python source with one line per .rpy line: python blocks dedented, the rest blank."""
    out = [""] * len(lines)
    i = 0
    while i < len(lines):
        match = PYTHON_BLOCK.match(lines[i])
        if not match:
            i += 1
            continue
        outer = len(match.group(1))
        i += 1
        body = []
        while i < len(lines):
            line = lines[i]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= outer:
                break
            body.append(i)
            i += 1
        indents = [len(lines[j]) - len(lines[j].lstrip(" ")) for j in body if lines[j].strip()]
        if not indents:
            continue
        cut = min(indents)
        for j in body:
            out[j] = lines[j][cut:] if lines[j].strip() else ""
    return "\n".join(out) + "\n"


def flake8_problems(path, source):
    cmd = [sys.executable, "-m", "flake8", "--config", str(ROOT / ".flake8"), "--builtins", RENPY_BUILTINS,
           "--extend-ignore", RPY_IGNORE, "--format", "%(row)d\t%(code)s %(text)s", "-"]
    result = subprocess.run(cmd, input=source, capture_output=True, text=True)
    if result.stderr.strip():
        yield 0, "flake8 failed: " + result.stderr.strip().splitlines()[-1]
    for line in result.stdout.splitlines():
        row, _, text = line.partition("\t")
        yield int(row), text


def main(argv):
    limit = max_line_length()
    total = 0
    files = find_files(argv)
    for path in files:
        lines = path.read_text(encoding="utf-8").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        problems = list(layout_problems(lines, limit))
        problems.extend(flake8_problems(path, extract_python(lines)))
        # A long line is reported by both layers; keep the Ren'Py one.
        problems = [p for p in problems if not p[1].startswith("E501")]
        for number, text in sorted(problems):
            print("%s:%d: %s" % (path.relative_to(ROOT) if path.is_absolute() else path, number, text))
        total += len(problems)
    print("%d file(s) checked, %d problem(s)" % (len(files), total))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
