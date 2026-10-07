"""End-to-end tests of the window (spec 4.14): real widgets, a real engine, the fixture games.

The window is built but never shown, so nothing appears on the screen of whoever runs the tests.
Without Tk, or without a display to build widgets on, these tests are skipped.
"""

import gc
import json
import sys
import time

import pytest

from renpytester import cli, gui, i18n, runner, sandbox
from tests.conftest import folder_digest

pytestmark = pytest.mark.e2e

# What the status line is about while the story is played: the stage, then, once the game has
# reported in, how far it has got. Which of the two is showing at a given moment depends on timing.
PLAYING = ("console.stage.routes", "gui.playing")


class Driver:
    """Does to a window what a person would, and waits the way a person would."""

    def __init__(self, root, window, session):
        self.root, self.window, self.session = root, window, session

    def wait(self, condition, seconds=90):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def choose(self, game):
        self.window.game_var.set(str(game))
        self.window.game_chosen()
        assert self.wait(lambda: self.window.detected or self.window.problems), "the game was never looked at"

    def run(self, seconds=120):
        assert str(self.window.run_button["state"]) == "normal"
        self.window.run_button.invoke()
        assert self.wait(lambda: not self.session.busy and self.window.result is not None, seconds)
        self.root.update()

    def rows(self):
        tree = self.window.findings
        return [tuple(tree.item(row, "values")) for row in tree.get_children()]

    def state(self, widget):
        return str(widget["state"])


@pytest.fixture
def open_window(sdk, tmp_path, monkeypatch):
    """Returns a function that builds a window, not shown, on a session with the SDK already chosen."""
    try:
        import tkinter
    except ImportError:
        pytest.skip("this Python has no Tk")
    monkeypatch.setattr(gui, "default_output", lambda: tmp_path / "report")
    monkeypatch.delenv("RENPY_SDK", raising=False)
    roots = []

    def build(lang="en", with_sdk=True):
        root = None
        for attempt in range(3):
            try:
                root = tkinter.Tk()
                break
            except tkinter.TclError as error:
                # On Windows, starting Tk many times in one process now and then fails to read its
                # own files; a second try works. With no display at all, every try fails.
                if attempt == 2:
                    pytest.skip("no display to build a window on: %s" % error)
                time.sleep(0.2)
        root.withdraw()
        roots.append(root)
        session = gui.Session()
        session.lang = i18n.set_language(lang)
        session.sdk = str(sdk) if with_sdk else ""
        return Driver(root, gui.Window(root, session), session)

    yield build
    i18n.set_language("en")
    for root in roots:
        try:
            root.destroy()
        except tkinter.TclError:
            pass
    # Tk may only be spoken to, and taken apart, by the thread that made it. Python frees what is
    # no longer used whenever it likes, in whichever thread happens to be running, and one test's
    # window being freed in the next test's worker thread stops the whole process. So everything
    # of these windows is let go of here and now. Their variables are first told that there is
    # no window left to say goodbye to.
    for item in gc.get_objects():
        if isinstance(item, tkinter.Variable):
            item._tk = None
    roots.clear()
    gc.collect()


def cli_findings(game, sdk, output, lang):
    code = cli.main([str(game), "--sdk", str(sdk), "--output", str(output), "--lang", lang])
    report = json.loads(next(output.glob("report-*.json")).read_text(encoding="utf-8"))
    return code, report


@pytest.mark.req("GUI-001", "GUI-002", "GUI-006")
def test_choosing_a_game_shows_what_it_is_and_offers_its_languages(open_window, game_copy, sdk):
    driver = open_window()
    window = driver.window
    assert window.detected_var.get() == "Choose the folder of a Ren'Py game to begin."
    assert driver.state(window.run_button) == "disabled"

    game = game_copy("tl_untranslated")
    before = folder_digest(game)
    driver.choose(game / "game")
    assert window.detected_var.get().startswith("Untranslated Fixture  ·  Ren'Py 8.")
    assert "project, using the SDK" in window.detected_var.get()
    assert sorted(window.language_vars) == ["portuguese", "spanish"]
    assert all(variable.get() for variable in window.language_vars.values())
    # A project needs an SDK, so the window asks for one; here it already has it.
    assert window.sdk_row.winfo_manager() == "grid"
    assert driver.state(window.run_button) == "normal"
    assert window.output_var.get().startswith("Reports are saved in ")
    assert folder_digest(game) == before

    # Something that is not a game is said so in the window, and cannot be run.
    driver.choose(game.parent.parent)
    assert "No Ren'Py game found" in window.detected_var.get()
    assert driver.state(window.run_button) == "disabled"
    assert window.command_var.get() == ""


