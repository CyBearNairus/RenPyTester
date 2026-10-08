"""The ways the program is handed to people: a clone, a package, an executable (spec 4.13)."""

import importlib.util
import os
import re
import subprocess
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

from renpytester import __version__, cli, launcher, palette

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
    assert command.count("--add-data") == len(files)


@pytest.mark.req("CLI-007", "DIST-002")
def test_windows_gets_a_window_program_with_no_console_beside_the_console_program(build_exe):
    entry = ROOT / "build" / "entry.py"
    details = ROOT / "build" / "version.txt"
    command = build_exe.command(entry, build_exe.WINDOWED, windowed=True, version_file=details)
    assert "--windowed" in command and "--console" not in command
    assert command[command.index("--name") + 1] == "renpytesterw"
    assert command[command.index("--version-file") + 1] == str(details)
    # Nothing hides a console any more: the window program never has one.
    assert "--hide-console" not in command and "--hide-console" not in build_exe.command(entry)


@pytest.mark.req("DIST-007")
def test_executable_is_built_without_network_modules_and_the_program_imports_none(build_exe):
    command = build_exe.command(ROOT / "build" / "entry.py")
    left_out = {command[at + 1] for at, word in enumerate(command) if word == "--exclude-module"}
    assert {"socket", "_socket", "ssl", "_ssl", "http", "ftplib", "urllib.request"} <= left_out

    # Left out of the executable, they must not be asked for: a Python of its own, so that what the
    # tests themselves have loaded does not count.
    modules = sorted(
        "renpytester." + file.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", ".")
        for file in PACKAGE.rglob("*.py") if file.name not in ("__init__.py", "__main__.py", "silent_editor.py"))
    assert "renpytester.gui" in modules and "renpytester.report.html_report" in modules
    code = "import sys, %s\nprint(sorted(set(sys.modules) & set(%r)))" % (", ".join(modules), sorted(left_out))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


@pytest.mark.req("DIST-008")
def test_release_signs_the_windows_executables_only_when_it_has_been_set_up_to():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "signpath/github-action-submit-signing-request@" in workflow
    # Never in a rehearsal, never without the settings, and the signed files are tested before they are released.
    assert "if: matrix.windowed && github.ref_type == 'tag' && vars.SIGNPATH_ORGANIZATION_ID != ''" in workflow
    assert workflow.count("if: steps.unsigned.outcome == 'success'") == 2
    assert "RENPYTESTER_SIGNED=1" in workflow and "secrets.SIGNPATH_API_TOKEN" in workflow

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Code signing policy" in readme
    assert "Free code signing provided by [SignPath.io](https://signpath.io/), certificate by " in readme
    assert "will not transfer any information to other networked systems unless specifically requested" in readme


@pytest.mark.req("DIST-010", "DIST-008", "GUI-015")
def test_home_page_is_what_its_tool_writes_and_carries_the_code_signing_policy():
    spec = importlib.util.spec_from_file_location("make_site", ROOT / "tools" / "make_site.py")
    make_site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_site)
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert page == make_site.page(), "run python tools/make_site.py and commit docs/index.html"
    assert (ROOT / "docs" / ".nojekyll").is_file()

    for name in ("window.png", "report.png"):
        assert 'src="images/%s"' % name in page and (ROOT / "docs" / "images" / name).is_file()
    assert "Code signing policy</h2>" in page
    assert "Free code signing provided by <a href=\"https://signpath.io/\">SignPath.io</a>, certificate by" in page
    assert "will not transfer any information to other networked systems unless specifically requested" in page
    # Its colours are the palette's and no others.
    style = page.split("<style>")[1].split("</style>")[0]
    known = set(palette.LIGHT.values()) | set(palette.DARK.values())
    assert set(re.findall(r"#[0-9a-fA-F]{3,8}\b", style)) <= known


