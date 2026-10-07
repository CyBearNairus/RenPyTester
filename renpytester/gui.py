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

from renpytester import __author__, __url__, __version__, discovery, i18n, palette, runner, sandbox
from renpytester import report as reports
from renpytester.errors import ToolError
from renpytester.i18n import t
from renpytester.model import ERROR, INFO, WARNING

# Where the window keeps the last game and choices, when not in the usual place (GUI-008).
STATE_VARIABLE = "RENPYTESTER_GUI_STATE"
# The program's icon, in several sizes; made by tools/make_icon.py (GUI-013).
ASSETS = Path(__file__).resolve().parent / "assets"
ICON_SIZES = (16, 32, 48, 256)
# What Windows files the program's windows under on the taskbar. Without a name of its own, a
# program run by Python is filed under Python, and shown with Python's icon.
TASKBAR_NAME = "CyBearNairus.RenPyTester"
# What the window keeps sums of: the three severities, and possible issues, which are counted apart.
POSSIBLE = "possible"
COUNTED = (ERROR, WARNING, INFO, POSSIBLE)


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
        # Where to save reports; empty is the usual place (GUI-011).
        self.output = ""
        # Whether the window shows the settings a first run does not need (GUI-016).
        self.advanced = False
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
        self.advanced = saved.get("advanced") is True
        if isinstance(saved.get("output"), str):
            self.output = saved["output"]
        if i18n.normalise(saved.get("lang") if isinstance(saved.get("lang"), str) else None):
            self.lang = i18n.normalise(saved["lang"])

    def save(self):
        saved = {
            "game": self.game, "sdk": self.sdk, "stages": self.stages, "languages": self.languages,
            "sandbox": self.sandbox, "output": self.output, "advanced": self.advanced, "lang": self.lang}
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
        # The languages are of use to the checks that are made in each of them.
        if self.languages is not None and {runner.TRANSLATIONS, runner.SCREENS} & set(self.stages):
            given["languages"] = tuple(self.languages)
        return given

    def plan(self):
        """Returns (the options of the run the window would make now, the same run as a command line).

        Raises ToolError when the game or its config file will not do; the message says why.
        """
        given = self.given()
        _options, settings = runner.prepare(self.game, {})
        # The folder chosen in the window; or the one the game's config file names; or the usual one.
        if self.output:
            given["output"] = self.output
        elif "output" not in settings.settings:
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