@pytest.mark.req("GUI-001", "GUI-002", "GUI-006", "GAME-005")
def test_project_with_no_sdk_is_asked_for_one_in_the_window(open_window, game_copy, sdk):
    driver = open_window(with_sdk=False)
    window = driver.window
    driver.choose(game_copy("clean"))
    assert "does not include a Ren'Py engine" in window.detected_var.get()
    assert window.sdk_row.winfo_manager() == "grid"
    assert driver.state(window.run_button) == "disabled"

    window.sdk_var.set(str(sdk))
    window.sdk_chosen()
    assert driver.wait(lambda: window.detected is not None)
    assert window.detected_var.get().startswith("Clean Fixture 1.0")
    assert driver.state(window.run_button) == "normal"
    assert "--sdk" in window.command_var.get()


@pytest.mark.req("GUI-003", "GUI-004", "GUI-005", "GUI-007", "GUI-008", "GUI-009", "ARCH-006")
@pytest.mark.parametrize("lang", ["en", "pt-BR"])
def test_run_from_the_window_finds_what_the_command_line_finds(open_window, game_copy, sdk, tmp_path, capsys, lang):
    game = game_copy("two_bugs")
    before = folder_digest(game)
    driver = open_window(lang)
    window = driver.window
    driver.choose(game)

    assert window.run_button["text"] == ("Run" if lang == "en" else "Executar")
    driver.run()

    # The result: failed, with the counts, and the report one click away (GUI-005).
    assert window.result[0] == "finished"
    assert window.result_var.get().startswith("FAILED" if lang == "en" else "FALHOU")
    assert ("2 errors" if lang == "en" else "2 erros") in window.result_var.get()
    assert window.counts_var.get().split() == (["Errors:", "2", "Warnings:", "0"] if lang == "en" else [
        "Erros:", "2", "Avisos:", "0"])
    assert window.bar["value"] == 100
    assert driver.state(window.report_button) == "normal"
    assert window.paths["html"].is_file() and window.paths["html"].parent == tmp_path / "report"
    assert window.run_button["text"] == ("Run" if lang == "en" else "Executar")
    assert folder_digest(game) == before

    # The same findings as the command the window displays, in the same language (GUI-007, 7.4 item 7).
    from_window = json.loads(window.paths["json"].read_text(encoding="utf-8"))
    assert "--lang " + lang in window.command_var.get()
    code, from_cli = cli_findings(game, sdk, tmp_path / "cli-report", lang)
    capsys.readouterr()
    i18n.set_language(lang)
    assert code == 1
    assert from_window["findings"] == from_cli["findings"]
    assert from_window["coverage"] == from_cli["coverage"]
    assert from_window["summary"] == from_cli["summary"]

    # And they are listed in the window, with file and line (GUI-009).
    rows = driver.rows()
    assert [row[1] for row in rows] == ["game/script.rpy:%d" % f["line"] for f in from_cli["findings"]]
    assert all(row[0] == ("error" if lang == "en" else "erro") for row in rows)
    assert all(("The game crashed here" if lang == "en" else "O jogo quebrou aqui") in row[2] for row in rows)

    # What was chosen is remembered for next time (GUI-008).
    remembered = gui.Session()
    remembered.load()
    assert (remembered.game, remembered.sdk, remembered.lang) == (str(game), str(sdk), lang)


@pytest.mark.req("GUI-002", "GUI-007", "TL-001")
def test_choices_in_the_window_change_the_run_and_the_command(open_window, game_copy):
    driver = open_window()
    window = driver.window
    game = game_copy("tl_untranslated")
    driver.choose(game)

    window.stage_vars["lint"].set(False)
    window.stage_vars["routes"].set(False)
    window.language_vars["portuguese"].set(False)
    window.choices_changed()
    assert "--stages translations" in window.command_var.get()
    assert "--languages spanish" in window.command_var.get()
    driver.run()
    report = window.result[1]
    assert report.settings["stages"] == ["translations"]
    assert list(report.stages["translations"]["languages"]) == ["spanish"]
    assert window.result_var.get().startswith("PASSED")
    assert driver.rows() == []

    # With nothing to check, or no language for the translations, there is nothing to run.
    window.language_vars["spanish"].set(False)
    window.choices_changed()
    assert driver.state(window.run_button) == "disabled"
    assert window.status_var.get() == "Choose at least one language, or untick the translations."
    window.stage_vars["translations"].set(False)
    window.choices_changed()
    assert window.status_var.get() == "Choose at least one thing to check."


