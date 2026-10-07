"""Shared test fixtures.

End-to-end tests need a Ren'Py SDK. It is taken from the RENPY_SDK environment variable, or from
the newest one unpacked under .cache/sdk/. Without one, those tests are skipped.
"""

import hashlib
import os
import platform
import shutil
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "games"


def find_sdk():
    if os.environ.get("RENPY_SDK"):
        return Path(os.environ["RENPY_SDK"])

    def version(path):
        return [int(i) for i in path.name.split("-")[1].split(".")]

    found = sorted((ROOT / ".cache" / "sdk").glob("renpy-*-sdk"), key=version)
    return found[-1] if found else None


@pytest.fixture(autouse=True)
def own_cache(tmp_path_factory, monkeypatch):
    """Keeps sandbox copies made by a test out of the real cache of whoever runs the tests."""
    path = tmp_path_factory.mktemp("cache")
    monkeypatch.setenv("RENPYTESTER_CACHE", str(path))
    # The same for what the window remembers between sessions.
    monkeypatch.setenv("RENPYTESTER_GUI_STATE", str(path / "window.json"))
    return path


@pytest.fixture(scope="session")
def sdk():
    path = find_sdk()
    if path is None or not (path / "renpy").is_dir():
        pytest.skip("no Ren'Py SDK available: set RENPY_SDK")
    return path


@pytest.fixture
def game_copy(tmp_path):
    """Returns a function that copies a fixture game into a temporary folder and returns its path."""

    copies = []

    def copy(name):
        copies.append(name)
        target = tmp_path / ("game-%d" % len(copies)) / name
        shutil.copytree(FIXTURES / name, target)
        return target

    return copy


def folder_digest(path):
    """A fingerprint of every file's name and content under a folder."""
    digest = hashlib.sha1()
    for file in sorted(Path(path).rglob("*")):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Keeps the engine and harness logs of a failed test under .cache/failures/, where they outlive the run.

    An end-to-end failure can depend on timing inside the engine and not come back on the next run;
    the logs are the only evidence.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    tmp_path = item.funcargs.get("tmp_path")
    if tmp_path is None:
        return
    logs = [p for p in Path(tmp_path).rglob("*-logs") if p.is_dir()]
    target = ROOT / ".cache" / "failures" / item.name.replace("[", "-").replace("]", "")
    shutil.rmtree(target, ignore_errors=True)
    for number, folder in enumerate(logs):
        shutil.copytree(folder, target / ("%d-%s" % (number, folder.name)))
    for report_file in Path(tmp_path).rglob("report-*.json"):
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(report_file, target / report_file.name)


def pytest_sessionstart(session):
    session.config.renpytester_started = time.monotonic()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """On GitHub, puts the result of this test run on the page of the workflow run."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return

    def tests(kind):
        return [r for r in terminalreporter.stats.get(kind, []) if hasattr(r, "nodeid")]

    def cell(text):
        return str(text).replace("|", "&#124;").replace("\n", " ")[:300]

    what = " ".join(config.invocation_params.args) or "everything"
    sdk_path = find_sdk()
    about = [
        "the executable" if os.environ.get("RENPYTESTER_EXE") else "from source",
        "Ren'Py SDK %s" % sdk_path.name.split("-")[1] if sdk_path and "tests/unit" not in what else None,
        "Python %s" % platform.python_version(), platform.platform(terse=True)]
    counts = [len(tests(kind)) for kind in ("passed", "failed", "error", "skipped")]
    seconds = int(time.monotonic() - getattr(config, "renpytester_started", time.monotonic()))
    lines = [
        "### %s Tests: `%s`" % ("\u2705" if exitstatus == 0 else "\u274c", what), "",
        ", ".join(part for part in about if part) + ".", "",
        "| Passed | Failed | Errors | Skipped | Time |", "| --- | --- | --- | --- | --- |",
        "| %d | %d | %d | %d | %d min %02d s |" % (*counts, seconds // 60, seconds % 60)]
    broken = tests("failed") + tests("error")
    if broken:
        lines += ["", "| Failed test | Why |", "| --- | --- |"]
        for report in broken:
            crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
            lines.append("| `%s` | %s |" % (cell(report.nodeid), cell(crash.message if crash else "")))
    with open(target, "a", encoding="utf-8") as page:
        page.write("\n".join(lines) + "\n\n")
