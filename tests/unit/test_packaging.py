"""The ways the program is handed to people: a clone, a package, an executable (spec 4.13)."""

import importlib.util
import os
import subprocess
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

from renpytester import __version__, cli, launcher

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "renpytester"


@pytest.fixture(scope="module")
def build_exe():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "tools" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.mark.req("DIST-001", "ARCH-005")
def test_runs_from_a_clone_with_nothing_but_python(tmp_path):
    # -S: no installed packages at all, so anything but the standard library would fail to import.
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-S", "-m", "renpytester", "--version"], capture_output=True, text=True, cwd=str(ROOT),
        env=env, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "renpytester " + __version__


@pytest.mark.req("DIST-004")
def test_package_installs_the_command_and_everything_it_needs(project):
    assert project["project"]["scripts"] == {"renpytester": "renpytester.cli:main"}
    assert callable(cli.main)
    assert project["project"]["dependencies"] == []

    packages = {
        path.parent.relative_to(ROOT).as_posix().replace("/", ".") for path in PACKAGE.rglob("__init__.py")}
    assert set(project["tool"]["setuptools"]["packages"]) == packages

    # Every file that is not code is named as data, or an installed copy would be missing it.
    patterns = project["tool"]["setuptools"]["package-data"]["renpytester"]
    in_packages = {path.parent for path in PACKAGE.rglob("__init__.py")}
    for file in PACKAGE.rglob("*"):
        if not file.is_file() or "__pycache__" in file.parts:
            continue
        if file.suffix == ".py" and file.parent in in_packages:
            continue
        name = file.relative_to(PACKAGE).as_posix()
        assert any(fnmatch(name, pattern) for pattern in patterns), name


@pytest.mark.req("DIST-002", "DIST-004")
def test_executable_is_given_the_same_data_files_as_the_package(build_exe):
    files = {(file.relative_to(ROOT).as_posix(), folder) for file, folder in build_exe.data_files()}
    for name in ("harness/zzz_renpytester_harness.rpy", "harness/silent_editor.py", "locale/en.json",
                 "locale/pt_BR.json", "assets/icon.ico", "assets/icon-32.png"):
        assert ("renpytester/" + name, "renpytester/" + name.split("/")[0]) in files, name
    # Each goes where the program looks for it: beside the module that reads it.
    assert launcher.SILENT_EDITOR.relative_to(ROOT).as_posix() in {name for name, _folder in files}

    entry = ROOT / "build" / "entry.py"
    command = build_exe.command(entry)
    assert "--onefile" in command and "--console" in command and command[-1] == str(entry)
    assert ("--hide-console" in command) == (sys.platform == "win32")
    assert command.count("--add-data") == len(files)


@pytest.mark.req("DIST-005")
def test_release_is_refused_for_a_tag_that_is_not_the_version(build_exe, capsys):
    assert build_exe.version() == __version__
    assert build_exe.main(["--tag", "v" + __version__]) == 0
    for tag in (__version__, "v" + __version__ + ".1", "v0.0.0", "latest"):
        assert build_exe.main(["--tag", tag]) == 1, tag
        assert tag in capsys.readouterr().out


@pytest.mark.req("DIST-006")
def test_engine_is_not_given_the_executables_own_libraries(monkeypatch):
    environ = {"LD_LIBRARY_PATH": "/tmp/_MEI123", "LD_LIBRARY_PATH_ORIG": "/opt/lib", "OTHER": "kept"}

    # From source there is nothing to undo.
    monkeypatch.delattr(sys, "frozen", raising=False)
    launcher.leave_bundle(environ)
    assert environ["LD_LIBRARY_PATH"] == "/tmp/_MEI123"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    launcher.leave_bundle(environ)
    assert environ == {"LD_LIBRARY_PATH": "/opt/lib", "OTHER": "kept"}

    # The user had none: the engine gets none.
    environ = {"LD_LIBRARY_PATH": "/tmp/_MEI123"}
    launcher.leave_bundle(environ)
    assert environ == {}


@pytest.mark.req("CLI-007")
def test_double_click_is_told_from_a_terminal_for_the_executable_too():
    # From source the program is one process; the executable is two, the one that unpacks it and itself.
    assert cli.console_is_ours(1, frozen=False, to_console=True)
    assert not cli.console_is_ours(2, frozen=False, to_console=True)
    assert cli.console_is_ours(2, frozen=True, to_console=True)
    assert not cli.console_is_ours(1, frozen=True, to_console=True)
    assert not cli.console_is_ours(3, frozen=True, to_console=True)
    # Started by another program that reads its output: not a person's double click.
    assert not cli.console_is_ours(1, frozen=False, to_console=False)
    assert not cli.console_is_ours(2, frozen=True, to_console=False)