@pytest.mark.req("GUI-003", "CLI-006", "SAFE-002")
def test_cancel_stops_the_game_restores_the_folder_and_keeps_what_was_found(open_window, game_copy):
    game = game_copy("hang")
    before = folder_digest(game)
    driver = open_window()
    window, session = driver.window, driver.session
    driver.choose(game)
    window.stage_vars["lint"].set(False)
    window.stage_vars["translations"].set(False)
    window.choices_changed()

    window.run_button.invoke()
    assert session.busy
    assert window.run_button["text"] == "Cancel"
    # The window keeps answering while the game runs, and its controls are locked meanwhile (GUI-004).
    assert driver.wait(lambda: window.status_key in PLAYING, 30)
    assert driver.state(window.game_entry) == "disabled"
    driver.wait(lambda: False, 2)

    window.run_button.invoke()
    assert driver.state(window.run_button) == "disabled"
    # Far sooner than the minute the tool would wait for a game that makes no progress.
    assert driver.wait(lambda: not session.busy and window.result is not None, 20)
    driver.root.update()

    assert window.result[0] == "finished"
    report = window.result[1]
    assert (report.complete, report.interrupted) == (False, True)
    assert report.stages["routes"]["status"] == "interrupted"
    assert "INCOMPLETE" in window.result_var.get()
    assert "The game folder has been restored." in window.result_var.get()
    assert window.run_button["text"] == "Run" and driver.state(window.run_button) == "normal"
    assert window.paths["html"].is_file()
    assert folder_digest(game) == before
    assert sorted(p.name for p in (game / "game").iterdir()) == ["script.rpy"]


@pytest.mark.req("GUI-003", "SAFE-002")
def test_closing_the_window_during_a_run_stops_the_run_first(open_window, game_copy):
    import tkinter

    game = game_copy("hang")
    before = folder_digest(game)
    driver = open_window()
    window, session = driver.window, driver.session
    driver.choose(game)
    window.stage_vars["lint"].set(False)
    window.stage_vars["translations"].set(False)
    window.choices_changed()
    window.run_button.invoke()
    assert session.busy, (window.detected_var.get(), window.status_var.get(), window.result_var.get())
    assert driver.wait(lambda: window.status_key in PLAYING, 30), (window.status_key, window.result_var.get())

    window.close()
    assert window.closing

    def closed():
        try:
            return not driver.root.winfo_exists()
        except tkinter.TclError:
            return True

    end = time.time() + 20
    while time.time() < end and not closed():
        try:
            driver.root.update()
        except tkinter.TclError:
            break
        time.sleep(0.01)
    assert closed()
    assert not session.busy
    assert folder_digest(game) == before


@pytest.mark.req("GUI-002", "SAFE-006", "GUI-010", "SAFE-012")
def test_sandbox_can_be_chosen_and_its_copies_managed_from_the_window(open_window, game_copy, own_cache):
    game = game_copy("writes_files")
    before = folder_digest(game)
    driver = open_window()
    window = driver.window
    driver.choose(game)
    window.stage_vars["lint"].set(False)
    window.stage_vars["translations"].set(False)
    window.sandbox_var.set(True)
    window.choices_changed()
    assert "--sandbox" in window.command_var.get()
    driver.run()
    report = window.result[1]
    assert report.sandbox["path"].startswith(str(own_cache))
    assert folder_digest(game) == before

    dialog = window.show_cache()
    driver.root.update()
    tree = next(w for w in dialog.winfo_children()[0].winfo_children() if w.winfo_class() == "Treeview")
    rows = [tree.item(row, "values") for row in tree.get_children()]
    assert [row[0] for row in rows] == [str(game)]
    assert len(sandbox.listing()) == 1

    tree.selection_set(tree.get_children()[0])
    buttons = [w for w in dialog.winfo_children()[0].winfo_children()[-1].winfo_children()]
    delete = next(b for b in buttons if b["text"] == "Delete the selected")
    delete.invoke()
    driver.root.update()
    assert tree.get_children() == ()
    assert sandbox.listing() == []
    dialog.destroy()


