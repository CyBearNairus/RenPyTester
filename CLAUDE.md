# RenPyTester

A tool that automatically plays through any Ren'Py game and reports broken scenes, missing assets and broken translations.
Runnable from source with plain Python or as a single-file executable, from a terminal or a simple window.

## Current state

**Milestones M0 (spikes) and M1 (walking skeleton) are done. Milestone M2 (lint stage) is next.**
[docs/SPEC.md](docs/SPEC.md) version 0.6 is approved; the 0.7 amendments (getting past minigames, built in M3) are waiting for the owner's approval (decision D11 in spec section 9.2).
What works today: `python -m renpytester GAME` finds the game and its engine and plays one path with no window.
It reports crashes and script errors on the console and in `report.json`, in English or Brazilian Portuguese.
It leaves the game folder byte-for-byte unchanged.
Not built yet: branching exploration and snapshots (M3), lint (M2), translations (M4), JUnit/HTML/config (M5), sandbox (M6), GUI (M7), packaging (M8).
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
- **Never re-implement the engine.** Parsing, lint, translation lookup and text substitution are done by the game's own Ren'Py, never by our code.
- **Harness talks to the orchestrator through a JSON-lines file**, never stdout.
- **Hook only what every supported engine version has.** Ren'Py 8.0 and 8.6 differ internally (8.0 has no `Context.handle_exception`, and `renpy.error` seen from a game script is a function, not the module).
  Any harness change must pass the test suite on both the oldest and the newest SDK.
- **A failure in our own code is never reported as a problem in the game.**
  Harness and orchestrator bugs exit with code 3 and say they are RenPyTester bugs.
- **Nothing is rendered.** The harness replaces the engine's interaction layer, so render-time failures (missing image files, bad text tags, screen errors) never show up by themselves.
  Each must be checked explicitly when the statement runs.
- **The engine writes into the game folder by itself** (`game/cache/`, `game/saves/`, logs).
  Back up and restore, or remove, everything it touches; redirect logs with `RENPY_LOG_BASE`.
- **Never modify the game.** Only add files prefixed `zzz_renpytester_`, and always remove them, including after a crash or Ctrl+C.
  Saves and persistent data go to a temp directory.
  In sandbox mode, write nothing at all to the original.
- **Never report "passed" for something that was not checked.** Skipped is skipped.

## Test games

- **The Question** and **Tutorial** ship inside the Ren'Py SDK and are the known-good baselines.
- Fixture games under `tests/fixtures/games/` are original content, one seeded bug each.

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
- Tests on the oldest engine: set `RENPY_SDK` to `.cache/sdk/renpy-8.0.3-sdk` and run `python -m pytest` again.
  Do this for every harness change.
- Linters: `python -m flake8 .`, `python tools/lint_rpy.py`, `npx markdownlint-cli2 "**/*.md"`.
- Run a spike: `python spikes/run.py s4_screens.rpy --game tutorial`.

## Layout

- `renpytester/`: the orchestrator.
  `cli` parses options, `discovery` finds the game and engine, `workspace` prepares and restores the game folder, and `launcher` runs the engine invisibly.
  `runner` ties a run together, `model` holds findings and the report, `i18n` and `locale/` hold every user-facing string, and `report/` writes output.
- `renpytester/harness/zzz_renpytester_harness.rpy`: the script injected into the game.
- `tests/fixtures/games/`: one small game per behaviour under test. A new finding class needs a new fixture.
- `docs/report-schema.md`: the JSON report format. Update it with any change to `model.py`.