def make_sharp():
    """Asks Windows to let the program draw at the screen's real resolution. Without this, on a
    screen set to show things larger, Windows stretches the window like a picture, and it blurs."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass  # An older Windows, or already set; the window still opens.


def dark_title_bar(window):
    """Has Windows draw the window's own frame dark, to go with dark contents."""
    if sys.platform == "win32":
        try:
            import ctypes

            window.update_idletasks()
            frame = int(window.wm_frame(), 16)
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(frame, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass


def blend(colours):
    """The average of some "#rrggbb" colours, as one."""
    parts = [[int(colour[i:i + 2], 16) for i in (1, 3, 5)] for colour in colours]
    return "#%02x%02x%02x" % tuple(round(sum(part[i] for part in parts) / len(parts)) for i in range(3))


def tick_box(root, size, margin, around, edge, fill, tick=None):
    """A picture of a tick box, `size` pixels across with `margin` empty pixels after it.

    Tk can only colour whole pixels, so each one is given the average of what a sharper drawing
    would have under it; that is what makes the round corners and the tick look smooth.
    """
    import tkinter

    fine = 4
    radius, line = 0.2, 0.07
    stroke = [((0.24, 0.53), (0.43, 0.71)), ((0.43, 0.71), (0.78, 0.31))]

    def near_stroke(x, y):
        for (ax, ay), (bx, by) in stroke:
            dx, dy = bx - ax, by - ay
            along = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
            if (x - ax - along * dx) ** 2 + (y - ay - along * dy) ** 2 <= 0.075 ** 2:
                return True
        return False

    def colour_at(x, y):
        # How far inside the rounded square the point is; negative is outside.
        qx, qy = abs(x - 0.5) - (0.5 - radius), abs(y - 0.5) - (0.5 - radius)
        outside = (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - radius
        if outside > 0:
            return around
        if tick and near_stroke(x, y):
            return tick
        return edge if outside > -line else fill

    rows = []
    for py in range(size):
        row = []
        for px_ in range(size + margin):
            if px_ >= size:
                row.append(around)
                continue
            samples = [
                colour_at((px_ + (i + 0.5) / fine) / size, (py + (j + 0.5) / fine) / size)
                for i in range(fine) for j in range(fine)]
            row.append(blend(samples))
        rows.append("{" + " ".join(row) + "}")
    image = tkinter.PhotoImage(master=root, width=size + margin, height=size)
    image.put(" ".join(rows))
    return image


def apply_theme(root, colours, px):
    """Dresses Tk's widgets in the colours of the HTML report (GUI-015).

    `px` turns a size in pixels into what it should be on this screen. Everything is done with the
    styles Tk itself has and a few small pictures drawn here; there is no extra library behind the
    look. Returns those pictures, which must be kept for as long as the window is open.
    """
    from tkinter import font as fonts
    from tkinter import ttk

    c = colours
    for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
        try:
            fonts.nametofont(name, root=root).configure(size=10)
        except Exception:
            pass

    style = ttk.Style(root)
    style.theme_use("clam")  # The one built-in theme whose every colour can be set, on every system.
    root.configure(background=c["page"])
    style.configure(
        ".", background=c["card"], foreground=c["ink"], bordercolor=c["line"], lightcolor=c["card"],
        darkcolor=c["card"], troughcolor=c["line"], focuscolor=c["accent"], selectbackground=c["accent"],
        selectforeground=c["accent-ink"], insertcolor=c["ink"])
    style.configure("Page.TFrame", background=c["page"])
    style.configure("Page.TLabel", background=c["page"], foreground=c["soft"])
    style.configure("Soft.TLabel", foreground=c["soft"])
    style.configure("Problem.TLabel", foreground=c["error"])
    style.configure("Title.TLabel", font=("TkDefaultFont", 14, "bold"))
    for kind in ("error", "warning", "info", "possible"):
        style.configure(kind + ".Count.TLabel", foreground=c[kind], font=("TkDefaultFont", 18, "bold"))

    style.configure(
        "TButton", background=c["card"], foreground=c["ink"], bordercolor=c["line"], lightcolor=c["card"],
        darkcolor=c["card"], relief="raised", borderwidth=1, padding=(px(12), px(5)), focuscolor=c["card"])
    style.map(
        "TButton", background=[("disabled", c["card"]), ("pressed", c["line"]), ("active", c["page"])],
        foreground=[("disabled", c["soft"])], bordercolor=[("focus", c["accent"])],
        lightcolor=[("pressed", c["line"]), ("active", c["page"])],
        darkcolor=[("pressed", c["line"]), ("active", c["page"])])
    style.configure(
        "Accent.TButton", background=c["accent"], foreground=c["accent-ink"], bordercolor=c["accent"],
        lightcolor=c["accent"], darkcolor=c["accent"], focuscolor=c["accent"], padding=(px(22), px(9)),
        font=("TkDefaultFont", 10, "bold"))
    style.map(
        "Accent.TButton",
        background=[("disabled", c["line"]), ("pressed", c["accent-hover"]), ("active", c["accent-hover"])],
        foreground=[("disabled", c["soft"])],
        bordercolor=[("disabled", c["line"])], lightcolor=[("disabled", c["line"]), ("active", c["accent-hover"])],
        darkcolor=[("disabled", c["line"]), ("active", c["accent-hover"])])
    style.configure(
        "Link.TButton", foreground=c["accent"], bordercolor=c["card"], padding=(0, px(2)),
        font=("TkDefaultFont", 10, "underline"))
    style.map(
        "Link.TButton", background=[("active", c["card"]), ("pressed", c["card"])],
        foreground=[("active", c["accent-hover"])], bordercolor=[("focus", c["line"])],
        lightcolor=[("active", c["card"]), ("pressed", c["card"])],
        darkcolor=[("active", c["card"]), ("pressed", c["card"])])
    style.configure("Page.TButton", background=c["page"], lightcolor=c["page"], darkcolor=c["page"])
    style.map(
        "Page.TButton", background=[("disabled", c["page"]), ("pressed", c["line"]), ("active", c["card"])],
        lightcolor=[("pressed", c["line"]), ("active", c["card"])],
        darkcolor=[("pressed", c["line"]), ("active", c["card"])])

    style.configure(
        "TEntry", fieldbackground=c["card"], foreground=c["ink"], bordercolor=c["line"], lightcolor=c["card"],
        darkcolor=c["card"], padding=px(5))
    style.map(
        "TEntry", bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])],
        fieldbackground=[("readonly", c["code"]), ("disabled", c["page"])], foreground=[("disabled", c["soft"])])
    style.configure(
        "TCombobox", fieldbackground=c["card"], background=c["card"], foreground=c["ink"], arrowcolor=c["soft"],
        bordercolor=c["line"], lightcolor=c["card"], darkcolor=c["card"], padding=px(4))
    style.map(
        "TCombobox", fieldbackground=[("readonly", c["card"]), ("disabled", c["page"])],
        foreground=[("disabled", c["soft"])], selectbackground=[("readonly", c["card"])],
        selectforeground=[("readonly", c["ink"])], bordercolor=[("focus", c["accent"])])
    for option, value in (("background", c["card"]), ("foreground", c["ink"]),
                          ("selectBackground", c["accent"]), ("selectForeground", c["accent-ink"])):
        root.option_add("*TCombobox*Listbox." + option, value)

    # Tick boxes: the theme's own show a cross when ticked, so the boxes are drawn here.
    size, gap = px(16), px(7)
    boxes = {
        "empty": tick_box(root, size, gap, c["card"], c["soft"], c["card"]),
        "ticked": tick_box(root, size, gap, c["card"], c["accent"], c["accent"], c["accent-ink"]),
        "empty-off": tick_box(root, size, gap, c["card"], c["line"], c["page"]),
        "ticked-off": tick_box(root, size, gap, c["card"], c["line"], c["line"], c["soft"]),
    }
    try:
        style.element_create(
            "Tick.indicator", "image", boxes["empty"], ("disabled", "selected", boxes["ticked-off"]),
            ("disabled", boxes["empty-off"]), ("selected", boxes["ticked"]), sticky="w")
        style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("Tick.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    except Exception:
        pass  # Made already for this Tk; or it will not have them, and the theme's own boxes stay.
    style.configure(
        "TCheckbutton", background=c["card"], foreground=c["ink"], focuscolor=c["card"], padding=(0, px(3)))
    style.map("TCheckbutton", background=[("active", c["card"])], foreground=[("disabled", c["soft"])])

    style.configure(
        "Horizontal.TProgressbar", troughcolor=c["line"], background=c["accent"], bordercolor=c["line"],
        lightcolor=c["accent"], darkcolor=c["accent"], thickness=px(8))
    style.configure(
        "Treeview", background=c["card"], fieldbackground=c["card"], foreground=c["ink"], bordercolor=c["line"],
        lightcolor=c["card"], darkcolor=c["card"], rowheight=px(28), relief="flat")
    style.map(
        "Treeview", background=[("selected", c["accent-soft"])], foreground=[("selected", c["ink"])])
    style.configure(
        "Treeview.Heading", background=c["card"], foreground=c["soft"], bordercolor=c["line"],
        lightcolor=c["card"], darkcolor=c["card"], relief="flat", padding=(px(6), px(6)),
        font=("TkDefaultFont", 9, "bold"))
    style.map("Treeview.Heading", background=[("active", c["page"])])
    style.configure(
        "Vertical.TScrollbar", background=c["line"], troughcolor=c["card"], bordercolor=c["card"],
        lightcolor=c["line"], darkcolor=c["line"], arrowcolor=c["soft"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", c["soft"])])
    return list(boxes.values())


class Window:
    """The widgets. Everything slow happens in the session's threads; this only shows and asks."""

    PAD = 8

    def __init__(self, root, session, dark=None):
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
        self.counts = dict.fromkeys(COUNTED, 0)
        self.result = None
        self.status_key = None
        self.icons = load_icons(root)
        self.planned_output = None
        # Dark or light, as the system is set (GUI-015). The window keeps the one it opened with.
        self.dark = palette.system_is_dark() if dark is None else dark
        self.colours = palette.DARK if self.dark else palette.LIGHT
        # How much larger than usual this screen shows things.
        self.scale = max(root.winfo_fpixels("1i") / 96.0, 1.0)
        self.pictures = apply_theme(root, self.colours, self.px)
        if self.dark:
            dark_title_bar(root)

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
        self.result_var = tk.StringVar()
        self.output_var = tk.StringVar(value=session.output)
        self.saved_var = tk.StringVar()

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

    def button(self, parent, key, command, **options):
        widget = self.ttk.Button(parent, command=command, **options)
        self.texts.append((widget, key))
        return widget

    def check(self, parent, key, variable, command):
        widget = self.ttk.Checkbutton(parent, variable=variable, command=command)
        self.texts.append((widget, key))
        return widget

    def px(self, size):
        """A size in pixels as it should be on this screen, which may be set to show things larger."""
        return max(1, round(size * self.scale))

    def card(self, parent, **grid):
        """A white panel with a thin edge, like the cards of the HTML report. Returns its inside."""
        edge = self.tk.Frame(parent, background=self.colours["line"])
        edge.grid(**grid)
        inside = self.ttk.Frame(edge, padding=self.px(14))
        inside.pack(fill="both", expand=True, padx=1, pady=1)
        return inside

    def marker(self, colour):
        """A small bar of one colour, shown at the start of a finding's row as the HTML report
        shows it at the edge of a finding's box."""
        width, height = self.px(4), self.px(18)
        image = self.tk.PhotoImage(master=self.root, width=width + self.px(6), height=height)
        image.put(colour, to=(self.px(3), 0, self.px(3) + width, height))
        return image

    def build(self):
        tk, ttk, pad = self.tk, self.ttk, self.px(self.PAD)
        self.root.minsize(self.px(840), self.px(560))
        outer = ttk.Frame(self.root, padding=pad * 2, style="Page.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        wrap = self.px(700)

        # ---- The game (GUI-001). This is all a first run needs; the rest is one click away (GUI-016).
        game = self.card(outer, row=0, column=0, sticky="ew")
        game.columnconfigure(1, weight=1)
        row = 0
        self.label(game, "gui.game", style="Soft.TLabel").grid(row=row, column=0, sticky="w")
        self.game_entry = ttk.Entry(game, textvariable=self.game_var)
        self.game_entry.grid(row=row, column=1, sticky="ew", padx=pad)
        self.game_entry.bind("<Return>", lambda _event: self.game_chosen())
        self.game_entry.bind("<FocusOut>", lambda _event: self.game_chosen())
        self.game_browse = self.button(game, "gui.browse", self.browse_game)
        self.game_browse.grid(row=row, column=2, sticky="ew")
        row += 1
        self.detected_label = ttk.Label(game, textvariable=self.detected_var, wraplength=wrap, justify="left")
        self.detected_label.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(self.px(4), 0))
        row += 1

        # The SDK is not a setting but something a game with no engine cannot be tested without,
        # so it is asked for here, in plain sight, and only for such a game.
        self.sdk_label = self.label(game, "gui.sdk", style="Soft.TLabel")
        self.sdk_label.grid(row=row, column=0, sticky="w", pady=(pad, 0))
        self.sdk_entry = ttk.Entry(game, textvariable=self.sdk_var)
        self.sdk_entry.grid(row=row, column=1, sticky="ew", padx=pad, pady=(pad, 0))
        self.sdk_entry.bind("<Return>", lambda _event: self.sdk_chosen())
        self.sdk_entry.bind("<FocusOut>", lambda _event: self.sdk_chosen())
        self.sdk_browse = self.button(game, "gui.browse", self.browse_sdk)
        self.sdk_browse.grid(row=row, column=2, sticky="ew", pady=(pad, 0))
        row += 1
        self.sdk_hint = self.label(game, "gui.sdk_hint", wraplength=wrap, justify="left", style="Soft.TLabel")
        self.sdk_hint.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(self.px(4), 0))
        self.sdk_widgets = (self.sdk_label, self.sdk_entry, self.sdk_browse, self.sdk_hint)
        row += 1

        self.advanced_button = ttk.Button(game, command=self.toggle_advanced, style="Link.TButton")
        self.advanced_button.grid(row=row, column=0, columnspan=3, sticky="w", pady=(pad, 0))
        row += 1

        # ---- The settings a first run does not need (GUI-002, GUI-016)
        advanced = self.advanced_frame = ttk.Frame(game)
        advanced.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(pad, 0))
        advanced.columnconfigure(1, weight=1)
        row = 0
        # The languages come first: they are the one setting that is the game's own, and differ
        # from one game to the next. A game in one language has none, and the row is not shown.
        self.languages_label = self.label(advanced, "gui.languages", style="Soft.TLabel")
        self.languages_label.grid(row=row, column=0, sticky="nw", pady=(self.px(3), self.px(4)))
        self.languages_frame = ttk.Frame(advanced)
        self.languages_frame.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(0, self.px(4)))
        row += 1
        self.label(advanced, "gui.checks", style="Soft.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(self.px(3), 0))
        checks = ttk.Frame(advanced)
        checks.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad)
        self.stage_checks = []
        for index, name in enumerate(runner.STAGES):
            widget = self.check(checks, "gui.stage." + name, self.stage_vars[name], self.choices_changed)
            # Two to a row: all of them side by side would make the window wider than it need be.
            widget.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, pad * 2))
            self.stage_checks.append(widget)
        row += 1
        # The sandbox, and under it the copies it keeps (SAFE-006, GUI-010): nobody needs the
        # second who has not used the first.
        self.label(advanced, "gui.sandbox_label", style="Soft.TLabel").grid(
            row=row, column=0, sticky="nw", pady=(self.px(7), 0))
        self.sandbox_check = self.check(advanced, "gui.sandbox", self.sandbox_var, self.choices_changed)
        self.sandbox_check.grid(row=row, column=1, columnspan=2, sticky="w", padx=pad, pady=(self.px(4), 0))
        row += 1
        self.cache_button = self.button(advanced, "gui.cache", self.show_cache)
        self.cache_button.grid(row=row, column=1, sticky="w", padx=pad, pady=(self.px(4), 0))
        row += 1

        # Where the reports go (GUI-011).
        self.label(advanced, "gui.output", style="Soft.TLabel").grid(row=row, column=0, sticky="w", pady=(pad, 0))
        self.output_entry = ttk.Entry(advanced, textvariable=self.output_var)
        self.output_entry.grid(row=row, column=1, sticky="ew", padx=pad, pady=(pad, 0))
        self.output_entry.bind("<Return>", lambda _event: self.output_chosen())
        self.output_entry.bind("<FocusOut>", lambda _event: self.output_chosen())
        self.output_browse = self.button(advanced, "gui.browse", self.browse_output)
        self.output_browse.grid(row=row, column=2, sticky="ew", pady=(pad, 0))
        row += 1

        # The same run as a command (GUI-007), across the whole card.
        command = ttk.Frame(advanced)
        command.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(pad * 1.5, 0))
        command.columnconfigure(0, weight=1)
        self.label(command, "gui.command", style="Soft.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.command_entry = ttk.Entry(
            command, textvariable=self.command_var, state="readonly", font=("TkFixedFont", 9))
        self.command_entry.grid(row=1, column=0, sticky="ew", padx=(0, pad), pady=(self.px(3), 0))
        self.button(command, "gui.copy", self.copy_command).grid(row=1, column=1, pady=(self.px(3), 0))
        # The first column is as wide in both parts of the card, so that everything lines up.
        for part in (game, advanced):
            part.grid_columnconfigure(0, minsize=self.px(120))
            part.grid_columnconfigure(2, minsize=self.px(110))

        # ---- Running, and how it went (GUI-003, GUI-004, GUI-005, GUI-006)
        running = self.card(outer, row=1, column=0, sticky="ew", pady=(pad * 1.5, 0))
        running.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(running, command=self.run_or_cancel, style="Accent.TButton")
        self.run_button.grid(row=0, column=0, rowspan=2, sticky="w")
        self.bar = ttk.Progressbar(running, maximum=100)
        self.bar.grid(row=0, column=1, sticky="ew", padx=(pad * 2, 0), pady=(self.px(6), 0))
        ttk.Label(running, textvariable=self.status_var, style="Soft.TLabel").grid(
            row=1, column=1, sticky="w", padx=(pad * 2, 0))

        # The sums, as the HTML report's first screen has them. They count up while the game is played.
        sums = ttk.Frame(running)
        sums.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(pad * 1.5, 0))
        self.count_vars = {}
        for column, (kind, key) in enumerate((
                (ERROR, "html.errors"), (WARNING, "html.warnings"), (INFO, "html.notes"),
                (POSSIBLE, "html.possible"))):
            box = tk.Frame(sums, background=self.colours["line"])
            box.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else pad, 0))
            sums.columnconfigure(column, weight=1, uniform="sums")
            inside = ttk.Frame(box, padding=(self.px(12), self.px(4)))
            inside.pack(fill="both", expand=True, padx=1, pady=1)
            self.count_vars[kind] = tk.StringVar(value="0")
            ttk.Label(inside, textvariable=self.count_vars[kind], style=kind + ".Count.TLabel").pack(anchor="w")
            self.label(inside, key, style="Soft.TLabel").pack(anchor="w")

        result = ttk.Frame(running)
        result.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(pad, 0))
        result.columnconfigure(0, weight=1)
        self.result_label = tk.Label(
            result, textvariable=self.result_var, anchor="w", justify="left", wraplength=self.px(520),
            font=("TkDefaultFont", 12, "bold"), background=self.colours["card"], foreground=self.colours["ink"])
        self.result_label.grid(row=0, column=0, sticky="w")
        self.report_button = self.button(result, "gui.open_report", self.open_report)
        self.report_button.grid(row=0, column=1, padx=(pad, 0), sticky="e")
        self.folder_button = self.button(result, "gui.open_folder", self.open_report_folder)
        self.folder_button.grid(row=0, column=2, padx=(pad, 0), sticky="e")
        ttk.Label(result, textvariable=self.saved_var, wraplength=wrap, justify="left", style="Soft.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(self.px(2), 0))

        # ---- The findings (GUI-009)
        found = self.card(outer, row=2, column=0, sticky="nsew", pady=(pad * 1.5, 0))
        found.master.configure(background=self.colours["line"])
        found.configure(padding=0)
        found.columnconfigure(0, weight=1)
        found.rowconfigure(0, weight=1)
        self.findings = ttk.Treeview(found, columns=("kind", "where", "what"), show="tree headings", height=4)
        self.findings.column("#0", width=self.px(22), minwidth=self.px(22), stretch=False)
        self.findings.column("kind", width=self.px(120), stretch=False)
        self.findings.column("where", width=self.px(250), stretch=False)
        self.findings.column("what", width=self.px(380))
        for column in ("kind", "where", "what"):
            self.findings.heading(column, anchor="w")
        self.findings.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(found, orient="vertical", command=self.findings.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.findings.configure(yscrollcommand=scroll.set)
        self.markers = {kind: self.marker(self.colours[kind]) for kind in (ERROR, WARNING, INFO, POSSIBLE)}
        outer.rowconfigure(2, weight=1)

        # ---- The window's own language, and about (I18N-002, GUI-014)
        bottom = ttk.Frame(outer, style="Page.TFrame")
        bottom.grid(row=3, column=0, sticky="ew", pady=(pad * 1.5, 0))
        bottom.columnconfigure(2, weight=1)
        self.label(bottom, "gui.language", style="Page.TLabel").grid(row=0, column=0)
        # The languages are listed by name, in the order of i18n.LANGUAGES (GUI-012).
        self.lang_box = ttk.Combobox(bottom, textvariable=self.lang_var, state="readonly", width=24)
        self.lang_box.grid(row=0, column=1, padx=pad)
        self.lang_box.bind("<<ComboboxSelected>>", lambda _event: self.language_chosen())
        self.button(bottom, "gui.about", self.show_about, style="Page.TButton").grid(row=0, column=3)

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
        self.detected_label.configure(style="Problem.TLabel" if self.problems else "TLabel")

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
                    self.saved_var.set(t("gui.reports_in", path=options.output))
                    # The box shows where reports will really go, also when that was not chosen here.
                    if not session.output and not self.typing_in(self.output_entry):
                        self.output_var.set(options.output)
                    self.planned_output = options.output
                    ready = True
                except ToolError as error:
                    reason = t(error.message_id, **error.params)
        self.command_var.set(command)
        if not busy and self.status_key is None:
            self.status_var.set(reason)

        for widget in self.sdk_widgets:
            if self.needs_sdk:
                widget.grid()
            else:
                widget.grid_remove()
        if session.advanced:
            self.advanced_frame.grid()
        else:
            self.advanced_frame.grid_remove()
        self.advanced_button.configure(text=t("gui.advanced.hide" if session.advanced else "gui.advanced.show"))
        self.fit()
        self.run_button.configure(
            text=t("gui.cancel") if busy else t("gui.run"),
            state="normal" if (busy and not session.stop.is_set()) or (ready and not busy) else "disabled")
        state = "disabled" if busy else "normal"
        for widget in (
                self.game_entry, self.game_browse, self.sdk_entry, self.sdk_browse, self.sandbox_check,
                self.output_entry, self.output_browse, self.cache_button, *self.stage_checks,
                *self.languages_frame.winfo_children()):
            widget.configure(state=state)
        self.lang_box.configure(state="disabled" if busy else "readonly")
        for widget in (self.report_button, self.folder_button):
            widget.configure(state="normal" if self.paths and not busy else "disabled")

    def typing_in(self, widget):
        """True while the keyboard is in `widget`: what is being typed there must not be replaced."""
        try:
            return self.root.focus_get() is widget
        except KeyError:
            return False  # The keyboard is in a list Tk made by itself, such as a drop-down.

    def fit(self):
        """Makes the window tall enough for what it now shows. It is never made smaller: how much
        room the list of findings gets beyond that is the user's to decide."""
        root = self.root
        root.update_idletasks()
        # As tall as its contents ask for, but never taller than the screen has room for.
        needed = min(root.winfo_reqheight(), root.winfo_screenheight() - self.px(90))
        root.minsize(self.px(840), max(self.px(560), needed))
        if root.winfo_viewable() and root.winfo_height() < needed:
            root.geometry("%dx%d" % (root.winfo_width(), needed))

    def toggle_advanced(self):
        self.session.advanced = not self.session.advanced
        self.refresh()

    def browse_output(self):
        from tkinter import filedialog

        chosen = filedialog.askdirectory(title=t("gui.choose_output"), mustexist=False)
        if chosen:
            self.output_var.set(str(Path(chosen)))
            self.output_chosen()

    def output_chosen(self):
        """Takes the report folder typed or browsed for. An empty box, or the folder that would be
        used anyway, means no choice was made: the game's config file, or the usual place, decides."""
        chosen = self.output_var.get().strip().strip('"')
        usual = self.planned_output if not self.session.output else None
        self.session.output = "" if not chosen or chosen == usual else chosen
        self.refresh()

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
        self.counts = dict.fromkeys(COUNTED, 0)
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
        for kind, variable in self.count_vars.items():
            variable.set(str(self.counts[kind]))

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
            self.counts[POSSIBLE if finding.possible else finding.severity] += 1
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
            colour = self.colours["ok" if outcome == "passed" else "error"]
            self.counts = {kind: report.count(kind) for kind in (ERROR, WARNING, INFO)}
            self.counts[POSSIBLE] = report.count_possible()
            self.show_counts()
        elif self.result[0] == "stopped":
            text = t("cli.interrupted")
        else:
            text, colour = self.result[1], self.colours["error"]
        self.result_var.set(text)
        self.result_label.configure(foreground=colour or self.colours["ink"])
        if self.result and self.result[0] == "finished":
            self.list_findings(self.result[1])

    def list_findings(self, report):
        self.findings.delete(*self.findings.get_children())
        for finding in report.to_dict()["findings"]:
            kind = t("gui.possible") if finding["possible"] else t("html.severity." + finding["severity"])
            marker = self.markers[POSSIBLE if finding["possible"] else finding["severity"]]
            self.findings.insert(
                "", "end", image=marker, values=(kind, reports.where(finding), reports.message(finding)))

    def open_report(self):
        if self.paths:
            webbrowser.open(Path(self.paths["html"]).resolve().as_uri())

    def open_report_folder(self):
        if self.paths:
            open_folder(Path(self.paths["html"]).parent)

    # ------------------------------------------------------- the sandbox's copies (GUI-010)

    def dialog(self, title):
        """A second window in the same dress as the first. Returns (the window, the card to fill).

        It is made out of sight, and stays so until `present` is called for it. A window shown
        before it has its contents appears for a moment as a small empty frame in a corner of the
        screen, then jumps to its place (GUI-017).
        """
        window = self.tk.Toplevel(self.root, background=self.colours["page"])
        window.withdraw()
        window.title(title)
        set_icon(window, self.icons)
        page = self.ttk.Frame(window, padding=self.px(self.PAD) * 2, style="Page.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        return window, self.card(page, row=0, column=0, sticky="nsew")

    def present(self, window):
        """Shows a dialog that is ready, over the middle of the main window (GUI-017)."""
        root = self.root
        window.update_idletasks()
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        # Both windows wear the same frame, so lining up their outer corners lines up their middles.
        x = root.winfo_x() + (root.winfo_width() - width) // 2
        y = root.winfo_y() + (root.winfo_height() - height) // 2
        # Never off the screen, whatever the main window is doing.
        x = max(0, min(x, root.winfo_screenwidth() - width))
        y = max(0, min(y, root.winfo_screenheight() - height))
        window.geometry("+%d+%d" % (x, y))
        window.transient(root)
        if self.dark:
            dark_title_bar(window)  # The frame is only drawn dark if told to be before it is shown.
        if root.winfo_viewable():
            window.deiconify()
            window.focus_set()
        return window

    def show_cache(self):
        ttk, pad = self.ttk, self.px(self.PAD)
        dialog, frame = self.dialog(t("gui.cache.title"))
        ttk.Label(
            frame, text=t("cache.where", path=str(sandbox.cache_dir())), wraplength=self.px(640),
            style="Soft.TLabel").pack(anchor="w")
        tree = ttk.Treeview(frame, columns=("game", "size", "used"), show="headings", height=8)
        for column, key, width in (("game", "gui.cache.game", 380), ("size", "gui.cache.size", 100),
                                   ("used", "gui.cache.used", 170)):
            tree.heading(column, text=t(key))
            tree.column(column, width=self.px(width))
        tree.pack(fill="both", expand=True, pady=pad)
        total = ttk.Label(frame, style="Soft.TLabel")
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
        return self.present(dialog)

    # ---------------------------------------------------------------- about (GUI-014)

    def show_about(self):
        tk, ttk, pad = self.tk, self.ttk, self.px(self.PAD)
        dialog, frame = self.dialog(t("gui.about.title"))
        dialog.resizable(False, False)
        wrap = self.px(380)

        if len(self.icons) > 2:
            ttk.Label(frame, image=self.icons[2]).grid(row=0, column=0, rowspan=2, padx=(0, pad * 2), sticky="n")
        ttk.Label(frame, text="RenPyTester", style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(frame, text=t("gui.about.version", version=__version__), style="Soft.TLabel").grid(
            row=1, column=1, sticky="w")
        ttk.Label(frame, text=t("cli.description"), wraplength=wrap, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(pad * 2, 0))
        ttk.Label(frame, text=t("gui.about.credit", author=__author__)).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        ttk.Label(frame, text=t("gui.about.licence"), wraplength=wrap, justify="left", style="Soft.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w")
        # The one thing in the program that leads to the network, and only when it is clicked (SAFE-008).
        # A button made to look like a link, so that it can be reached and pressed from the keyboard too.
        colours = self.colours
        link = tk.Button(
            frame, text=__url__, fg=colours["info"], activeforeground=colours["info"], bg=colours["card"],
            activebackground=colours["card"], cursor="hand2", relief="flat", borderwidth=0, padx=0, pady=0,
            font=("TkDefaultFont", 10, "underline"), command=lambda: self.open_link(__url__))
        link.grid(row=5, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        ttk.Button(frame, text=t("gui.close"), command=dialog.destroy).grid(
            row=6, column=0, columnspan=2, sticky="e", pady=(pad * 2, 0))
        return self.present(dialog)

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
    make_sharp()
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
