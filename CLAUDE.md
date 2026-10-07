# RenPyTester

A tool that automatically plays through any Ren'Py game and reports broken scenes, missing assets and broken translations.
Runnable from source with plain Python or as a single-file executable, from a terminal or a simple window.

## Current state

**Milestones M0 (spikes), M1 (walking skeleton), M2 (lint stage), M3a (exploration), M3b (checks that need no rendering), M3c (getting past minigames), M3d (label runs), M3e (parallel processes) and M4 (translations) are done.**
**M5 (reports and config), M6 (sandbox) and M7 (graphical interface) are done too. M8 (packaging) is next.**
[docs/SPEC.md](docs/SPEC.md) version 0.16 is approved; the 0.17 amendments that came out of building M7 are waiting for the owner's approval (decision D21 in spec section 9.2).
What works today: `python -m renpytester GAME` finds the game and its engine and explores every choice of every menu with no window, using in-memory snapshots, and carries on after a crash or a hang.
While playing it checks for undefined images, missing image, audio and movie files, broken text tags and menus with nothing to choose.
It also runs the engine's lint and turns its report into findings, merged with what playing found.
It reports on the console and in a JSON file named after the game and the time of the run, in English or Brazilian Portuguese.
It leaves the game folder byte-for-byte unchanged.
A minigame or other interaction it cannot play is skipped, and the story is continued once for each result the script checks for; what is found after that is reported as a possible issue.
After exploring the story it plays each label by itself, to reach what the story never reaches; what only those label runs find is a possible issue too, and is dropped if the story played the same statement without trouble.
With `--jobs` above 1 (the default on most computers) the label runs are shared out between extra game processes and lint runs at the same time; the story itself is always explored by one process.
For each language the game has, it reports lines and texts with no translation, broken text tags in translations, translations whose `[variables]` differ from the original's, and a language that cannot be switched to.
These are checked by a game process of its own that plays nothing.
While the story is played, every translation of each line is also tried out in the state the game is in, for all languages at once, so no route is played again for a language.
Every run writes three reports under the same name: JSON, JUnit XML and a self-contained HTML page.
Settings can be kept in a `renpytester.toml` in the game folder: any option, ignore rules, severities, answers for particular prompts, starting values for game variables, and labels not to play.
`--baseline` leaves out what an earlier report already had, Ctrl+C still writes a report of what was found, and `renpytester info GAME` says what a game is without playing it.
With `--sandbox` a copy of the game is tested and the game itself is only read; the copy is kept in a per-user cache and brought up to date on later runs, and `renpytester cache list` and `cache clear` manage it.
A game whose own script writes into its folder is told so in the report.
`python -m renpytester` with nothing after it, or `renpytester gui [GAME]`, opens a window that makes the same runs: choose the game, tick what to check, run or cancel, and read the result and the findings there.
The window has the program's own icon, lists its languages by name, and has an *About* dialog with the version, the author and the repository.
Not built yet: packaging (M8).
Engine facts and hooks are recorded in [docs/SPIKES.md](docs/SPIKES.md): read it before touching the harness.
`spikes/` holds the throwaway M0 experiments; never import from it.

Ren'Py SDKs for local testing are unpacked under `.cache/sdk/` (git-ignored): the newest and the oldest supported 8.x.

## Spec-driven workflow

[docs/SPEC.md](docs/SPEC.md) is the source of truth.
The rules:

1. **Spec first.** Any change in behaviour starts as a change to the spec, in the same commit or an earlier one.
   If code and spec disagree, the code is wrong, or the spec needs an explicit amendment.
   Never leave them disagreeing.
2. **Every requirement has an ID** (`RUN-003`, `TL-005`, ...).
   IDs are permanent: never renumber or reuse.
   A dropped requirement is marked *Withdrawn* and stays in the table.
3. **Every test names the requirement IDs it verifies.** A requirement is done when a passing test names it.
   No test, not done.
