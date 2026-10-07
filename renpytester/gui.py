"""The window (spec 4.14).

It is a front end to the run the command line makes, never a second way of testing a game: it
gathers the same choices, hands them to the same `runner.prepare` and `runner.run`, and shows
what comes back. Every run it makes can be written as a command line, and it shows that command.

There are two parts. `Session` holds what is being worked on and does the work, in threads, with
no widgets; everything it has to say goes into a queue. `Window` is the widgets: it reads the
queue and never touches the game. Tk is imported only when a window is really opened, so the
command line works on a Python that has no Tk (COMPAT-007).
"""

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

from renpytester import __author__, __url__, __version__, discovery, i18n, runner, sandbox
from renpytester import report as reports
from renpytester.errors import ToolError
from renpytester.i18n import t
from renpytester.model import ERROR, WARNING

# Where the window keeps the last game and choices, when not in the usual place (GUI-008).
STATE_VARIABLE = "RENPYTESTER_GUI_STATE"
# The program's icon, in several sizes; made by tools/make_icon.py (GUI-013).
ASSETS = Path(__file__).resolve().parent / "assets"
ICON_SIZES = (16, 32, 48, 256)
# What Windows files the program's windows under on the taskbar. Without a name of its own, a
# program run by Python is filed under Python, and shown with Python's icon.
TASKBAR_NAME = "CyBearNairus.RenPyTester"


def language_name(code):
    """What an interface language is called, in the interface language of the moment (GUI-012)."""
    return t("language." + code)


def name_for_taskbar():
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(TASKBAR_NAME)
        except Exception:
            pass  # An older Windows; the window still opens, filed under Python.


def load_icons(root):
    """Gives the window the program's icon (GUI-013).

    Returns the icon as images, which must be kept for as long as the window is open. A window
    that cannot have its icon is still a window: any failure here is passed over.
    """
    import tkinter

    images = []
    try:
        images = [tkinter.PhotoImage(master=root, file=str(ASSETS / ("icon-%d.png" % size))) for size in ICON_SIZES]
    except (tkinter.TclError, OSError):
        images = []
    set_icon(root, images)
    return images


def set_icon(window, images):
    """Gives one window the program's icon. Each window is given it by itself: on Windows, Tk's ways
    of setting an icon for every window at once were found to set none (checked with Tk 8.6)."""
    import tkinter

    try:
        if sys.platform == "win32":
            window.iconbitmap(str(ASSETS / "icon.ico"))
        elif images:
            window.iconphoto(False, *images)
    except (tkinter.TclError, OSError):
        pass


def state_file():
    if os.environ.get(STATE_VARIABLE):
        return Path(os.environ[STATE_VARIABLE]).expanduser()
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "RenPyTester" / "window.json"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "RenPyTester" / "window.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "renpytester" / "window.json"


def default_output():
    """Where a run started from the window saves its reports, unless the game's config file says.

    A window has no "current folder" that means anything to the person using it, so the command
    line's default, a folder beside wherever the command was typed, will not do.
    """
    return Path.home() / "renpytester-report"


def command_line(parts):
    """A list of arguments as one line that the user's own terminal understands."""
    return subprocess.list2cmdline(parts) if sys.platform == "win32" else shlex.join(parts)


