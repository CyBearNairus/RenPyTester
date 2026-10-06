# RenPyTester

A tool that automatically plays through any Ren'Py game and reports broken scenes, missing assets and broken translations.
Runnable from source with plain Python or as a single-file executable, from a terminal or a simple window.

## Current state

**Specification phase. There is no code yet.**
[docs/SPEC.md](docs/SPEC.md) is Draft 0.3 and has not been approved.
Do not start implementation until the spec's status line says *Approved*.
The first implementation work is milestone M0 (feasibility spikes), not product code.

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

- **Two runtimes.** The *orchestrator* (`src/renpytester/`) runs on Python 3.11+.
  The *harness* (`src/renpytester/harness/`) is injected into the game and runs on the game's embedded Python, which we do not choose: it is whatever Python 3 that Ren'Py 8 release ships, as old as 3.9.
  Harness code must run on 3.9: no `match`, no `X | Y` type unions, no `tomllib`, no third-party imports.
  Ren'Py 7 and older (Python 2) are out of scope and are refused, not half-supported.
- **Orchestrator is stdlib-only at runtime**, including the GUI (`tkinter`).
  Dev tools are fine as dev dependencies.
- **The game is never visible.** No game window, no audio, no focus stealing during a run.
  The game runs at high speed, so a visible window flashes: treat any change that could show one as a safety bug, not a cosmetic one.
- **Every user-facing string goes through the message catalogue** in English and Brazilian Portuguese.
  No hard-coded text in console, GUI or HTML output.
  Machine-readable output (JSON keys, finding classes, exit codes) stays language-neutral.
- **The GUI is a front end to the same run as the CLI**, never a second implementation.
- **Never re-implement the engine.** Parsing, lint, translation lookup and text substitution are done by the game's own Ren'Py, never by our code.
- **Harness talks to the orchestrator through a JSON-lines file**, never stdout.
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
- Every Markdown file must pass `markdownlint` with the repository's `.markdownlint.json` (spec NFR-008).
  Run `npx markdownlint-cli2 "**/*.md"` before finishing any change that touches a `.md` file.
  Tables use the spaced form: `| --- | --- |`, never `|---|---|`.
- In Markdown prose, break lines only at the end of a sentence, one sentence per line.
  Never wrap in the middle of a sentence to fit a column width; the limit is 250 characters.
- User-facing messages are written for game developers who may not know Python: say what is wrong and where in their script.

Build, test and run commands will be added here when milestone M1 creates them.