4. **No unspecified features.** If something useful is not in the spec, propose a requirement for it; do not just build it.
5. **Commits reference IDs** for the requirements they implement or change.
6. **Spec edits bump the version and add a change-log row** (section 10 of the spec).
7. **Unverified engine behaviour is an assumption, not a fact.** Beliefs about how Ren'Py behaves go in spec section 9.1 until a spike or test proves them, on the oldest and newest supported Ren'Py 8.x.

## Architecture rules that are easy to break

Full detail in spec section 3.
The ones that cause real damage if forgotten:

- **Two runtimes.** The *orchestrator* (`renpytester/`) runs on Python 3.11+.
  The *harness* (`renpytester/harness/`) is injected into the game and runs on the game's embedded Python, which we do not choose: it is whatever Python 3 that Ren'Py 8 release ships, as old as 3.9.
  Harness code must run on 3.9: no `match`, no `X | Y` type unions, no `tomllib`, no third-party imports.
  Ren'Py 7 and older (Python 2) are out of scope and are refused, not half-supported.
- **Orchestrator is stdlib-only at runtime**, including the GUI (`tkinter`).
  Dev tools are fine as dev dependencies.
- **The game is never visible.** No game window, no audio, no focus stealing during a run.
  The game runs at high speed, so a visible window flashes: treat any change that could show one as a safety bug, not a cosmetic one.
- **Nothing else may appear on screen either.**
  A failing game makes the engine open `traceback.txt` or `errors.txt` in the system text editor (Notepad).
  Every engine launch, including spikes and tests, must set `RENPY_EDIT_PY` to `renpytester/harness/silent_editor.py`; launch the engine only through `renpytester.launcher` or `spikes/run.py`, which do.
- **Every user-facing string goes through the message catalogue** in English and Brazilian Portuguese.
  No hard-coded text in console, GUI or HTML output.
  Machine-readable output (JSON keys, finding classes, exit codes) stays language-neutral.
- **The GUI is a front end to the same run as the CLI**, never a second implementation.
  Both get their settings from `runner.prepare` and run with `runner.run`; the window adds no setting the command line lacks, and shows the command that makes the same run.
- **In the window, only the main thread touches Tk.**
  `gui.Session` does the work in threads and has no widgets; it talks to `gui.Window` through a queue that the window empties on a timer.
  Never call a widget, or a Tk variable, from a session thread.
  Tk objects must also not be freed by another thread: Python frees things in whichever thread is running, and a Tk interpreter freed by the wrong one stops the process.
  That is why the window keeps replaced variables, and why the window tests let go of each window in the main thread.
- **A run is stopped from outside by setting the `stop` event given to `runner.run`**, which does exactly what Ctrl+C does.
  Everything that waits on a game process must look at that event; a new wait that does not would make *Cancel* hang.
- **The icon is drawn by `tools/make_icon.py`**, which needs Pillow, a development tool only; the files it writes under `renpytester/assets/` are committed.
  To change the icon, change the drawing in that tool and run it; never edit the image files or bring in artwork from elsewhere.
  On Windows each window is given the icon by itself with `iconbitmap`, because Tk's ways of setting one icon for all windows set none there.
- **Colours live in `renpytester/palette.py` and nowhere else.**
  The HTML report and the window both take them from there, so that they look like one program; a colour written into `gui.py` or the report's style is a mistake, and a test looks for them in the report.
  The window's look is made with Tk's own `clam` theme restyled in `gui.apply_theme`, plus small pictures the program draws itself (tick boxes, the markers beside findings); nothing is added to what the program needs.
  Sizes in pixels go through `Window.px`, so that the window is right on a screen set to show things larger.
- **The window is never shown in tests** (`root.withdraw()`), and tests must replace `gui.default_output`: the real one is in the user's home folder.
- **Never re-implement the engine.** Parsing, lint, translation lookup and text substitution are done by the game's own Ren'Py, never by our code.
- **A translation is not at fault for what its original does too.**
  Text such as `"Page {}"` is filled in by Python and reads as a broken tag in every language; a translated line is reported only when the original passes the same check.
