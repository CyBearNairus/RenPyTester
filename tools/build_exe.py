"""Build the single-file executable (spec DIST-002, DIST-003, DIST-005).

    python tools/build_exe.py            builds dist/renpytester (on Windows, renpytester.exe and renpytesterw.exe)
    python tools/build_exe.py --tag TAG  only checks that TAG is the tag of this version, and builds nothing

Needs PyInstaller, a development tool only. The executable is for the system it is built on.
On Windows there are two, as Python itself has python.exe and pythonw.exe: renpytesterw.exe is a
window program, which a double click opens with no console window at all, and renpytester.exe is
a console program, which a terminal waits for and gets the exit code of.
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
# The executable for a double click on Windows, which has no console (CLI-007).
WINDOWED = NAME + "w"

# What the executable starts with. The package's own __main__ cannot be it: PyInstaller would take
# the package's folder for the place to find modules in.
ENTRY = "import sys\n\nfrom renpytester.cli import main\n\nsys.exit(main())\n"

# Python's network modules, which the program never uses and PyInstaller would pack all the same,
# because the standard library names them here and there. Left out, the executable holds no code
# that can open a connection (DIST-007), which also gives antivirus programs less to mistrust.
NO_NETWORK = ("socket", "_socket", "ssl", "_ssl", "http", "ftplib", "urllib.request")


def about():
    """What the package says of itself: its version, author and address."""
    scope = {}
    exec((PACKAGE / "__init__.py").read_text(encoding="utf-8"), scope)
    return scope


def version():
    return about()["__version__"]


def version_info(file_name):
    """What Windows shows under Details in the properties of the executable (DIST-002), in the
    form PyInstaller reads it from."""
    facts = about()
    numbers = tuple(int(part) for part in (facts["__version__"].split(".") + ["0"] * 4)[:4])
    texts = [
        ("CompanyName", facts["__author__"]),
        ("FileDescription", "RenPyTester"),
        ("FileVersion", facts["__version__"]),
        ("InternalName", NAME),
        ("LegalCopyright", "Copyright (C) %s. Licensed under GPL-3.0. %s" % (facts["__author__"], facts["__url__"])),
        ("OriginalFilename", file_name),
        ("ProductName", "RenPyTester"),
        ("ProductVersion", facts["__version__"]),
        ("Comments", facts["__doc__"].strip()),
    ]
    strings = ", ".join("StringStruct(%r, %r)" % pair for pair in texts)
    return (
        "VSVersionInfo(ffi=FixedFileInfo(filevers=%r, prodvers=%r, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, "
        "subtype=0x0, date=(0, 0)), kids=[StringFileInfo([StringTable('040904B0', [%s])]), "
        "VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n" % (numbers, numbers, strings))


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


def command(entry, name=NAME, windowed=False, version_file=None):
    cmd = [
        sys.executable, "-m", "PyInstaller", "--onefile", "--windowed" if windowed else "--console", "--name", name,
        "--noupx", "--clean", "--noconfirm", "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD), "--paths", str(ROOT), "--icon", str(PACKAGE / "assets" / "icon.ico")]
    if version_file is not None:
        cmd += ["--version-file", str(version_file)]
    for module in NO_NETWORK:
        cmd += ["--exclude-module", module]
    for file, folder in data_files():
        cmd += ["--add-data", "%s:%s" % (file, folder)]
    return cmd + [str(entry)]


def build():
    """Builds the executables for this system and returns them, the console program first."""
    BUILD.mkdir(exist_ok=True)
    entry = BUILD / (NAME + "_entry.py")
    entry.write_text(ENTRY, encoding="utf-8")
    if sys.platform != "win32":
        subprocess.run(command(entry), check=True, cwd=str(ROOT))
        return [DIST / NAME]
    built = []
    for name, windowed in ((NAME, False), (WINDOWED, True)):
        details = BUILD / (name + "_version.txt")
        details.write_text(version_info(name + ".exe"), encoding="utf-8")
        subprocess.run(command(entry, name, windowed, details), check=True, cwd=str(ROOT))
        built.append(DIST / (name + ".exe"))
    return built


def summarise(built):
    """On GitHub, puts what was built on the page of the run that built it."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as page:
        page.write("### Executable built\n\n| File | Version | Size | SHA-256 |\n| --- | --- | --- | --- |\n")
        for file in built:
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            page.write("| `%s` | %s | %.1f MB | `%s` |\n" % (
                file.name, version(), file.stat().st_size / 1024 ** 2, digest))
        page.write("\n")


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
    for file in built:
        print("Built %s" % file)
    summarise(built)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
