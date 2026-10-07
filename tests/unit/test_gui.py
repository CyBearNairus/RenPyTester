"""The part of the window that has no widgets (spec 4.14), and how the window is asked for (CLI-007)."""

import builtins
import json
import shlex
import sys

import pytest

from renpytester import cli, gui, i18n, runner
from renpytester.errors import ToolError


@pytest.fixture(autouse=True)
def english(monkeypatch, tmp_path):
    i18n.set_language("en")
    monkeypatch.delenv("RENPY_SDK", raising=False)
    monkeypatch.setattr(gui, "default_output", lambda: tmp_path / "reports")


@pytest.fixture
def game(tmp_path):
    folder = tmp_path / "My Game"
    (folder / "game").mkdir(parents=True)
    (folder / "game" / "script.rpy").write_text("label start:\n    return\n")
    return folder


def split(command):
    """A command line as the user's terminal would split it."""
    if sys.platform != "win32":
        return shlex.split(command)
    import ctypes

    count = ctypes.c_int()
    ctypes.windll.shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    parts = ctypes.windll.shell32.CommandLineToArgvW(command, ctypes.byref(count))
    return [parts[index] for index in range(count.value)]


def from_command_line(command):
    """The options the command line makes of a command the window displays."""
    program, *arguments = split(command)
    assert program == "renpytester"
    args = cli.build_parser().parse_args(arguments)
    options, _settings = runner.prepare(args.game, cli.given_by(args), args.config)
    return options, args


@pytest.mark.req("GUI-007", "GUI-002")
def test_window_shows_the_command_that_makes_the_same_run(game, tmp_path):
    session = gui.Session(tmp_path / "state.json")
    # A new session starts in the system's language, whatever that is where the tests run.
    assert session.lang in i18n.LANGUAGES
    session.game, session.lang = str(game), "en"

    options, command = session.plan()
    assert options == runner.Options(game=str(game), output=str(tmp_path / "reports"))
    from_command, args = from_command_line(command)
    assert from_command == options
    assert args.lang == "en"
    assert "--stages" not in command and "--sandbox" not in command and "--sdk" not in command

    session.sdk = str(tmp_path / "an sdk with spaces")
    session.stages = ["translations", "lint"]
    session.languages = ["french", "spanish"]
    session.sandbox = True
    session.lang = "pt-BR"
    options, command = session.plan()
    assert (options.stages, options.languages, options.sandbox, options.sdk) == (
        ("lint", "translations"), ("french", "spanish"), True, session.sdk)
    from_command, args = from_command_line(command)
    assert from_command == options
    assert args.lang == "pt-BR"

    # Languages only matter when translations are checked; the command does not mention them otherwise.
    session.stages = ["routes"]
    options, command = session.plan()
    assert options.languages is None and "--languages" not in command
    assert from_command_line(command)[0] == options


@pytest.mark.req("GUI-002", "GUI-007", "CFG-002")
def test_window_leaves_everything_else_to_the_config_file(game, tmp_path):
    (game / "renpytester.toml").write_text('seed = 7\nmax_time = 30\noutput = "my-reports"\n', encoding="utf-8")
    session = gui.Session(tmp_path / "state.json")
    session.game = str(game)
    options, command = session.plan()
    assert (options.seed, options.max_time) == (7, 30)
    # The file says where reports go, so the window does not.
    assert options.output == str((game / "my-reports").resolve())
    assert "--output" not in command
    assert from_command_line(command)[0] == options


@pytest.mark.req("GUI-006", "CFG-004")
def test_what_stops_a_run_is_an_error_with_a_message_not_a_crash(game, tmp_path):
    session = gui.Session(tmp_path / "state.json")
    session.game = str(tmp_path / "nowhere")
    with pytest.raises(ToolError) as raised:
        session.plan()
    assert raised.value.message_id == "error.path_missing"

    session.game = str(game)
    (game / "renpytester.toml").write_text("sed = 7\n", encoding="utf-8")
    with pytest.raises(ToolError) as raised:
        session.plan()
    assert raised.value.message_id == "error.config_unknown_key"


