import pytest

from renpytester import discovery
from renpytester.errors import ToolError


def make_engine(root, lib="native", version="8.6.0"):
    (root / "renpy").mkdir(parents=True)
    (root / "renpy" / "vc_version.py").write_text("version = '%s.123'\n" % version)
    for name in discovery.platform_lib_names() if lib == "native" else [lib]:
        folder = root / "lib" / name
        folder.mkdir(parents=True)
        (folder / "python.exe").write_text("")
        (folder / "python").write_text("")
    return root


@pytest.mark.req("GAME-001")
def test_game_folder_is_found_from_anything_inside_it(tmp_path):
    game = tmp_path / "MyGame"
    (game / "game" / "images").mkdir(parents=True)
    (game / "game" / "script.rpy").write_text("")
    (game / "MyGame.exe").write_text("")
    for inside in (game, game / "game", game / "game" / "script.rpy", game / "MyGame.exe", game / "game" / "images"):
        assert discovery.resolve_basedir(inside) == game


@pytest.mark.req("GAME-001")
def test_missing_path_and_non_game_are_explained(tmp_path):
    with pytest.raises(ToolError) as error:
        discovery.resolve_basedir(tmp_path / "nowhere")
    assert error.value.message_id == "error.path_missing"
    (tmp_path / "empty").mkdir()
    with pytest.raises(ToolError) as error:
        discovery.resolve_basedir(tmp_path / "empty")
    assert error.value.message_id == "error.not_a_game"


@pytest.mark.req("GAME-002", "GAME-003")
def test_built_distribution_uses_its_own_engine(tmp_path):
    game = make_engine(tmp_path / "Built")
    (game / "game").mkdir()
    (game / "Built.py").write_text("")
    found = discovery.discover(game)
    assert found.kind == discovery.DISTRIBUTION
    assert found.engine_root == game
    assert found.main_script == game / "Built.py"
    assert found.renpy_version == (8, 6, 0)


@pytest.mark.req("GAME-002", "GAME-004", "GAME-008")
def test_project_uses_the_sdk(tmp_path):
    sdk = make_engine(tmp_path / "sdk")
    (sdk / "renpy.py").write_text("")
    game = tmp_path / "Project"
    (game / "game").mkdir(parents=True)
    found = discovery.discover(game, sdk)
    assert found.kind == discovery.PROJECT
    assert found.engine_root == sdk
    assert found.main_script == sdk / "renpy.py"


@pytest.mark.req("GAME-005")
def test_project_without_sdk_says_how_to_supply_one(tmp_path):
    (tmp_path / "Project" / "game").mkdir(parents=True)
    with pytest.raises(ToolError) as error:
        discovery.discover(tmp_path / "Project")
    assert error.value.message_id == "error.no_engine"
    assert error.value.exit_code == 3


@pytest.mark.req("COMPAT-004")
def test_python2_engine_is_refused_before_anything_runs(tmp_path):
    game = make_engine(tmp_path / "Old", lib="py2-windows-x86_64", version="7.4.11")
    (game / "game").mkdir()
    (game / "Old.py").write_text("")
    with pytest.raises(ToolError) as error:
        discovery.discover(game)
    assert error.value.message_id == "error.python2_engine"
    assert not list((game / "game").iterdir())


@pytest.mark.req("GAME-006")
def test_version_is_read_from_the_oldest_supported_layout(tmp_path):
    engine = make_engine(tmp_path / "sdk")
    (engine / "renpy" / "vc_version.py").write_text("vc_version = 22090809\n")
    (engine / "renpy" / "__init__.py").write_text(
        "if PY2:\n    version_tuple = (7, 5, 3, vc_version)\nelse:\n    version_tuple = (8, 0, 3, vc_version)\n")
    assert discovery.read_version(engine) == (8, 0, 3)
