"""Command line (spec 4.10)."""

import argparse
import sys
import traceback
from pathlib import Path

from renpytester import __version__, config, discovery, i18n, report, runner, sandbox
from renpytester.errors import ToolError
from renpytester.i18n import t
from renpytester.model import ERROR, SEVERITIES
from renpytester.report import human_size
from renpytester.report.console import Console

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_TOOL = 3

# The command that only says what the game is (CLI-008).
INFO = "info"
# The command that shows and deletes the cached copies that --sandbox makes (SAFE-012).
CACHE = "cache"
# The command that opens the window (CLI-007).
GUI = "gui"


def language_from(argv):
    """Finds --lang before the real parse, so that the help text itself can be translated."""
    for index, arg in enumerate(argv):
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def build_parser():
    """The options of a run. None of them has a default here: one that was not given is left to the
    config file, and then to the defaults of runner.Options, which the help text quotes (CFG-002)."""
    defaults = runner.Options(game="")
    parser = argparse.ArgumentParser(prog="renpytester", description=t("cli.description"), epilog=t("cli.epilog"))
    parser.add_argument("game", metavar="GAME", help=t("cli.game"))
    parser.add_argument("--sdk", metavar="PATH", help=t("cli.sdk"))
    parser.add_argument("--config", metavar="FILE", help=t("cli.config", name=config.FILE_NAME))
    parser.add_argument("--output", metavar="DIR", help=t("cli.output", default=defaults.output))
    parser.add_argument("--baseline", metavar="REPORT", help=t("cli.baseline"))
    parser.add_argument(
        "--stages", metavar="LIST",
        help=t("cli.stages", default=",".join(defaults.stages), all=", ".join(runner.STAGES)))
    parser.add_argument(
        "--strategy", choices=config.STRATEGIES, help=t("cli.strategy", default=defaults.strategy))
    parser.add_argument("--languages", metavar="LIST", help=t("cli.languages"))
    parser.add_argument("--no-labels", action="store_true", default=None, help=t("cli.no_labels"))
    parser.add_argument("--jobs", type=int, metavar="N", help=t("cli.jobs"))
    parser.add_argument("--max-paths", type=int, metavar="N", help=t("cli.max_paths", default=defaults.max_paths))
    parser.add_argument(
        "--max-time", type=float, metavar="SECONDS", help=t("cli.max_time", default=int(defaults.max_time)))
    parser.add_argument("--max-depth", type=int, metavar="N", help=t("cli.max_depth", default=defaults.max_depth))
    parser.add_argument("--seed", type=int, help=t("cli.seed", default=defaults.seed))
    parser.add_argument(
        "--timeout", type=float, metavar="SECONDS", help=t("cli.timeout", default=int(defaults.timeout)))
    parser.add_argument("--input-value", metavar="TEXT", help=t("cli.input_value", default=defaults.input_value))
    parser.add_argument("--max-steps", type=int, metavar="N", help=t("cli.max_steps", default=defaults.max_steps))
    parser.add_argument("--fail-on", choices=[*SEVERITIES, "never"], help=t("cli.fail_on", default=ERROR))
    parser.add_argument("--fail-on-possible", action="store_true", default=None, help=t("cli.fail_on_possible"))
    parser.add_argument("--show-window", action="store_true", default=None, help=t("cli.show_window"))
    parser.add_argument("--sandbox", action="store_true", default=None, help=t("cli.sandbox"))
    parser.add_argument("--sandbox-verify", action="store_true", default=None, help=t("cli.sandbox_verify"))
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=t("cli.lang"))
    parser.add_argument("--version", action="version", version="renpytester " + __version__)
    return parser


def build_window_parser():
    parser = argparse.ArgumentParser(prog="renpytester " + GUI, description=t("cli.gui.description"))
    parser.add_argument("game", metavar="GAME", nargs="?", help=t("cli.gui.game"))
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=t("cli.lang"))
    return parser


def build_cache_parser():
    parser = argparse.ArgumentParser(prog="renpytester " + CACHE, description=t("cli.cache.description"))
    parser.add_argument("action", choices=("list", "clear"), help=t("cli.cache.action"))
    parser.add_argument("game", metavar="GAME", nargs="?", help=t("cli.cache.game"))
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=t("cli.lang"))
    return parser


def build_info_parser():
    parser = argparse.ArgumentParser(prog="renpytester " + INFO, description=t("cli.info.description"))
    parser.add_argument("game", metavar="GAME", help=t("cli.game"))
    parser.add_argument("--sdk", metavar="PATH", help=t("cli.sdk"))
    parser.add_argument("--config", metavar="FILE", help=t("cli.config", name=config.FILE_NAME))
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=t("cli.lang"))
    return parser


def listed(text):
    """A list given on the command line as words separated by commas, or None when it was not given."""
    return None if text is None else tuple(item.strip() for item in text.split(",") if item.strip())


def given_by(args):
    """The settings the command line asked for, by their names in runner.Options. Others are None."""
    return {
        "sdk": args.sdk, "output": args.output, "baseline": args.baseline, "stages": listed(args.stages),
        "strategy": args.strategy, "languages": listed(args.languages),
        "labels": False if args.no_labels else None, "jobs": args.jobs, "seed": args.seed, "timeout": args.timeout,
        "input_value": args.input_value, "max_steps": args.max_steps, "max_paths": args.max_paths,
        "max_time": args.max_time, "max_depth": args.max_depth, "show_window": args.show_window,
        "sandbox": args.sandbox, "sandbox_verify": args.sandbox_verify,
        "fail_on": args.fail_on, "fail_on_possible": args.fail_on_possible}