@pytest.mark.req("GUI-008")
def test_choices_are_remembered_between_sessions(game, tmp_path):
    path = tmp_path / "deep" / "state.json"
    first = gui.Session(path)
    first.game, first.sdk, first.stages = str(game), "C:/sdk", ["routes"]
    first.languages, first.sandbox, first.lang = ["french"], True, "pt-BR"
    first.save()

    second = gui.Session(path)
    second.load()
    assert (second.game, second.sdk, second.stages) == (str(game), "C:/sdk", ["routes"])
    assert (second.languages, second.sandbox, second.lang) == (["french"], True, "pt-BR")

    # A file that is damaged, or was written by something else, is passed over.
    for text in ("not json", "[]", json.dumps({"game": 5, "stages": "all", "lang": "fr", "sandbox": "yes"})):
        path.write_text(text, encoding="utf-8")
        third = gui.Session(path)
        third.load()
        assert (third.game, third.stages, third.sandbox) == ("", list(runner.STAGES), False)
        assert third.lang in i18n.LANGUAGES


@pytest.mark.req("GUI-008")
def test_window_state_is_kept_in_the_users_profile(monkeypatch):
    assert gui.state_file().name == "window.json"
    monkeypatch.delenv("RENPYTESTER_GUI_STATE")
    assert "renpytester" in str(gui.state_file()).lower()
    assert gui.state_file().is_absolute()


@pytest.mark.req("GUI-012", "I18N-008")
def test_every_interface_language_has_a_name_in_every_interface_language():
    names = {}
    for shown_in in i18n.LANGUAGES:
        i18n.set_language(shown_in)
        names[shown_in] = [gui.language_name(code) for code in i18n.LANGUAGES]
    i18n.set_language("en")
    assert names == {"en": ["English", "Brazilian Portuguese"], "pt-BR": ["Inglês", "Português do Brasil"]}
    # A language added later needs a name too, or it would be listed by its message identifier.
    assert not [name for listed in names.values() for name in listed if name.startswith("language.")]


@pytest.mark.req("GUI-013", "NFR-006")
def test_icon_files_are_in_the_package_in_every_size_the_window_asks_for():
    import struct

    for size in gui.ICON_SIZES:
        data = (gui.ASSETS / ("icon-%d.png" % size)).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", data[16:24]) == (size, size)
    icon = (gui.ASSETS / "icon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", icon[:6])
    assert (reserved, kind) == (0, 1) and count >= 4
    # They are installed with the package, and the tool that draws them is in the repository.
    root = gui.ASSETS.parent.parent
    assert "assets/*.png" in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert (root / "tools" / "make_icon.py").is_file()


@pytest.mark.req("CLI-007")
def test_window_is_opened_by_no_arguments_by_gui_and_by_a_dropped_folder(game):
    assert cli.window_wanted([]) == (True, None)
    assert cli.window_wanted(["gui"]) == (True, None)
    assert cli.window_wanted(["gui", str(game)]) == (True, str(game))
    # A folder dropped on the program arrives as its only argument, in a console of its own.
    assert cli.window_wanted([str(game)], alone=True) == (True, str(game))
    # The same argument typed into a terminal is a run in the terminal (CLI-001).
    assert cli.window_wanted([str(game)], alone=False) == (False, None)
    assert cli.window_wanted([str(game), "--jobs", "1"], alone=True) == (False, None)
    assert cli.window_wanted(["--version"], alone=True) == (False, None)
    assert cli.window_wanted(["info", str(game)], alone=False) == (False, None)
    assert cli.window_wanted(["no-such-folder"], alone=True) == (False, None)


@pytest.mark.req("CLI-007")
def test_gui_command_opens_the_window_with_the_game_and_the_language(monkeypatch, game):
    opened = []
    monkeypatch.setattr(gui, "main", lambda game, lang: opened.append((game, lang)) or 0)
    assert cli.main(["gui", str(game), "--lang", "pt-BR"]) == 0
    assert cli.main([]) == 0
    i18n.set_language("en")
    assert opened == [(str(game), "pt-BR"), (None, None)]


@pytest.mark.req("COMPAT-007", "CLI-003")
def test_python_without_tk_says_what_to_install_and_the_command_line_still_works(monkeypatch, capsys, game):
    real_import = builtins.__import__

    def no_tk(name, *args, **kwargs):
        if name == "tkinter" or name.startswith("tkinter."):
            raise ImportError("No module named 'tkinter'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_tk)
    with pytest.raises(ToolError) as raised:
        gui.main()
    assert raised.value.message_id == "error.no_tkinter"

    assert cli.main(["gui"]) == 3
    text = capsys.readouterr().out
    assert "python3-tk" in text and "renpytester GAME" in text
    # Nothing about the command line needs Tk: its options are still read and checked.
    assert cli.main([str(game), "--stages", "nonsense", "--lang", "en"]) == 2
    assert "Unknown stage" in capsys.readouterr().out
