"""Command line (spec 4.10)."""

import argparse
import sys
import traceback

from renpytester import __version__, i18n, runner
from renpytester.errors import ToolError, UsageError
from renpytester.i18n import t
from renpytester.model import ERROR, SEVERITIES
from renpytester.report import json_report
from renpytester.report.console import Console

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_TOOL = 3


def language_from(argv):
    """Finds --lang before the real parse, so that the help text itself can be translated."""
    for index, arg in enumerate(argv):
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def build_parser():
    defaults = runner.Options(game="")
    parser = argparse.ArgumentParser(prog="renpytester", description=t("cli.description"))
    parser.add_argument("game", metavar="GAME", help=t("cli.game"))
    parser.add_argument("--sdk", metavar="PATH", help=t("cli.sdk"))
    parser.add_argument(
        "--output", metavar="DIR", default=defaults.output, help=t("cli.output", default=defaults.output))
    parser.add_argument(
        "--stages", metavar="LIST", default=",".join(defaults.stages),
        help=t("cli.stages", default=",".join(defaults.stages), all=", ".join(runner.STAGES)))
    parser.add_argument(
        "--strategy", choices=["explore", "first"], default=defaults.strategy,
        help=t("cli.strategy", default=defaults.strategy))
    parser.add_argument("--no-labels", action="store_true", help=t("cli.no_labels"))
    parser.add_argument(
        "--max-paths", type=int, default=defaults.max_paths, metavar="N",
        help=t("cli.max_paths", default=defaults.max_paths))
    parser.add_argument(
        "--max-time", type=float, default=defaults.max_time, metavar="SECONDS",
        help=t("cli.max_time", default=int(defaults.max_time)))
    parser.add_argument(
        "--max-depth", type=int, default=defaults.max_depth, metavar="N",
        help=t("cli.max_depth", default=defaults.max_depth))
    parser.add_argument("--seed", type=int, default=defaults.seed, help=t("cli.seed", default=defaults.seed))
    parser.add_argument(
        "--timeout", type=float, default=defaults.timeout, metavar="SECONDS",
        help=t("cli.timeout", default=int(defaults.timeout)))
    parser.add_argument(
        "--input-value", default=defaults.input_value, metavar="TEXT",
        help=t("cli.input_value", default=defaults.input_value))
    parser.add_argument(
        "--max-steps", type=int, default=defaults.max_steps, metavar="N",
        help=t("cli.max_steps", default=defaults.max_steps))
    parser.add_argument(
        "--fail-on", choices=[*SEVERITIES, "never"], default=ERROR, help=t("cli.fail_on", default=ERROR))
    parser.add_argument("--fail-on-possible", action="store_true", help=t("cli.fail_on_possible"))
    parser.add_argument("--show-window", action="store_true", help=t("cli.show_window"))
    parser.add_argument("--lang", choices=i18n.LANGUAGES, help=t("cli.lang"))
    parser.add_argument("--version", action="version", version="renpytester " + __version__)
    return parser


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

    args = build_parser().parse_args(argv)
    console = Console()

    stages = tuple(i.strip() for i in args.stages.split(",") if i.strip())
    unknown = [i for i in stages if i not in runner.STAGES]
    if unknown or not stages:
        error = UsageError("error.unknown_stage", stages=", ".join(unknown) or "-", all=", ".join(runner.STAGES))
        console.write(console.paint(t(error.message_id, **error.params), ERROR))
        return error.exit_code

    options = runner.Options(
        game=args.game, sdk=args.sdk, output=args.output, strategy=args.strategy, labels=not args.no_labels,
        seed=args.seed,
        timeout=args.timeout, input_value=args.input_value, max_steps=args.max_steps, max_paths=args.max_paths,
        max_time=args.max_time, max_depth=args.max_depth, show_window=args.show_window,
        fail_on=args.fail_on, fail_on_possible=args.fail_on_possible,
        stages=tuple(i for i in runner.STAGES if i in stages))

    if options.show_window:
        console.write(console.paint(t("cli.show_window_warning"), "warning"))

    try:
        report = runner.run(options, console.progress)
    except ToolError as error:
        console.write(console.paint(t(error.message_id, **error.params), ERROR))
        return error.exit_code
    except KeyboardInterrupt:
        console.write(t("cli.interrupted"))
        return EXIT_TOOL
    except Exception:
        # Anything unexpected is our fault, never the game's (NFR-004).
        console.write(console.paint(t("error.internal"), ERROR))
        console.write(traceback.format_exc())
        return EXIT_TOOL

    failed = report.failed(options.fail_on, options.fail_on_possible)
    json_path = json_report.write(report, options.output)
    console.summary(report, json_path, failed)

    if not report.complete:
        return EXIT_TOOL
    return EXIT_FINDINGS if failed else EXIT_OK