- **Switching language is done only in the translations process, never in one that plays.**
  A language's `translate python` code changes the game's state, which would change what exploring the story finds.
- **Harness talks to the orchestrator through a JSON-lines file**, never stdout.
- **Hook only what every supported engine version has.** Ren'Py 8.0 and 8.6 differ internally (8.0 has no `Context.handle_exception`, and `renpy.error` seen from a game script is a function, not the module).
  Any harness change must pass the test suite on both the oldest and the newest SDK.
- **A failed end-to-end test keeps its logs** under `.cache/failures/<test name>/`, because some failures depend on timing inside the engine and do not come back on the next run.
  Owner's instruction (2026-10-06): do not re-run the suite in a loop to chase a failure that does not reproduce; check `.cache/failures/` after each run and move on.
  The exception is an intermittent failure or edge case that makes the program itself malfunction: that must be hunted down and fixed.
- **When a result looks wrong, read the event log first.**
  Every run keeps what the harness reported in `<report name>-logs/events-run.jsonl`, beside the engine's own logs.
- **The harness must never act on the game's main menu or other out-of-story screens.**
  It once explored the main menu's buttons after an automatic script reload, which showed up as a run that intermittently found nothing.
  The same symptom (15 paths that all end in `quit`) had a second cause: on Windows the engine enters safe mode when Shift is down as it starts, and shows its renderer screen.
  The harness switches safe mode off; the `safe_mode` fixture reproduces it without touching the keyboard.
- **Results must not depend on `--jobs` or on timing.**
  Only work whose result does not depend on order may be given to another process: label runs and lint, never part of the story's exploration.
  Findings are collected and put into the report in a fixed order when everything has finished, and everything a label run keeps in memory is reset when it starts.
- **Game processes run at the same time, in the same game folder.**
  Each gets its own work folder (events, saves) and log folder; nothing in the game folder may be written by more than one.
  The engine's own second save location, `game/saves`, is switched off by the harness for that reason.
- **A failure in our own code is never reported as a problem in the game.**
  Harness and orchestrator bugs exit with code 3 and say they are RenPyTester bugs.
- **Nothing is rendered.** The harness replaces the engine's interaction layer, so render-time failures (missing image files, bad text tags, screen errors) never show up by themselves.
  Each must be checked explicitly when the statement runs.
- **A snapshot goes back to the engine's last hard checkpoint, not to where it was taken.**
  The engine then replays forward from there, which only works if everything since is part of the game's own state.
  Anything the harness does to the flow, such as the jump that starts a label run, must be followed by `renpy.game.log.checkpoint(hard=True)`.
- **The engine writes into the game folder by itself** (`game/cache/`, `game/saves/`, logs).
  Back up and restore, or remove, everything it touches; redirect logs with `RENPY_LOG_BASE`.
- **Never modify the game.** Only add files prefixed `zzz_renpytester_`, and always remove them, including after a crash or Ctrl+C.
  Saves and persistent data go to a temp directory.
  In sandbox mode, write nothing at all to the original: not a lock, not a record, not a leftover.
  Everything the sandbox needs to remember lives beside the copy, in the cache.
- **The sandbox copy is the game, and is tested by the same code.**
  `runner.run` only swaps the folder; `runner.run_in` does not know the difference except for the name it puts in the report.
  Do not add a second path through the run for sandbox mode.
- **Tests never touch the real cache.**
  `tests/conftest.py` points `RENPYTESTER_CACHE` at a temporary folder for every test; anything new that uses the cache must go through `sandbox.cache_dir()`.
- **Never report "passed" for something that was not checked.** Skipped is skipped.
- **Options have no defaults in the command-line parser.**
  An option that was not given must stay `None`, so that the config file can supply it; the defaults live in `runner.Options` only, and `runner.build_options` puts the three together.
  Give a new option a default in `argparse` and the config file silently stops working for it.
- **Everything from the game is escaped in the HTML report**, and stripped of characters XML cannot hold in the JUnit report.
  Dialogue, tracebacks and choices are text the game wrote; the report shows them, never runs them.