@pytest.fixture(scope="module")
def virustotal():
    spec = importlib.util.spec_from_file_location("virustotal", ROOT / "tools" / "virustotal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.req("DIST-009")
def test_virustotal_key_comes_from_the_environment_or_the_env_file_and_nothing_is_sent_without_one(
        virustotal, tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    assert virustotal.key_from(env_file, {}) is None
    env_file.write_text("# keys\nOTHER=1\nVIRUSTOTAL_API_KEY = \"from-file\"\n", encoding="utf-8")
    assert virustotal.key_from(env_file, {}) == "from-file"
    assert virustotal.key_from(env_file, {"VIRUSTOTAL_API_KEY": "from-environment"}) == "from-environment"
    assert virustotal.key_from(env_file, {"VIRUSTOTAL_API_KEY": " "}) == "from-file"

    def never(*_args, **_kwargs):
        raise AssertionError("something was sent")

    program = tmp_path / "program.exe"
    program.write_bytes(b"MZ")
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(virustotal, "ROOT", tmp_path / "nowhere")
    monkeypatch.setattr(virustotal.urllib.request, "urlopen", never)
    monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert virustotal.main([str(program)]) == 0
    assert "Nothing was sent" in capsys.readouterr().out
    assert "Not asked" in summary.read_text(encoding="utf-8")
    assert virustotal.main([str(tmp_path / "missing.exe")]) == 1


@pytest.mark.req("DIST-009")
def test_virustotal_verdicts_are_reported_and_hold_nothing_back(virustotal, tmp_path, monkeypatch, capsys):
    results = {
        "Good": {"category": "undetected", "result": None},
        "Kind": {"category": "harmless", "result": None},
        "Wary": {"category": "malicious", "result": "W32.Malware.0000"},
        "Unsure": {"category": "suspicious", "result": None},
        "Slow": {"category": "timeout", "result": None},
        "Other": {"category": "type-unsupported", "result": None},
    }
    assert virustotal.verdicts(results) == (4, [("Unsure", "suspicious"), ("Wary", "W32.Malware.0000")])

    body, content_type = virustotal.form("program.exe", b"MZ\x00\xff")
    boundary = content_type.split("boundary=")[1]
    assert content_type.startswith("multipart/form-data; ")
    assert body.startswith(("--" + boundary + "\r\n").encode()) and body.endswith(("--" + boundary + "--\r\n").encode())
    assert b'name="file"; filename="program.exe"' in body and b"\r\n\r\nMZ\x00\xff\r\n" in body

    sent = []
    program = tmp_path / "program.exe"
    program.write_bytes(b"MZ")
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(virustotal, "analyse", lambda key, file: sent.append((key, file)) or results)
    monkeypatch.setenv("VIRUSTOTAL_API_KEY", "not-to-be-shown")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert virustotal.main([str(program)]) == 0
    assert sent == [("not-to-be-shown", program)]
    said = capsys.readouterr().out + summary.read_text(encoding="utf-8")
    assert "2 of 4 antivirus programs call it harmful" in said and "Wary: W32.Malware.0000" in said
    assert "not-to-be-shown" not in said

    def fail(key, file):
        raise virustotal.Failed("VirusTotal could not be reached.")

    monkeypatch.setattr(virustotal, "analyse", fail)
    assert virustotal.main([str(program)]) == 1


@pytest.mark.req("DIST-002")
def test_executable_says_what_it_is_in_its_properties(build_exe):
    text = build_exe.version_info("renpytesterw.exe")
    numbers = tuple(int(part) for part in __version__.split(".")) + (0,)
    assert "filevers=%r" % (numbers,) in text and "prodvers=%r" % (numbers,) in text
    for name, value in (
            ("ProductName", "RenPyTester"), ("FileDescription", "RenPyTester"), ("CompanyName", "CyBearNairus"),
            ("FileVersion", __version__), ("ProductVersion", __version__), ("OriginalFilename", "renpytesterw.exe")):
        assert "StringStruct(%r, %r)" % (name, value) in text, name
    assert "GPL-3.0" in text and "https://github.com/CyBearNairus/RenPyTester" in text
    # It is Python that PyInstaller can read, and nothing else.
    compile(text, "version", "eval")


@pytest.mark.req("CLI-007")
def test_window_program_with_nowhere_to_write_is_told_apart_from_one_in_a_terminal(monkeypatch):
    import io

    # Output that goes somewhere already is left alone.
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(cli, "no_terminal", False)
    cli.find_console()
    assert sys.stdout is stream and cli.no_terminal is False

    # The window program started by a double click has no output at all, and no terminal to find.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "platform", "linux")  # Nowhere to look for a terminal, as after a double click.
    cli.find_console()
    assert cli.no_terminal is True
    sys.stdout.write("goes nowhere, and does not fail")
    sys.stdout.close()
    sys.stderr.close()
    monkeypatch.setattr(sys, "platform", "win32")
    # So a folder dropped on it opens the window with that game.
    assert cli.own_console() is True


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
