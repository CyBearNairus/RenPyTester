"""What the specification asks of the project itself, not of a run: that every requirement is
tested, that the harness can run on the oldest engine's Python, and what CI checks (spec 7.3, 7.4)."""

import ast
import re
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
HARNESS = ROOT / "renpytester" / "harness"

REQUIREMENT = r"[A-Z][A-Z0-9]*-\d{3}"


def requirements():
    """Every requirement in the specification, as {id: priority}. The architecture constraints of
    section 3 have no priority of their own: each is binding, so they count as MUST."""
    found = {}
    for name, priority in re.findall(r"^\| (%s) \| (MUST|SHOULD|COULD|—) \|" % REQUIREMENT, SPEC, re.MULTILINE):
        found[name] = "withdrawn" if priority == "—" else priority
    for name, title in re.findall(r"^\*\*(%s) \(([^)]*)\)\.\*\*" % REQUIREMENT, SPEC, re.MULTILINE):
        found[name] = title if title in ("MUST", "SHOULD", "COULD") else "MUST"
    return found


def named_by_tests():
    """The requirements that tests say they verify, as {id: [test names]}."""
    found = {}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                is_req = isinstance(decorator, ast.Call) and ast.unparse(decorator.func) == "pytest.mark.req"
                for argument in decorator.args if is_req else []:
                    found.setdefault(argument.value, []).append("%s::%s" % (path.name, node.name))
    return found


@pytest.mark.req("NFR-002")
def test_every_requirement_that_must_be_met_is_named_by_a_test():
    """Item 1 of the acceptance for 1.0 (spec 7.4): a requirement is done when a test names it (7.3)."""
    known = requirements()
    assert len(known) > 150 and known["CLI-009"] == "withdrawn"
    tested = named_by_tests()
    must = sorted(name for name, priority in known.items() if priority == "MUST")
    assert [name for name in must if name not in tested] == []


@pytest.mark.req("NFR-002")
def test_tests_name_only_requirements_that_exist():
    known = requirements()
    wrong = {name: tests for name, tests in named_by_tests().items() if known.get(name) in (None, "withdrawn")}
    assert wrong == {}


def harness_python():
    """The Python of the script that is put into the game, and of the editor that opens nothing."""
    script = (HARNESS / "zzz_renpytester_harness.rpy").read_text(encoding="utf-8")
    start = script.index("init 999 python hide:\n") + len("init 999 python hide:\n")
    return {
        "zzz_renpytester_harness.rpy": textwrap.dedent(script[start:]),
        "silent_editor.py": (HARNESS / "silent_editor.py").read_text(encoding="utf-8")}


@pytest.mark.req("ARCH-001", "COMPAT-002")
@pytest.mark.parametrize("name", sorted(harness_python()))
def test_harness_is_python_that_the_oldest_engine_can_run(name):
    # The earliest Ren'Py 8 carries Python 3.9: nothing newer may be written, and nothing imported
    # that does not come with Python or with the engine.
    tree = ast.parse(harness_python()[name], feature_version=(3, 9))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        # Written as "X | Y", a pair of types is an error before Python 3.10; and nothing in the
        # harness has a reason to annotate.
        assert not isinstance(node, ast.AnnAssign), "line %d" % node.lineno
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.returns is None and not [a for a in node.args.args if a.annotation], node.name
    assert imported - set(sys.stdlib_module_names) - {"renpy"} == set()
    assert "tomllib" not in imported and "sys" in sys.stdlib_module_names


@pytest.mark.req("ARCH-002")
def test_harness_reports_through_the_events_file_and_never_through_what_it_prints():
    source = harness_python()["zzz_renpytester_harness.rpy"]
    printed = [
        node.lineno for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and ast.unparse(node.func) in ("print", "sys.stdout.write", "sys.stderr.write")]
    assert printed == []
    assert 'events = open(os.environ["RENPYTESTER_EVENTS"], "a", encoding="utf-8")' in source


@pytest.mark.req("COMPAT-001", "COMPAT-006")
def test_every_supported_system_and_python_is_tested_on_every_push():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == ">=3.11"
    systems = re.findall(r"^ +os: \[(.*)\]$", CI, re.MULTILINE)
    # The unit tests and the end-to-end tests each run on Windows, Linux and macOS.
    assert len(systems) == 2
    for listed in systems:
        assert [name.strip().split("-")[0] for name in listed.split(",")] == ["windows", "ubuntu", "macos"]
    pythons = re.search(r'^ +python: \[(.*)\]$', CI, re.MULTILINE).group(1)
    assert [version.strip().strip('"') for version in pythons.split(",")][:2] == ["3.11", "3.12"]


@pytest.mark.req("DIST-005", "DIST-006")
def test_a_release_runs_every_end_to_end_test_once_and_ci_runs_them_from_source():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    # From source only what the executable cannot be given; then the executable on each engine, and
    # the window program on Windows.
    assert release.count("pytest tests/e2e") == 4
    assert release.count('python -m pytest tests/e2e -m source -n "$E2E_WORKERS"') == 1
    assert release.count('RENPYTESTER_EXE="$PWD/${{ matrix.built }}"') == 2
    assert release.count('RENPYTESTER_EXE="$PWD/${{ matrix.windowed }}"') == 1
    assert 'RENPY_SDK="$PWD/.cache/sdk/renpy-$RENPY_OLDEST-sdk"' in release
    # The rest from source is the CI workflow's, on every push.
    assert "python -m pytest tests/e2e -n" in CI and "-m source" not in CI
    # A tag takes the place of a rehearsal, and never the other way round.
    assert "cancel-in-progress: ${{ github.ref_type == 'tag' }}" in release


@pytest.mark.req("NFR-008", "NFR-009")
def test_every_linter_is_run_on_every_push_with_the_repositorys_own_rules():
    for command in ("python -m flake8 .", "python tools/lint_rpy.py", 'markdownlint-cli2 "**/*.md"'):
        assert command in CI, command
    assert "max-line-length = 120" in (ROOT / ".flake8").read_text(encoding="utf-8")
    assert (ROOT / ".markdownlint.json").is_file()
    assert (ROOT / "tools" / "lint_rpy.py").is_file()