- **State the harness sets at the story's first statement is set again after every return to it.**
  Putting the game back to a snapshot can roll back to before that statement and undo it, which is why the config file's variables are applied whenever the first statement played after a start or a restore is the story's first.

## Test games

- **The Question** and **Tutorial** ship inside the Ren'Py SDK and are the known-good baselines.
- Fixture games under `tests/fixtures/games/` are original content, one seeded bug each.
  Those whose name starts with `tl_` have a translation under `game/tl/`.
  The identifier of a translated line (`start_76f3b19b`) is worked out by the engine from the line's text.
  After changing a line in such a fixture, run the SDK's `translate` command on a copy to get the new identifier, and never commit the `common.rpy` that command also writes.

**Never commit game content or engine code**: no SDK, no assets or scripts copied from any game.
Paths to these come from environment variables.

## Conventions

- Licence: GPL-3.0.
- English for code, the spec and commit messages.
  The tool's interface and reports are in English and Brazilian Portuguese.
- **All linting is required, for every script and document, with zero problems reported** (spec NFR-008, NFR-009).
  This includes spikes, tools and tests, not only product code.
  Run all three before finishing any change, and fix what they report instead of silencing it:
  `python -m flake8 .` for Python (config in `.flake8`, line length 120);
  `python tools/lint_rpy.py` for Ren'Py scripts (spaces only, indentation in multiples of 4, line length 120, plus Flake8 on the Python inside `python:` blocks);
  `npx markdownlint-cli2 "**/*.md"` for Markdown.
- In `.rpy` files, never align continuation lines under an opening bracket: that produces indentation that is not a multiple of 4.
  Break after the bracket and indent the continuation by 4.
- Every Markdown file must pass `markdownlint` with the repository's `.markdownlint.json` (spec NFR-008).
  Run `npx markdownlint-cli2 "**/*.md"` before finishing any change that touches a `.md` file.
  Tables use the spaced form: `| --- | --- |`, never `|---|---|`.
- In Markdown prose, break lines only at the end of a sentence, one sentence per line.
  Never wrap in the middle of a sentence to fit a column width; the limit is 250 characters.
- User-facing messages are written for game developers who may not know Python: say what is wrong and where in their script.

## Commands

- Run it: `python -m renpytester GAME --sdk .cache/sdk/renpy-8.6.0-sdk` (`--sdk` is only needed for a project that has no engine of its own).
- Tests: `python -m pytest` runs everything; `python -m pytest tests/unit` needs no engine.
  End-to-end tests use the SDK in the `RENPY_SDK` environment variable, or the newest one under `.cache/sdk/`, and are skipped if there is none.
  The `run` fixture passes `--jobs 1` unless the test gives its own, so that results do not depend on the machine.
- Tests on the oldest engine: set `RENPY_SDK` to `.cache/sdk/renpy-8.0.3-sdk` and run `python -m pytest` again.
  Do this for every harness change.
- Linters: `python -m flake8 .`, `python tools/lint_rpy.py`, `npx markdownlint-cli2 "**/*.md"`.
- Run a spike: `python spikes/run.py s4_screens.rpy --game tutorial`.

## Layout

- `renpytester/`: the orchestrator.
  `cli` parses options, `discovery` finds the game and engine, `workspace` prepares and restores the game folder, and `launcher` runs the engine invisibly.
  `lint` reads the engine's lint report, `routes` adds up coverage and tracks unexplored branches, `runner` ties a run together, and `model` holds findings and the report.
  `config` reads `renpytester.toml`, `sandbox` keeps the cached copies, `gui` is the window, `i18n` and `locale/` hold every user-facing string, and `report/` writes output.
  The JUnit and HTML writers take the JSON report's data, never the `Report` object: what is not in the JSON cannot be in them.
- `renpytester/harness/zzz_renpytester_harness.rpy`: the script injected into the game.
- `tests/fixtures/games/`: one small game per behaviour under test. A new finding class needs a new fixture.
- `docs/report-schema.md`: the JSON report format. Update it with any change to `model.py`.
