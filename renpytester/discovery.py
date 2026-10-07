"""Finding the game and the engine that will run it (spec 4.1), without launching anything."""

import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from renpytester.errors import ToolError

DISTRIBUTION = "distribution"
PROJECT = "project"


@dataclass
class Game:
    basedir: Path
    kind: str
    engine_root: Path
    python: Path
    main_script: Path
    renpy_version: tuple


def resolve_basedir(path):
    """Accepts the game folder or anything inside it and returns the game folder (GAME-001)."""
    path = Path(path).expanduser()
    if not path.exists():
        raise ToolError("error.path_missing", path=str(path))
    path = path.resolve()

    if path.is_dir() and path.suffix == ".app":
        bundled = path / "Contents" / "Resources" / "autorun"
        if (bundled / "game").is_dir():
            return bundled

    start = path if path.is_dir() else path.parent
    for candidate in (start, *start.parents):
        if (candidate / "game").is_dir():
            return candidate

    raise ToolError("error.not_a_game", path=str(path))


def platform_lib_names():
    """Names of the engine's per-platform library folder, most likely first."""
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return ["py3-windows-x86_64"]
    if sys.platform == "darwin":
        return ["py3-mac-universal", *(["py3-mac-arm64"] if machine == "arm64" else []), "py3-mac-x86_64"]
    if machine in ("aarch64", "arm64"):
        return ["py3-linux-aarch64", "py3-linux-x86_64"]
    return ["py3-linux-x86_64"]


def find_python(engine_root):
    name = "python.exe" if sys.platform == "win32" else "python"
    for lib in platform_lib_names():
        candidate = engine_root / "lib" / lib / name
        if candidate.is_file():
            return candidate
    return None


def uses_python2(engine_root):
    """True for Ren'Py 7 and older, whose library folders are not named py3-*."""
    lib = engine_root / "lib"
    if not lib.is_dir():
        return False
    names = [i.name for i in lib.iterdir() if i.is_dir()]
    return bool(names) and not any(i.startswith("py3-") or i.startswith("python3") for i in names)


def read_version(engine_root):
    """Reads the engine version from its files, as a tuple of integers, or () if unknown."""
    renpy_dir = engine_root / "renpy"

    try:
        text = (renpy_dir / "vc_version.py").read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^version\s*=\s*['\"](\d+)\.(\d+)\.(\d+)", text, re.M)
        if match:
            return tuple(int(i) for i in match.groups())
    except OSError:
        pass

    try:
        text = (renpy_dir / "__init__.py").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()

    pattern = r"version_tuple\s*=\s*\((\d+),\s*(\d+),\s*(\d+)"
    found = [tuple(int(i) for i in m.groups()) for m in re.finditer(pattern, text)]
    if not found:
        return ()
    # Files from the 7/8 transition list both lines; the Python version of the build decides.
    wanted = 7 if uses_python2(engine_root) else 8
    for version in found:
        if version[0] == wanted:
            return version
    return max(found)


def is_engine(root):
    return (root / "renpy").is_dir() and (root / "lib").is_dir()


def main_script(engine_root, basedir):
    if (engine_root / "renpy.py").is_file():
        return engine_root / "renpy.py"
    scripts = sorted(basedir.glob("*.py"))
    return scripts[0] if scripts else None


def discover(path, sdk=None):
    """Works out what to test and what to run it with (GAME-001 to GAME-005, COMPAT-004)."""
    basedir = resolve_basedir(path)
    bundled = is_engine(basedir)
    kind = DISTRIBUTION if bundled else PROJECT

    if sdk:
        engine_root = Path(sdk).expanduser().resolve()
        if not is_engine(engine_root):
            raise ToolError("error.sdk_invalid", path=str(engine_root))
    elif bundled:
        engine_root = basedir
    else:
        raise ToolError("error.no_engine", path=str(basedir))

    version = read_version(engine_root)
    if uses_python2(engine_root) or (version and version[0] < 8):
        raise ToolError("error.python2_engine", version=".".join(str(i) for i in version) or "?")

    python = find_python(engine_root)
    script = main_script(engine_root, basedir)
    if python is None or script is None:
        raise ToolError(
            "error.engine_incomplete", path=str(engine_root), wanted=", ".join(platform_lib_names()))

    return Game(basedir, kind, engine_root, python, script, version)