class Session:
    """The game, the choices made in the window, and the run under way. No widgets."""

    def __init__(self, path=None):
        self.path = Path(path) if path else state_file()
        self.game = ""
        self.sdk = ""
        self.stages = list(runner.STAGES)
        # The game's languages to check; None is all of them.
        self.languages = None
        self.sandbox = False
        # The interface language: the system's, until the window has been used in another.
        self.lang = i18n.detect()
        # What the threads have to tell the window, as tuples whose first part says what kind.
        self.events = queue.Queue()
        self.thread = None
        self.stop = None
        self.looking = 0

    # ----------------------------------------------------------- remembered choices (GUI-008)

    def load(self):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        if isinstance(saved.get("game"), str):
            self.game = saved["game"]
        if isinstance(saved.get("sdk"), str):
            self.sdk = saved["sdk"]
        if isinstance(saved.get("stages"), list):
            self.stages = [name for name in runner.STAGES if name in saved["stages"]]
        if isinstance(saved.get("languages"), list):
            self.languages = [name for name in saved["languages"] if isinstance(name, str)]
        self.sandbox = saved.get("sandbox") is True
        if i18n.normalise(saved.get("lang") if isinstance(saved.get("lang"), str) else None):
            self.lang = i18n.normalise(saved["lang"])

    def save(self):
        saved = {
            "game": self.game, "sdk": self.sdk, "stages": self.stages, "languages": self.languages,
            "sandbox": self.sandbox, "lang": self.lang}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        except OSError:
            pass  # Not being able to remember is no reason to stop.

    # --------------------------------------------------------- the run, as settings (GUI-007)

    def given(self):
        """What the window asks for, the way the command line would: only what differs from the defaults."""
        given = {"sdk": self.sdk or None, "sandbox": True if self.sandbox else None}
        if tuple(self.stages) != runner.STAGES:
            given["stages"] = tuple(name for name in runner.STAGES if name in self.stages)
        if self.languages is not None and runner.TRANSLATIONS in self.stages:
            given["languages"] = tuple(self.languages)
        return given

    def plan(self):
        """Returns (the options of the run the window would make now, the same run as a command line).

        Raises ToolError when the game or its config file will not do; the message says why.
        """
        given = self.given()
        _options, settings = runner.prepare(self.game, {})
        if "output" not in settings.settings:
            given["output"] = str(default_output())
        options, _settings = runner.prepare(self.game, given)

        parts = ["renpytester", self.game]
        for name in ("sdk", "output"):
            if given.get(name):
                parts += ["--" + name, given[name]]
        for name in ("stages", "languages"):
            if given.get(name) is not None:
                parts += ["--" + name, ",".join(given[name])]
        if given.get("sandbox"):
            parts.append("--sandbox")
        parts += ["--lang", self.lang]
        return options, command_line(parts)

    # ------------------------------------------------------------------------------ threads

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def look(self):
        """Finds out what the game is, in the background (GUI-001). The answer arrives as a
        "looked" event; one that was overtaken by a later question says so by its number."""
        self.looking += 1
        number = self.looking

        def work():
            try:
                options, _settings = runner.prepare(self.game, {"sdk": self.sdk or None})
                found = runner.describe(options)
                problems = ["%s  %s" % (reports.where(f), reports.message(f)) for f in found.to_dict()["findings"]]
                self.events.put(("looked", number, dict(found.game, kind=found.game_kind), problems))
            except ToolError as error:
                self.events.put(("looked", number, None, [t(error.message_id, **error.params)]))
            except Exception:
                self.events.put(("looked", number, None, [t("error.internal") + "\n" + traceback.format_exc()]))

        threading.Thread(target=work, daemon=True).start()
        return number

    def start(self):
        """Starts the run, in the background (GUI-003, GUI-004). Its progress arrives as "progress"
        events, and its end as one of "finished", "stopped" or "problem"."""
        options, _command = self.plan()
        self.stop = threading.Event()

        def progress(kind, **data):
            self.events.put(("progress", kind, data))

        def work():
            try:
                result = runner.run(options, progress, self.stop)
                paths = reports.write_all(result, options.output)
                failed = result.failed(options.fail_on, options.fail_on_possible)
                self.events.put(("finished", result, paths, failed))
            except ToolError as error:
                self.events.put(("problem", t(error.message_id, **error.params)))
            except KeyboardInterrupt:
                self.events.put(("stopped",))  # Stopped before there was anything to report.
            except Exception:
                # Anything unexpected is our fault, never the game's (NFR-004).
                self.events.put(("problem", t("error.internal") + "\n" + traceback.format_exc()))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def cancel(self):
        """Stops the run the way Ctrl+C does: the game folder is restored and what was found is kept."""
        if self.stop is not None:
            self.stop.set()


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class Window:
    """The widgets. Everything slow happens in the session's threads; this only shows and asks."""

    PAD = 8

    def __init__(self, root, session):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.session = session
        self.texts = []
        self.detected = None
        self.problems = []
        self.needs_sdk = False
        self.paths = None
        self.closing = False
        self.counts = {ERROR: 0, WARNING: 0}
        self.result = None
        self.status_key = None
        self.icons = load_icons(root)

        self.game_var = tk.StringVar(value=session.game)
        self.sdk_var = tk.StringVar(value=session.sdk)
        self.stage_vars = {name: tk.BooleanVar(value=name in session.stages) for name in runner.STAGES}
        self.language_vars = {}
        self.retired = []
        self.sandbox_var = tk.BooleanVar(value=session.sandbox)
        self.lang_var = tk.StringVar()
        self.command_var = tk.StringVar()
        self.detected_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.counts_var = tk.StringVar()
        self.result_var = tk.StringVar()
        self.output_var = tk.StringVar()

        self.build()
        self.retranslate()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self.callback_failed
        self.game_chosen(remember=False)
        self.pump()

    # ------------------------------------------------------------------------------ building

    def label(self, parent, key, **options):
        """A label whose text follows the interface language."""
        widget = self.ttk.Label(parent, **options)
        self.texts.append((widget, key))
        return widget

    def button(self, parent, key, command):
        widget = self.ttk.Button(parent, command=command)
        self.texts.append((widget, key))
        return widget

    def check(self, parent, key, variable, command):
        widget = self.ttk.Checkbutton(parent, variable=variable, command=command)
        self.texts.append((widget, key))
        return widget

    def build(self):
        tk, ttk, pad = self.tk, self.ttk, self.PAD
        self.root.minsize(760, 560)
        outer = ttk.Frame(self.root, padding=pad * 2)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        row = 0

        # ---- The game (GUI-001)
        self.label(outer, "gui.game").grid(row=row, column=0, sticky="w")
        self.game_entry = ttk.Entry(outer, textvariable=self.game_var)
        self.game_entry.grid(row=row, column=1, sticky="ew", padx=pad)
        self.game_entry.bind("<Return>", lambda _event: self.game_chosen())
        self.game_entry.bind("<FocusOut>", lambda _event: self.game_chosen())
        self.game_browse = self.button(outer, "gui.browse", self.browse_game)
        self.game_browse.grid(row=row, column=2)
        row += 1
        self.detected_label = ttk.Label(outer, textvariable=self.detected_var, wraplength=700, justify="left")
        self.detected_label.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(2, pad))
        row += 1

        # ---- The SDK, only for a game that needs one (GUI-002)
        self.sdk_row = ttk.Frame(outer)
        self.sdk_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, pad))
        self.sdk_row.columnconfigure(1, weight=1)
        self.label(self.sdk_row, "gui.sdk").grid(row=0, column=0, sticky="w")
        self.sdk_entry = ttk.Entry(self.sdk_row, textvariable=self.sdk_var)
        self.sdk_entry.grid(row=0, column=1, sticky="ew", padx=pad)
        self.sdk_entry.bind("<Return>", lambda _event: self.sdk_chosen())
        self.sdk_entry.bind("<FocusOut>", lambda _event: self.sdk_chosen())
        self.sdk_browse = self.button(self.sdk_row, "gui.browse", self.browse_sdk)
        self.sdk_browse.grid(row=0, column=2)
        self.label(self.sdk_row, "gui.sdk_hint", wraplength=700, justify="left").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=pad)
        row += 1

        # ---- What to check (GUI-002)
        self.label(outer, "gui.checks").grid(row=row, column=0, sticky="nw")
        checks = ttk.Frame(outer)
        checks.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad)
        self.stage_checks = []
        for column, name in enumerate(runner.STAGES):
            widget = self.check(checks, "gui.stage." + name, self.stage_vars[name], self.choices_changed)
            widget.grid(row=0, column=column, sticky="w", padx=(0, pad * 2))
            self.stage_checks.append(widget)
        row += 1
        self.languages_label = self.label(outer, "gui.languages")
        self.languages_label.grid(row=row, column=0, sticky="nw", pady=(pad, 0))
        self.languages_frame = ttk.Frame(outer)
        self.languages_frame.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(pad, 0))
        row += 1
        self.sandbox_check = self.check(outer, "gui.sandbox", self.sandbox_var, self.choices_changed)
        self.sandbox_check.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(pad, 0))
        row += 1

        # ---- The same run as a command (GUI-007)
        self.label(outer, "gui.command").grid(row=row, column=0, sticky="w", pady=(pad * 2, 0))
        self.command_entry = ttk.Entry(outer, textvariable=self.command_var, state="readonly")
        self.command_entry.grid(row=row, column=1, sticky="ew", padx=pad, pady=(pad * 2, 0))
        self.button(outer, "gui.copy", self.copy_command).grid(row=row, column=2, pady=(pad * 2, 0))
        row += 1

        # ---- Running (GUI-003, GUI-004)
        running = ttk.Frame(outer)
        running.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(pad * 2, 0))
        running.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(running, command=self.run_or_cancel)
        self.run_button.grid(row=0, column=0, rowspan=2, sticky="ns")
        self.bar = ttk.Progressbar(running, maximum=100)
        self.bar.grid(row=0, column=1, sticky="ew", padx=pad)
        ttk.Label(running, textvariable=self.counts_var).grid(row=0, column=2, sticky="e")
        ttk.Label(running, textvariable=self.status_var).grid(row=1, column=1, columnspan=2, sticky="w", padx=pad)
        row += 1

        # ---- The result (GUI-005, GUI-006)
        result = ttk.Frame(outer)
        result.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(pad, 0))
        result.columnconfigure(0, weight=1)
        self.result_label = tk.Label(
            result, textvariable=self.result_var, anchor="w", justify="left", wraplength=560,
            font=("TkDefaultFont", 11, "bold"))
        self.result_label.grid(row=0, column=0, sticky="w")
        self.report_button = self.button(result, "gui.open_report", self.open_report)
        self.report_button.grid(row=0, column=1, padx=(pad, 0))
        self.folder_button = self.button(result, "gui.open_folder", self.open_report_folder)
        self.folder_button.grid(row=0, column=2, padx=(pad, 0))
        ttk.Label(result, textvariable=self.output_var, wraplength=700, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w")
        row += 1

        # ---- The findings (GUI-009), and, in the same place, a message that stops a run (GUI-006)
        self.findings = ttk.Treeview(outer, columns=("kind", "where", "what"), show="headings", height=9)
        self.findings.column("kind", width=110, stretch=False)
        self.findings.column("where", width=230, stretch=False)
        self.findings.column("what", width=380)
        self.findings.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(pad, 0))
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.findings.yview)
        scroll.grid(row=row, column=3, sticky="ns", pady=(pad, 0))
        self.findings.configure(yscrollcommand=scroll.set)
        outer.rowconfigure(row, weight=1)
        row += 1

        # ---- The window's own language, and the copies the sandbox keeps (I18N-002, GUI-010)
        bottom = ttk.Frame(outer)
        bottom.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(pad, 0))
        bottom.columnconfigure(2, weight=1)
        self.label(bottom, "gui.language").grid(row=0, column=0)
        # The languages are listed by name, in the order of i18n.LANGUAGES (GUI-012).
        self.lang_box = ttk.Combobox(bottom, textvariable=self.lang_var, state="readonly", width=24)
        self.lang_box.grid(row=0, column=1, padx=pad)
        self.lang_box.bind("<<ComboboxSelected>>", lambda _event: self.language_chosen())
        self.cache_button = self.button(bottom, "gui.cache", self.show_cache)
        self.cache_button.grid(row=0, column=3)
        self.button(bottom, "gui.about", self.show_about).grid(row=0, column=4, padx=(pad, 0))

    def retranslate(self):
        """Puts every text of the window in the interface language (I18N-001)."""
        self.root.title(t("gui.title"))
        for widget, key in self.texts:
            widget.configure(text=t(key))
        self.lang_box.configure(values=[language_name(code) for code in i18n.LANGUAGES])
        self.lang_var.set(language_name(self.session.lang))
        self.findings.heading("kind", text=t("gui.column.kind"))
        self.findings.heading("where", text=t("gui.column.where"))
        self.findings.heading("what", text=t("gui.column.what"))
        self.show_detected()
        self.show_result()
        self.refresh()

    # ----------------------------------------------------------------------- the game (GUI-001)

    def browse_game(self):
        from tkinter import filedialog

        chosen = filedialog.askdirectory(title=t("gui.choose_game"), mustexist=True)
        if chosen:
            self.game_var.set(str(Path(chosen)))
            self.game_chosen()

    def browse_sdk(self):
        from tkinter import filedialog

        chosen = filedialog.askdirectory(title=t("gui.choose_sdk"), mustexist=True)
        if chosen:
            self.sdk_var.set(str(Path(chosen)))
            self.sdk_chosen()

    def game_chosen(self, remember=True):
        game = self.game_var.get().strip().strip('"')
        if game == self.session.game and (self.detected or self.problems) and remember:
            return
        if remember and game != self.session.game:
            self.session.languages = None  # Another game: its languages are other languages.
        self.session.game = game
        self.look()

    def sdk_chosen(self):
        sdk = self.sdk_var.get().strip().strip('"')
        if sdk != self.session.sdk:
            self.session.sdk = sdk
            self.look()

    def look(self):
        """Asks what the game is, and meanwhile says that it is being looked at."""
        self.detected, self.problems, self.needs_sdk = None, [], False
        self.set_languages([])
        if self.session.game:
            try:
                self.needs_sdk = not discovery.is_engine(discovery.resolve_basedir(self.session.game))
            except ToolError as error:
                self.problems = [t(error.message_id, **error.params)]
            else:
                if self.needs_sdk and not self.session.sdk and os.environ.get("RENPY_SDK"):
                    # The SDK the environment names would be used anyway; show it, so that the
                    # window and the command it displays say what the run will really use.
                    self.session.sdk = os.environ["RENPY_SDK"]
                    self.sdk_var.set(self.session.sdk)
                self.session.look()
                self.detected_var.set(t("gui.looking"))
                self.refresh()
                return
        self.show_detected()
        self.refresh()

    def show_detected(self):
        if self.detected:
            game = self.detected
            name = " ".join(part for part in (game.get("name"), game.get("version")) if part)
            self.detected_var.set(t(
                "gui.detected", name=name or "?", renpy=game.get("renpy_version") or "?",
                kind=t("kind." + game["kind"])))
        elif self.problems:
            self.detected_var.set("\n".join(self.problems))
        elif not self.session.game:
            self.detected_var.set(t("gui.no_game"))
        self.detected_label.configure(foreground="#b3261e" if self.problems else "")

    def set_languages(self, names):
        """One box for each language the game has, all ticked unless fewer were chosen before."""
        for child in self.languages_frame.winfo_children():
            child.destroy()
        chosen = self.session.languages
        # The old boxes' variables are kept, not dropped: Python might otherwise let go of them
        # while a thread of the session is running, and Tk may only be spoken to from this one.
        self.retired.extend(self.language_vars.values())
        self.language_vars = {}
        for index, name in enumerate(names):
            self.language_vars[name] = self.tk.BooleanVar(value=chosen is None or name in chosen)
            self.ttk.Checkbutton(
                self.languages_frame, text=name, variable=self.language_vars[name],
                command=self.choices_changed).grid(row=index // 5, column=index % 5, sticky="w", padx=(0, 16))
        if names:
            self.languages_label.grid()
            self.languages_frame.grid()
        else:
            self.languages_label.grid_remove()
            self.languages_frame.grid_remove()

    # ------------------------------------------------------------------ the choices (GUI-002)

    def choices_changed(self):
        session = self.session
        session.stages = [name for name in runner.STAGES if self.stage_vars[name].get()]
        session.sandbox = self.sandbox_var.get()
        if self.language_vars:
            ticked = [name for name, variable in self.language_vars.items() if variable.get()]
            session.languages = None if len(ticked) == len(self.language_vars) else ticked
        self.refresh()

    def language_chosen(self):
        # By its place in the list, not by its name: the names change with the language.
        chosen = self.lang_box.current()
        if chosen >= 0:
            self.session.lang = i18n.set_language(i18n.LANGUAGES[chosen])
        self.retranslate()

    def refresh(self):
        """Brings the command line and what can be clicked in line with the choices."""
        session = self.session
        busy = session.busy
        ready, command, reason = False, "", ""
        if session.game and not self.problems:
            if not session.stages:
                reason = t("gui.need_stage")
            elif session.languages == [] and runner.TRANSLATIONS in session.stages and self.language_vars:
                reason = t("gui.need_language")
            else:
                try:
                    options, command = session.plan()
                    self.output_var.set(t("gui.reports_in", path=options.output))
                    ready = True
                except ToolError as error:
                    reason = t(error.message_id, **error.params)
        self.command_var.set(command)
        if not busy and self.status_key is None:
            self.status_var.set(reason)

        if self.needs_sdk:
            self.sdk_row.grid()
        else:
            self.sdk_row.grid_remove()
        self.run_button.configure(
            text=t("gui.cancel") if busy else t("gui.run"),
            state="normal" if (busy and not session.stop.is_set()) or (ready and not busy) else "disabled")
        state = "disabled" if busy else "normal"
        for widget in (
                self.game_entry, self.game_browse, self.sdk_entry, self.sdk_browse, self.sandbox_check,
                self.cache_button, *self.stage_checks, *self.languages_frame.winfo_children()):
            widget.configure(state=state)
        self.lang_box.configure(state="disabled" if busy else "readonly")
        for widget in (self.report_button, self.folder_button):
            widget.configure(state="normal" if self.paths and not busy else "disabled")

    def copy_command(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.command_var.get())

    # --------------------------------------------------------- running (GUI-003, GUI-004)

    def run_or_cancel(self):
        if self.session.busy:
            self.session.cancel()
            self.set_status("gui.stopping")
            self.refresh()
            return
        self.choices_changed()
        self.result, self.paths = None, None
        self.counts = {ERROR: 0, WARNING: 0}
        self.findings.delete(*self.findings.get_children())
        self.show_result()
        self.show_counts()
        try:
            self.session.start()
        except ToolError as error:
            self.result = ("problem", t(error.message_id, **error.params))
            self.show_result()
            return
        self.session.save()
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        self.set_status("gui.starting")
        self.refresh()

    def set_status(self, key, **values):
        self.status_key = key
        self.status_var.set(t(key, **values) if key else "")

    def show_counts(self):
        self.counts_var.set(t("gui.counts", errors=self.counts[ERROR], warnings=self.counts[WARNING]))

    def pump(self):
        """Takes what the threads had to say and shows it. Runs again a moment later, for as long
        as the window is open; this is what keeps the window answering during a run."""
        try:
            while True:
                self.handle(self.session.events.get_nowait())
        except queue.Empty:
            pass
        if self.closing and not self.session.busy:
            self.root.destroy()
            return
        self.root.after(50, self.pump)

    def handle(self, event):
        kind = event[0]
        if kind == "looked":
            _kind, number, game, problems = event
            if number == self.session.looking and not self.session.busy:
                self.detected, self.problems = game, problems
                self.set_languages((game or {}).get("languages") or [])
                self.show_detected()
                self.refresh()
        elif kind == "progress":
            self.progress(event[1], event[2])
        else:
            self.bar.stop()
            self.bar.configure(mode="determinate", value=100 if kind == "finished" else 0)
            self.set_status(None)
            if kind == "finished":
                _kind, report, self.paths, failed = event
                self.result = ("finished", report, failed)
            elif kind == "stopped":
                self.result = ("stopped",)
            else:
                self.result = ("problem", event[1])
            self.show_result()
            self.refresh()

    def progress(self, kind, data):
        if kind == "stage":
            self.set_status("console.stage." + data["name"])
        elif kind == "sandbox":
            self.set_status("console.copying", done=data["done"], total=data["total"])
        elif kind == "finding":
            finding = data["finding"]
            if not finding.possible and finding.severity in self.counts:
                self.counts[finding.severity] += 1
                self.show_counts()
        elif kind == "step":
            self.bar.stop()
            self.bar.configure(mode="determinate", value=data.get("percent") or 0)
            self.set_status(
                "gui.playing", paths=data.get("paths") or 0, waiting=data.get("waiting") or 0,
                percent=data.get("percent") or 0)

    # ------------------------------------------------------ the result (GUI-005, -006, -009)

    def show_result(self):
        colour = ""
        if self.result is None:
            text = ""
        elif self.result[0] == "finished":
            _kind, report, failed = self.result
            outcome = "incomplete" if not report.complete else ("failed" if failed else "passed")
            totals = t(
                "console.totals", errors=report.count(ERROR), warnings=report.count(WARNING),
                infos=report.count("info"))
            if report.count_possible():
                totals += ", " + t("console.totals_possible", count=report.count_possible())
            text = "%s  %s" % (t("console." + outcome), totals)
            if report.interrupted:
                text = t("cli.interrupted") + "\n" + text
            colour = "#1e6b3a" if outcome == "passed" else "#b3261e"
            self.counts = {ERROR: report.count(ERROR), WARNING: report.count(WARNING)}
            self.show_counts()
        elif self.result[0] == "stopped":
            text = t("cli.interrupted")
        else:
            text, colour = self.result[1], "#b3261e"
        self.result_var.set(text)
        self.result_label.configure(fg=colour or self.ttk.Style().lookup("TLabel", "foreground") or "black")
        if self.result and self.result[0] == "finished":
            self.list_findings(self.result[1])

    def list_findings(self, report):
        self.findings.delete(*self.findings.get_children())
        for finding in report.to_dict()["findings"]:
            kind = t("gui.possible") if finding["possible"] else t("html.severity." + finding["severity"])
            self.findings.insert("", "end", values=(kind, reports.where(finding), reports.message(finding)))

    def open_report(self):
        if self.paths:
            webbrowser.open(Path(self.paths["html"]).resolve().as_uri())

    def open_report_folder(self):
        if self.paths:
            open_folder(Path(self.paths["html"]).parent)

    # ------------------------------------------------------- the sandbox's copies (GUI-010)

    def show_cache(self):
        tk, ttk, pad = self.tk, self.ttk, self.PAD
        dialog = tk.Toplevel(self.root)
        dialog.title(t("gui.cache.title"))
        dialog.transient(self.root)
        set_icon(dialog, self.icons)
        frame = ttk.Frame(dialog, padding=pad * 2)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=t("cache.where", path=str(sandbox.cache_dir())), wraplength=640).pack(anchor="w")
        tree = ttk.Treeview(frame, columns=("game", "size", "used"), show="headings", height=8)
        for column, key, width in (("game", "gui.cache.game", 380), ("size", "gui.cache.size", 100),
                                   ("used", "gui.cache.used", 170)):
            tree.heading(column, text=t(key))
            tree.column(column, width=width)
        tree.pack(fill="both", expand=True, pady=pad)
        total = ttk.Label(frame)
        total.pack(anchor="w")

        def fill():
            tree.delete(*tree.get_children())
            copies = sandbox.listing()
            for entry in copies:
                used = (entry["last_used"] or "?")[:19].replace("T", " ")
                if entry["in_use"]:
                    used = t("gui.cache.in_use")
                tree.insert("", "end", iid=entry["original"], values=(
                    entry["original"], reports.human_size(entry["bytes"]), used))
            size = reports.human_size(sum(entry["bytes"] for entry in copies))
            total.configure(text=t("cache.total", count=len(copies), size=size) if copies else t("cache.empty"))

        def delete(everything):
            for original in ([None] if everything else list(tree.selection())):
                sandbox.clear(original)
            fill()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(pad, 0))
        ttk.Button(buttons, text=t("gui.cache.delete"), command=lambda: delete(False)).pack(side="left")
        ttk.Button(buttons, text=t("gui.cache.delete_all"), command=lambda: delete(True)).pack(side="left", padx=pad)
        ttk.Button(buttons, text=t("gui.close"), command=dialog.destroy).pack(side="right")
        fill()
        return dialog

    # ---------------------------------------------------------------- about (GUI-014)

    def show_about(self):
        tk, ttk, pad = self.tk, self.ttk, self.PAD
        dialog = tk.Toplevel(self.root)
        dialog.title(t("gui.about.title"))
        dialog.transient(self.root)
        set_icon(dialog, self.icons)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=pad * 3)
        frame.pack(fill="both", expand=True)

        if len(self.icons) > 2:
            ttk.Label(frame, image=self.icons[2]).grid(row=0, column=0, rowspan=2, padx=(0, pad * 2), sticky="n")
        ttk.Label(frame, text="RenPyTester", font=("TkDefaultFont", 14, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text=t("gui.about.version", version=__version__)).grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text=t("cli.description"), wraplength=380, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(pad * 2, 0))
        ttk.Label(frame, text=t("gui.about.credit", author=__author__)).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        ttk.Label(frame, text=t("gui.about.licence"), wraplength=380, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w")
        # The one thing in the program that leads to the network, and only when it is clicked (SAFE-008).
        # A button made to look like a link, so that it can be reached and pressed from the keyboard too.
        link = tk.Button(
            frame, text=__url__, fg="#1f5fa8", activeforeground="#1f5fa8", cursor="hand2", relief="flat",
            borderwidth=0, padx=0, pady=0, font=("TkDefaultFont", 9, "underline"),
            command=lambda: self.open_link(__url__))
        link.grid(row=5, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        ttk.Button(frame, text=t("gui.close"), command=dialog.destroy).grid(
            row=6, column=0, columnspan=2, sticky="e", pady=(pad * 2, 0))
        return dialog

    @staticmethod
    def open_link(address):
        webbrowser.open(address)

    # ------------------------------------------------------------------------------ leaving

    def close(self):
        """Closing during a run stops the run first, so that the game folder is put back (SAFE-002)."""
        self.session.save()
        if self.session.busy:
            self.closing = True
            self.session.cancel()
            self.set_status("gui.stopping")
            self.refresh()
        else:
            self.root.destroy()

    def callback_failed(self, _kind, error, trace):
        """A failure in the window's own code is shown in the window, as what it is (GUI-006, NFR-004)."""
        details = "".join(traceback.format_exception(type(error), error, trace))
        self.result = ("problem", t("error.internal") + "\n" + details[-1500:])
        self.show_result()


def main(game=None, lang=None):
    """Opens the window, with `game` already chosen if given (CLI-007). Returns an exit code.

    `lang` is the interface language asked for on the command line; without it, the window uses
    the one it was last used in.
    """
    try:
        import tkinter
        from tkinter import ttk  # noqa: F401  (checked here, used by Window)
    except ImportError:
        raise ToolError("error.no_tkinter") from None
    name_for_taskbar()
    try:
        root = tkinter.Tk()
    except tkinter.TclError as error:
        raise ToolError("error.no_display", message=str(error)) from None

    session = Session()
    session.load()
    if game:
        if str(game) != session.game:
            session.languages = None
        session.game = str(game)
    if lang:
        session.lang = lang
    i18n.set_language(session.lang)
    Window(root, session)
    root.mainloop()
    return 0