@pytest.mark.req("I18N-001", "I18N-002")
def test_language_of_the_window_can_be_changed_in_the_window(open_window, game_copy):
    driver = open_window("en")
    window = driver.window
    driver.choose(game_copy("clean"))
    assert window.run_button["text"] == "Run"
    assert window.findings.heading("what", "text") == "What is wrong"

    # The languages are offered by name, not by code (GUI-012).
    assert window.lang_box["values"] == ("English", "Brazilian Portuguese")
    assert window.lang_var.get() == "English"
    window.lang_box.current(1)
    window.language_chosen()
    assert window.lang_box["values"] == ("Inglês", "Português do Brasil")
    assert window.lang_var.get() == "Português do Brasil"
    driver.root.update()
    assert i18n.get_language() == "pt-BR"
    assert window.run_button["text"] == "Executar"
    assert window.findings.heading("what", "text") == "O que está errado"
    assert "projeto, usando o SDK" in window.detected_var.get()
    assert window.command_var.get().endswith("--lang pt-BR")
    assert driver.session.lang == "pt-BR"
    # Every text that follows the language was changed, not only the ones looked at above.
    english = json.loads((i18n.LOCALE_DIR / "en.json").read_text(encoding="utf-8"))
    for widget, key in window.texts:
        assert widget["text"] != english[key] or english[key] == i18n.t(key), key


@pytest.mark.req("GUI-006", "NFR-004")
def test_failure_of_the_tool_itself_is_shown_in_the_window(open_window, game_copy, monkeypatch):
    driver = open_window()
    window = driver.window
    driver.choose(game_copy("clean"))

    def broken(*_arguments, **_named):
        raise RuntimeError("something RenPyTester did wrong")

    monkeypatch.setattr(runner, "run", broken)
    driver.run(seconds=20)
    assert window.result[0] == "problem"
    assert "This is a bug in RenPyTester, not a problem in your game." in window.result_var.get()
    assert "something RenPyTester did wrong" in window.result_var.get()
    assert driver.state(window.run_button) == "normal"
    assert driver.state(window.report_button) == "disabled"


def texts_in(widget):
    """Every text shown by a widget and the widgets inside it."""
    found = []
    for child in widget.winfo_children():
        if "text" in child.keys() and child["text"]:
            found.append(str(child["text"]))
        found.extend(texts_in(child))
    return found


@pytest.mark.req("GUI-013")
def test_window_has_the_programs_icon_and_opens_without_it_if_it_must(open_window, monkeypatch, tmp_path):
    window = open_window().window
    assert [(icon.width(), icon.height()) for icon in window.icons] == [(size, size) for size in gui.ICON_SIZES]
    # Windows files a program run by Python under Python, unless the program gives its own name.
    assert gui.TASKBAR_NAME == "CyBearNairus.RenPyTester"
    gui.name_for_taskbar()
    if sys.platform == "win32":
        # Ask Windows itself: the window has an icon of its own, small (title bar) and big (taskbar).
        import ctypes
        from ctypes import wintypes

        send = ctypes.windll.user32.SendMessageW
        send.restype = ctypes.c_void_p
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        window.root.update()
        frame = int(window.root.wm_frame(), 16)
        assert send(frame, 0x7F, 0, 0) and send(frame, 0x7F, 1, 0)

    monkeypatch.setattr(gui, "ASSETS", tmp_path / "no-icons-here")
    bare = open_window().window
    assert bare.icons == []
    assert bare.run_button["text"] == "Run"


@pytest.mark.req("GUI-014", "SAFE-008")
@pytest.mark.parametrize("lang", ["en", "pt-BR"])
def test_about_gives_the_version_the_author_and_the_repository(open_window, monkeypatch, lang):
    from renpytester import __version__

    opened = []
    monkeypatch.setattr(gui.webbrowser, "open", opened.append)
    driver = open_window(lang)
    window = driver.window
    about = next(widget for widget, key in window.texts if key == "gui.about")
    assert about["text"] == ("About..." if lang == "en" else "Sobre...")

    about.invoke()
    driver.root.update()
    dialog = next(child for child in driver.root.winfo_children() if child.winfo_class() == "Toplevel")
    assert dialog.title() == ("About RenPyTester" if lang == "en" else "Sobre o RenPyTester")
    texts = texts_in(dialog)
    assert "RenPyTester" in texts
    assert ("Version %s" if lang == "en" else "Versão %s") % __version__ in texts
    assert ("Created by CyBearNairus." if lang == "en" else "Criado por CyBearNairus.") in texts
    assert "https://github.com/CyBearNairus/RenPyTester" in texts
    assert any("GNU" in text for text in texts)

    # Nothing goes to the network until the address is clicked (SAFE-008).
    assert opened == []
    link = next(child for child in dialog.winfo_children()[0].winfo_children()
                if str(child["text"]).startswith("https://"))
    link.invoke()
    assert opened == ["https://github.com/CyBearNairus/RenPyTester"]
    dialog.destroy()