def prepare(args, given, language_given):
    """Reads the config file that goes with the game and returns the settings of the run (CFG-002)."""
    options, settings = runner.prepare(args.game, given, args.config)
    if settings.lang and not language_given:
        i18n.set_language(settings.lang)  # I18N-002: the command line, then the config file, then the system.
    return options


def fail(console, error):
    console.write(console.paint(t(error.message_id, **error.params), ERROR))
    return error.exit_code


def internal_error(console):
    # Anything unexpected is our fault, never the game's (NFR-004).
    console.write(console.paint(t("error.internal"), ERROR))
    console.write(traceback.format_exc())
    return EXIT_TOOL


def info(argv, language_given):
    """Says what the game is, without playing it (CLI-008)."""
    args = build_info_parser().parse_args(argv)
    console = Console()
    try:
        result = runner.describe(prepare(args, {"sdk": args.sdk}, language_given), console.progress)
    except ToolError as error:
        return fail(console, error)
    except KeyboardInterrupt:
        console.write(t("cli.interrupted"))
        return EXIT_TOOL
    except Exception:
        return internal_error(console)

    if result.game.get("python"):
        console.write(t("console.python", version=result.game["python"]))
    if result.findings:
        # The game cannot start: say why, since that is all there is to know about it.
        console.write()
        console.listing(result.findings)
        return EXIT_FINDINGS
    return EXIT_OK


def own_console():
    """True when this process has a console window all to itself. On Windows that is what a program
    gets when it is started by a double click, or by dropping something on it, and not from a terminal."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        processes = (ctypes.c_uint * 4)()
        return ctypes.windll.kernel32.GetConsoleProcessList(processes, 4) == 1
    except Exception:
        return False


def window_wanted(argv, alone=None):
    """Decides whether to open the window instead of running in the terminal (CLI-007).

    Returns (whether it is wanted, the game to open it with or None). It is wanted when nothing
    was asked for, when `gui` was, and when a folder was dropped on the program: the folder then
    arrives as the only argument, to a process that no terminal started.
    """
    if not argv:
        return True, None
    if argv[0] == GUI:
        args = build_window_parser().parse_args(argv[1:])
        return True, args.game
    dropped = len(argv) == 1 and not argv[0].startswith("-") and Path(argv[0]).exists()
    if dropped and (own_console() if alone is None else alone):
        return True, argv[0]
    return False, None


def window(game, lang):
    """Opens the window (4.14). Without Tk, says what to install; the command line still works (COMPAT-007)."""
    from renpytester import gui

    try:
        return gui.main(game, lang)
    except ToolError as error:
        return fail(Console(), error)


def cache(argv):
    """Shows the sandbox copies kept in the cache, or deletes them (SAFE-012)."""
    args = build_cache_parser().parse_args(argv)
    console = Console()
    try:
        if args.action == "list":
            copies = sandbox.listing()
            console.write(t("cache.where", path=str(sandbox.cache_dir())))
            if not copies:
                console.write(t("cache.empty"))
            for entry in copies:
                console.write(t(
                    "cache.entry.in_use" if entry["in_use"] else "cache.entry", game=entry["original"],
                    size=human_size(entry["bytes"]), files=entry["files"],
                    when=(entry["last_used"] or "?")[:19].replace("T", " ")))
            if copies:
                console.write(t("cache.total", count=len(copies), size=human_size(sum(e["bytes"] for e in copies))))
        else:
            original = discovery.resolve_basedir(args.game) if args.game else None
            deleted, freed, kept = sandbox.clear(original)
            console.write(t("cache.cleared", count=deleted, size=human_size(freed)))
            if kept:
                console.write(t("cache.kept", count=kept))
    except ToolError as error:
        return fail(console, error)
    except Exception:
        return internal_error(console)
    return EXIT_OK


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # Piped output (CI logs, other programs) is UTF-8; a real console keeps its own encoding.
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")

    wanted = language_from(argv)
    if wanted is not None and i18n.normalise(wanted) is None:
        wanted = None  # argparse reports the bad value below.
    i18n.set_language(wanted)

    wanted_window, game = window_wanted(argv)
    if wanted_window:
        return window(game, wanted)
    if argv and argv[0] == INFO:
        return info(argv[1:], wanted is not None)
    if argv and argv[0] == CACHE:
        return cache(argv[1:])

    args = build_parser().parse_args(argv)
    console = Console()

    try:
        options = prepare(args, given_by(args), wanted is not None)
    except ToolError as error:
        return fail(console, error)

    if options.show_window:
        console.write(console.paint(t("cli.show_window_warning"), "warning"))

    try:
        result = runner.run(options, console.progress)
    except ToolError as error:
        return fail(console, error)
    except KeyboardInterrupt:
        console.write(t("cli.interrupted"))
        return EXIT_TOOL
    except Exception:
        return internal_error(console)

    if result.interrupted:
        console.write(t("cli.interrupted"))
    failed = result.failed(options.fail_on, options.fail_on_possible)
    paths = report.write_all(result, options.output)
    console.summary(result, paths, failed)

    if not result.complete:
        return EXIT_TOOL
    return EXIT_FINDINGS if failed else EXIT_OK
