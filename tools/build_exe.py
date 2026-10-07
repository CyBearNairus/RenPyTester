"""Build the single-file executable (spec DIST-002, DIST-003, DIST-005).

    python tools/build_exe.py            builds dist/renpytester (renpytester.exe on Windows)
    python tools/build_exe.py --tag TAG  only checks that TAG is the tag of this version, and builds nothing

Needs PyInstaller, a development tool only. The executable is for the system it is built on.
It carries the files that pyproject.toml lists as the package's data, so that it and an installed
package (DIST-004) cannot come to differ in what they hold.
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "renpytester"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "renpytester"

# What the executable starts with. The package's own __main__ cannot be it: PyInstaller would take
# the package's folder for the place to find modules in.
ENTRY = "import sys\n\nfrom renpytester.cli import main\n\nsys.exit(main())\n"


def version():
    scope = {}
    exec((PACKAGE / "__init__.py").read_text(encoding="utf-8"), scope)
    return scope["__version__"]


def tag_of(number):
    return "v" + number


def data_files():
    """Every file the package needs beside its code, as (file, folder inside the executable)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    found = []
    for package, patterns in project["tool"]["setuptools"]["package-data"].items():
        folder = ROOT / package.replace(".", "/")
        for pattern in patterns:
            for file in sorted(folder.glob(pattern)):
                found.append((file, file.parent.relative_to(ROOT).as_posix()))
    return found


def command(entry):
    cmd = [
        sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--name", NAME, "--noupx", "--clean",
        "--noconfirm", "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
        "--paths", str(ROOT), "--icon", str(PACKAGE / "assets" / "icon.ico")]
    if sys.platform == "win32":
        # Started by a double click, the program is given a console window of its own, which it has
        # no use for: it is hidden before anything is unpacked (CLI-007).
        cmd += ["--hide-console", "hide-early"]
    for file, folder in data_files():
        cmd += ["--add-data", "%s:%s" % (file, folder)]
    return cmd + [str(entry)]


def build():
    BUILD.mkdir(exist_ok=True)
    entry = BUILD / (NAME + "_entry.py")
    entry.write_text(ENTRY, encoding="utf-8")
    subprocess.run(command(entry), check=True, cwd=str(ROOT))
    return DIST / (NAME + (".exe" if sys.platform == "win32" else ""))


def summarise(built):
    """On GitHub, puts what was built on the page of the run that built it."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    digest = hashlib.sha256(built.read_bytes()).hexdigest()
    with open(target, "a", encoding="utf-8") as page:
        page.write("### Executable built\n\n| File | Version | Size | SHA-256 |\n| --- | --- | --- | --- |\n")
        page.write("| `%s` | %s | %.1f MB | `%s` |\n\n" % (
            built.name, version(), built.stat().st_size / 1024 ** 2, digest))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="check that this is the tag of the version in the source, and build nothing")
    args = parser.parse_args(argv)
    if args.tag is not None:
        wanted = tag_of(version())
        if args.tag != wanted:
            print("The tag is %s, but the source is version %s, whose tag is %s." % (args.tag, version(), wanted))
            return 1
        print("Tag %s matches the version." % args.tag)
        return 0
    built = build()
    print("Built %s" % built)
    summarise(built)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
