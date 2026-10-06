# RenPyTester Specification

| Field | Value |
| --- | --- |
| Status | **Draft 0.3**, under review, not yet approved for implementation |
| Last updated | 2026-10-06 |

This document is the source of truth for what RenPyTester does.
Code is written to satisfy requirements listed here; behaviour that is not listed here is not part of the product.
See [CLAUDE.md](../CLAUDE.md) for the workflow that keeps spec and code in sync.

Priority keywords: **MUST** (required for 1.0), **SHOULD** (planned for 1.0, may slip), **COULD** (wanted, not scheduled).
Each requirement has a stable ID (`AREA-NNN`).
IDs are never reused or renumbered; a dropped requirement is marked *Withdrawn* and kept.

---

## 1. Purpose

Ren'Py developers currently find broken scenes and broken translations by playing the game by hand, route by route, language by language.
RenPyTester automates that: point it at any Ren'Py game, and it plays through the game on its own, then reports every error it hit, where it happened, and how to reproduce it.

### 1.1 Goals

1. **Find real breakage**: crashes, missing assets, bad jumps, broken translations, in any route.
2. **Universal**: works on any Ren'Py game without the game being modified or prepared for it.
3. **Zero-config first run**: `renpytester <game folder>` gives a useful result.
4. **Two ways to run**: from source with plain Python, or as a single downloadable executable.
5. **CI-friendly**: deterministic, scriptable, machine-readable output, meaningful exit codes.
6. **Fast and unobtrusive**: routes are tested in parallel with no real-time waiting, and the user sees a progress bar, never the game's window.
7. **Graphical or command line**: the same run can be started from a simple window or a terminal.

### 1.2 Non-goals

- Judging writing, art, pacing or game balance.
- Visual regression testing (screenshot comparison).
  *COULD be revisited after 1.0.*
- Testing Android, iOS or web builds.
  Desktop builds only.
- Fixing the problems it finds, or editing game scripts in any way.
- Decompiling, unpacking or redistributing game content.
- Defeating anti-tamper or DRM.
- Games on Ren'Py 7 or older (Python 2 engines).
  *May be revisited after 1.0.*

### 1.3 Users

| User | Needs |
| --- | --- |
| Solo/indie developer | Download one file, drop the game folder on it, read a plain-language report. |
| Translator / localisation lead | Know which lines in *their* language are missing or broken, with file and line. |
| Team with CI | Run unattended on every commit, fail the build on new errors, keep a JUnit/JSON artefact. |
| Modder | Test a built game they do not have the project source for. |

The tool's own interface is available in English and Brazilian Portuguese (4.15).

---

## 2. Concepts

- **Game**: a directory containing a Ren'Py `game/` folder.
  Either a *built distribution* (ships its own engine in `renpy/` and `lib/`) or a *project* (needs a separate Ren'Py SDK to run).
- **Orchestrator**: the RenPyTester program the user runs.
  It lives outside the game.
- **Harness**: a small script the orchestrator places inside the game for the duration of a run.
  It executes inside the game's own engine, drives the game, and reports back.
- **Stage**: one kind of check (`lint`, `routes`, `translations`, `screens`).
  A run executes one or more stages.
- **Path**: the ordered list of decisions (menu choices, inputs, screen actions) taken from the start of the game to some point.
  A path is sufficient to reproduce a finding.
- **Finding**: one reported problem, with severity, location, and reproduction path.
- **Coverage**: the fraction of the game's script statements that were executed in a run.

---

## 3. Architecture constraints

These are decisions that shape every requirement below.
Changing one is a spec change.

**ARCH-001 (Two runtimes).** The orchestrator and the harness are separate programs running on separate Python interpreters.
The orchestrator runs on the user's Python (or the frozen executable).
The harness runs on the Python embedded in the game's Ren'Py engine, which the tool does not choose: it is whatever Python 3 that Ren'Py 8 release ships (3.9 for the earliest 8.x).
Harness code MUST therefore be valid on Python 3.9 and later and use only the standard library and the Ren'Py API.

**ARCH-002 (File-based protocol).** The harness reports to the orchestrator by appending JSON lines to an event file whose path the orchestrator supplies.
Standard output is not relied on, because Windows game executables are GUI-subsystem programs with no usable console.

**ARCH-003 (Engine does the work).** RenPyTester never re-implements Ren'Py's parser or execution model.
Script loading, lint, translation lookup and text substitution are all performed by the game's own engine, so results match what players would see on that engine version.

**ARCH-004 (No source required).** Everything MUST work on a game whose scripts exist only as compiled `.rpyc` inside `.rpa` archives.

**ARCH-005 (Orchestrator has no runtime dependencies).** The orchestrator uses only the Python standard library at runtime, so "run from source" needs nothing but Python.
Development and packaging tools (test runner, linter, PyInstaller) are dev-only dependencies.
The graphical interface is built on the standard library's `tkinter` for the same reason.

**ARCH-006 (Invisible by default).** A normal run never puts a game window on the user's screen, never plays the game's audio, and never takes keyboard or mouse focus.
Because the game is driven at high speed, a visible window would flash rapidly, which is a photosensitivity hazard as well as a nuisance.
A visible window exists only when the user explicitly asks for one.

---

## 4. Functional requirements

### 4.1 Game discovery and launch (GAME)

| ID | Pri | Requirement |
| --- | --- | --- |
| GAME-001 | MUST | Accept a path to a game directory. Also accept a path to anything inside it (the `game/` folder, the launcher `.exe`/`.sh`/`.py`, a macOS `.app`) and resolve the game directory from it. |
| GAME-002 | MUST | Detect whether the game is a built distribution or a project, and report which was detected. |
| GAME-003 | MUST | Launch a built distribution using the engine it ships with, on Windows, Linux and macOS. |
| GAME-004 | MUST | Launch a project using a Ren'Py SDK given by `--sdk PATH` or the `RENPY_SDK` environment variable. |
| GAME-005 | MUST | If no usable engine can be found, exit with code 3 and a message that says exactly what was looked for and how to supply an SDK. |
| GAME-006 | MUST | Detect and report the game's Ren'Py version, Python major version, game name and version, and the list of available languages, before any stage runs. |
| GAME-007 | MUST | Every game process runs with no visible window, no taskbar or dock entry where the platform allows, no audio output and no focus stealing (ARCH-006). If this cannot be achieved on the current platform and engine version, the run stops with an explanation, and continues only if the user passes `--show-window` after a photosensitivity warning. |
| GAME-008 | SHOULD | `--sdk` may be used with a built distribution to override the bundled engine. |
| GAME-009 | COULD | `--download-sdk VERSION` fetches a matching SDK into a cache directory. |

### 4.2 Safety and isolation (SAFE)

A user must be able to trust the tool with their only copy of a project.

| ID | Pri | Requirement |
| --- | --- | --- |
| SAFE-001 | MUST | Default mode is **in place**: the game is tested where it is. The only change made to the game directory is the addition of harness files with a reserved name prefix (`zzz_renpytester_`). No existing file is modified, moved or deleted by RenPyTester. |
| SAFE-002 | MUST | All harness files, including compiled files the engine generates from them, are removed when the run ends, including on error, Ctrl+C, or timeout. |
| SAFE-003 | MUST | On startup, detect harness files left behind by a previous run that was killed, remove them, and say so. |
| SAFE-004 | MUST | Saves and persistent data are redirected to a temporary directory. The user's real saves and persistent data are never read or written. |
| SAFE-005 | MUST | Refuse to start if another RenPyTester run is active on the same game directory. |
| SAFE-006 | MUST | `--sandbox` (a checkbox in the GUI) runs against a copy of the game instead of the original, for games whose own script writes or deletes files in the game directory. In this mode nothing at all is written to the original. |
| SAFE-009 | MUST | The sandbox copy is kept in a per-user cache directory after the run and reused by later runs of the same game. |
| SAFE-010 | MUST | Before each sandbox run the copy is synchronised with the original, rsync-style: only files that are new or changed in the original are copied, files that no longer exist in the original are removed from the copy, and files the game itself altered in the copy during an earlier run are restored. After synchronisation the copy is identical to the original. |
| SAFE-011 | MUST | Change detection compares file size and modification time by default; `--sandbox-verify` compares content hashes instead, for when timestamps cannot be trusted. |
| SAFE-012 | MUST | The report states where the sandbox copy is and how much disk space it uses. `renpytester cache list` and `renpytester cache clear [GAME]` show and delete cached copies; the GUI offers the same. |
| SAFE-007 | SHOULD | Detect when the game itself created, changed or deleted files in the game directory during an in-place run, and list them in the report as a warning recommending `--sandbox`. |
| SAFE-008 | MUST | No network access, no telemetry. (GAME-009 is the single opt-in exception.) |

### 4.3 Driving the game (RUN)

The harness must get through a game with no human present.

| ID | Pri | Requirement |
| --- | --- | --- |
| RUN-001 | MUST | Start from the same entry point a player would (including `splashscreen` if defined), bypassing the main menu by starting a new game. |
| RUN-002 | MUST | Advance through dialogue and narration without waiting for clicks. |
| RUN-003 | MUST | Resolve `menu` statements by selecting the choice the explorer (4.4) asks for. Choices whose condition is false are not selectable and are recorded as such. |
| RUN-004 | MUST | Pass through timed pauses, hard pauses, transitions and movies without waiting real time. |
| RUN-005 | MUST | Answer text input prompts with a configurable value (default `Tester`), honouring the prompt's length and allowed-character limits. |
| RUN-006 | MUST | Handle `call screen` and other custom interactions by enumerating the activatable elements on screen and choosing among them as decisions, the same way menu choices are. If nothing activatable can be found, report a `stuck` finding and end the path. |
| RUN-007 | MUST | Treat return to main menu, end of script, and a game-initiated quit as a normal end of path, not an error, and continue with the next path. |
| RUN-008 | MUST | Emit a heartbeat with the current script location. If the orchestrator sees no progress for `--timeout` seconds (default 60) it kills the game, reports a `hang` finding with the last known location and path, and continues with remaining work. |
| RUN-009 | MUST | Detect a path that keeps executing without reaching new statements (step budget per path, default configurable) and end it with a `loop` finding of severity *warning*. |
| RUN-010 | MUST | Seed the game's random number generator so that the same command on the same game produces the same paths and findings. The seed is configurable and recorded in the report. |
| RUN-011 | MUST | After an error on one path, continue testing other paths. One crash never ends the run. |
| RUN-012 | MUST | If the game process dies without the harness reporting why, report an `engine-crash` finding with the process exit code and the tail of the engine's log, then relaunch and continue. |
| RUN-013 | SHOULD | Typical performance: at least 500 dialogue statements per second per game process on a mid-range desktop. |
| RUN-014 | MUST | Explore several routes at the same time by running multiple game processes in parallel. `--jobs N` sets how many; the default is chosen from the number of CPU cores and available memory. `--jobs 1` is always supported. |
| RUN-015 | MUST | Parallel processes do not interfere with each other: each has its own save and persistent directory and its own event file. |
| RUN-016 | MUST | Nothing in a run waits on real time: no rendering to a display, no frame-rate limit, no audio playback, no animation or transition delays (extends RUN-004). |

### 4.4 Route exploration (EXP)

Exhaustive path coverage is impossible (choices multiply), so the target is **statement coverage**: execute every reachable statement at least once, in a realistic game state.

| ID | Pri | Requirement |
| --- | --- | --- |
| EXP-001 | MUST | Explore branches so as to maximise statement coverage: at each decision point, prefer options that can lead to statements not yet executed. |
| EXP-002 | MUST | Reach deep branches without replaying the game from the start for every path (snapshot and restore of game state at decision points). |
| EXP-003 | MUST | Bound the work: `--max-paths`, `--max-time` and `--max-depth` limits, with defaults that finish a typical short game in minutes. When a limit stops exploration early, the report says so and gives the coverage reached. |
| EXP-004 | MUST | Record for each finding the full path that led to it. |
| EXP-005 | MUST | Report coverage: statements executed / total, per file and per label, plus the list of labels never reached. |
| EXP-006 | MUST | `--strategy first` plays a single path taking the first available choice everywhere. This is the fast smoke test. |
| EXP-007 | MUST | The `labels` strategy starts execution at every label in isolation, to reach code that normal exploration cannot. It is on by default and runs alongside normal exploration in the same pool of game processes (RUN-014). `--no-labels` turns it off. |
| EXP-011 | MUST | Normal exploration has priority on the process pool; label runs use only spare capacity and never delay it. |
| EXP-012 | MUST | When both strategies have finished, each finding from a label run is resolved against normal exploration: if normal exploration executed the same statement without error, the finding is dropped; if normal exploration reported the same problem, the two are merged into one confirmed finding (ERR-010); if normal exploration never executed that statement, the finding is kept as a *possible issue*. |
| EXP-013 | MUST | Possible issues are reported in their own section, separate from confirmed findings in every output, are marked as such in the JSON and JUnit reports, and do not affect the exit code unless `--fail-on-possible` is given. |
| EXP-014 | MUST | Coverage is reported as two figures: statements executed by normal exploration, and statements additionally executed only by label runs (low confidence). |
| EXP-015 | MUST | The resolution in EXP-012 depends only on the final results of both strategies, never on which finished first, so the report is the same for any `--jobs` value (NFR-001). |
| EXP-008 | SHOULD | `--replay PATH_ID` (or a path file) re-runs exactly one recorded path in a visible window at normal game speed, so the developer can watch a failure happen. This is the one situation where a game window is shown by request. |
| EXP-009 | SHOULD | User-authored paths in the config file ("always pick *Yes* at this menu", "play this exact route") are run in addition to automatic exploration. |
| EXP-010 | COULD | Persist coverage between runs so that a later run prioritises statements changed since the last one. |

### 4.5 Error detection (ERR)

Each row is a class of finding.
Every MUST class has a fixture game that triggers it (see 7.2).

| ID | Pri | Finding | Severity |
| --- | --- | --- | --- |
| ERR-001 | MUST | Script fails to parse or load (the game cannot start). | error |
| ERR-002 | MUST | Uncaught exception while executing a statement: undefined variable, bad Python, bad `jump`/`call` target, missing screen, etc. | error |
| ERR-003 | MUST | Image, audio, video or font file referenced but not loadable. | error |
| ERR-004 | MUST | Undefined image shown (`show`/`scene` with a name that was never defined). | error |
| ERR-005 | MUST | Malformed text: unclosed or unknown text tag, or failed `[variable]` interpolation, in dialogue, menu captions or screen text. | error |
| ERR-006 | MUST | Hang, loop, stuck, or engine crash (RUN-006, -008, -009, -012). | error / warning |
| ERR-007 | SHOULD | Label that is never reached by any path and never referenced. | info |
| ERR-008 | SHOULD | Menu with no selectable choice in some reached state. | error |
| ERR-009 | COULD | Save and load round-trip fails at a point in the game (unpicklable state). | error |

Every finding MUST carry: a stable ID, class, severity, message, script file and line, enclosing label, the stage that found it, the language active at the time, the reproduction path, and the engine traceback where one exists.

**ERR-010 (MUST).** The same underlying problem reached by many paths is reported once, with a count and the shortest reproduction path.

**ERR-011 (MUST).** Intentional errors are not reported: an exception the game's own script catches is not a finding.

### 4.6 Lint stage (LINT)

| ID | Pri | Requirement |
| --- | --- | --- |
| LINT-001 | MUST | Run the engine's built-in lint and convert its output into findings, with file and line where lint provides them. |
| LINT-002 | MUST | Lint findings that duplicate a finding from another stage are merged with it (ERR-010). |
| LINT-003 | SHOULD | Include lint's statistics (word count, dialogue blocks, per-language counts) in the report summary. |

### 4.7 Translation testing (TL)

| ID | Pri | Requirement |
| --- | --- | --- |
| TL-001 | MUST | Discover all languages the game defines. `--languages a,b` restricts the set; default is all. |
| TL-002 | MUST | For each language, switching to it succeeds: its `translate python` and `translate style` blocks execute without exception. |
| TL-003 | MUST | For each language, every translated dialogue line and string is checked for malformed text tags (ERR-005). |
| TL-004 | MUST | For each language, every translated line reached during route exploration is rendered with the real game state at that point, so that a bad `[variable]` reference in a translation is found. |
| TL-005 | MUST | Report untranslated dialogue lines and untranslated strings per language, with counts and locations. Severity *warning*; can be raised to *error* in the config file. |
| TL-006 | MUST | Report differences between source and translation in the set of interpolated `[variables]` (a variable dropped, added or misspelt). |
| TL-007 | SHOULD | Report orphaned translations: translation blocks whose source line no longer exists. |
| TL-008 | SHOULD | Report characters in translated text that the font in use for that language cannot draw (the "missing glyph squares" bug). |
| TL-009 | SHOULD | Report mismatches between source and translation in text tags that change meaning or flow (`{w}`, `{p}`, `{nw}`, `{a}`), severity *info*. |
| TL-010 | SHOULD | Translated lines that cause a statement to behave differently (e.g. a translation block containing different statements than the source) are executed, not only checked as text. |
| TL-011 | COULD | Report translated text that overflows the dialogue window. |

Translation testing MUST NOT multiply run time by the number of languages: checking each language does not require replaying every route once per language.

### 4.8 Screen smoke test (UI)

| ID | Pri | Requirement |
| --- | --- | --- |
| UI-001 | SHOULD | Display each standard menu screen the game defines (main menu, preferences, save, load, history, about, help, confirm) and report any exception. |
| UI-002 | SHOULD | Repeat UI-001 in each tested language. |
| UI-003 | COULD | Display every screen that has no required parameters. |

### 4.9 Reporting (REP)

| ID | Pri | Requirement |
| --- | --- | --- |
| REP-001 | MUST | Console output: a single progress bar that updates in place (stage, percent, paths done, coverage, findings so far, estimated time left), then a summary grouped by severity, with file:line for each finding. Readable without colour; colour used when the terminal supports it. When output is not a terminal (CI logs), plain periodic progress lines replace the bar. |
| REP-002 | MUST | JSON report containing everything: game info, run settings, seed, all findings, all paths that led to findings, coverage. The schema carries a version number and is documented in `docs/`. |
| REP-003 | MUST | JUnit XML report, so CI systems show findings as failed tests. |
| REP-004 | MUST | Self-contained single-file HTML report (no internet needed to view it), written for the game developer and concise: a one-screen summary first (pass/fail, counts by severity, coverage, per-language translation status), then confirmed findings grouped by script file, then possible issues (EXP-013) in a separate section, each finding collapsed to one line that expands to show the reproduction path and traceback. Filter by severity, stage and language. |
| REP-005 | MUST | Reports are written to `--output DIR` (default `./renpytester-report/`), never inside the game directory. |
| REP-006 | MUST | Messages are written for game developers, not engine developers: say what is wrong and where in *their* script, with the raw traceback available but secondary. |
| REP-007 | SHOULD | `--baseline REPORT.json` reports only findings that are not in an earlier report, so a project with known issues can still gate on new ones. |
| REP-008 | MUST | The engine's own log, `traceback.txt` and `errors.txt` output from the run are preserved in the output directory. |

### 4.10 Command line (CLI)

| ID | Pri | Requirement |
| --- | --- | --- |
| CLI-001 | MUST | `renpytester GAME` runs all default stages (`lint`, `routes`, `translations`) with default settings. The `routes` stage includes label runs (EXP-007). |
| CLI-002 | MUST | `--stages a,b` selects stages. |
| CLI-003 | MUST | Exit codes: `0` no findings at or above the failure threshold; `1` findings at or above it; `2` bad usage or configuration; `3` the game could not be launched or the tool failed internally. |
| CLI-004 | MUST | `--fail-on error\|warning\|info\|never` sets the threshold (default `error`). |
| CLI-005 | MUST | `--help` documents every option with its default; `--version` prints the version. |
| CLI-006 | MUST | Ctrl+C stops the game, cleans up (SAFE-002), and still writes a partial report marked incomplete. |
| CLI-007 | MUST | Launched with no arguments (for example by double-click), the executable opens the graphical interface (4.14). Dragging a game folder onto the executable opens the graphical interface with that game already selected. `renpytester gui [GAME]` does the same from a terminal. |
| CLI-008 | SHOULD | `renpytester info GAME` prints what GAME-006 detects and exits, without running the game's story. |
| CLI-009 | — | *Withdrawn in 0.2.* Replaced by section 4.14. |
| CLI-010 | MUST | `--lang en\|pt-BR` selects the interface language (4.15). |

### 4.11 Configuration (CFG)

| ID | Pri | Requirement |
| --- | --- | --- |
| CFG-001 | MUST | Zero configuration is a supported mode: every setting has a default. |
| CFG-002 | MUST | Optional `renpytester.toml`, looked for in the game directory, or given by `--config`. Command-line options override the file. |
| CFG-003 | MUST | Ignore rules: suppress findings by class, file glob, label, language, or message pattern. Suppressed findings are counted in the summary, never silently dropped. |
| CFG-004 | MUST | Unknown keys in the config file are an error (exit 2), not ignored. |
| CFG-005 | SHOULD | Per-prompt input values, and initial values for chosen game variables, so games that gate content on input can be explored. |
| CFG-006 | SHOULD | Mark labels as excluded from exploration (e.g. a minigame that cannot be automated). |

### 4.12 Compatibility (COMPAT)

| ID | Pri | Requirement |
| --- | --- | --- |
| COMPAT-001 | MUST | Host platforms: Windows 10+ x64, Linux x64, macOS (Intel and Apple Silicon). |
| COMPAT-002 | MUST | Ren'Py 8.x games (Python 3 engines). |
| COMPAT-003 | — | *Withdrawn in 0.2.* Ren'Py 6.99 support. |
| COMPAT-004 | MUST | A game on Ren'Py 7 or older is detected before anything is launched or injected, and refused with a clear message that Python 2 engines are not supported (exit 3). An unrecognised newer engine version produces a warning and a best-effort run, not a crash. |
| COMPAT-005 | MUST | When a check cannot be performed on a given engine version, the report lists it as *skipped* with the reason. A skipped check is never shown as passed. |
| COMPAT-006 | MUST | Orchestrator runs on Python 3.11 and later. |
| COMPAT-007 | MUST | The graphical interface works wherever the orchestrator does. When run from source on a Python without `tkinter` (some Linux distributions package it separately), the tool says which package to install and the command line remains fully usable. |

### 4.13 Distribution (DIST)

| ID | Pri | Requirement |
| --- | --- | --- |
| DIST-001 | MUST | Run from a clone with no install step beyond having Python: `python -m renpytester GAME`. |
| DIST-002 | MUST | Single-file executable for Windows, with the harness and the graphical interface embedded. No installer, no Python needed. |
| DIST-003 | SHOULD | Single-file executables for Linux and macOS. |
| DIST-004 | SHOULD | Installable as a package (`pipx install`, `uv tool install`) exposing the `renpytester` command. |
| DIST-005 | MUST | Executables are built by CI from a tagged commit and attached to a GitHub release. No hand-built releases. |
| DIST-006 | MUST | The executable and the from-source run behave identically; the test suite's end-to-end tests run against both. |

### 4.14 Graphical interface (GUI)

One simple window.
It is a front end to the same run the command line performs, not a second implementation.

| ID | Pri | Requirement |
| --- | --- | --- |
| GUI-001 | MUST | Choose the game by browsing for a folder or dropping one on the executable. Once chosen, show what was detected (GAME-006): name, engine version, languages. |
| GUI-002 | MUST | Options shown as plain controls with sensible defaults: stages to run, languages to test, sandbox copy on/off (SAFE-006), and an optional SDK folder when the game needs one. Everything else stays at its default or comes from `renpytester.toml`. |
| GUI-003 | MUST | A *Run* button that becomes *Cancel* during a run. Cancelling behaves as Ctrl+C does (CLI-006). |
| GUI-004 | MUST | During a run: one progress bar, the current stage, and running counts of errors and warnings. No game window appears (ARCH-006). The interface stays responsive. |
| GUI-005 | MUST | After a run: a pass/fail result, counts by severity, and a button that opens the HTML report in the default browser. |
| GUI-006 | MUST | Problems that stop a run (no engine found, unsupported engine, game already being tested) are shown as a readable message in the window, not as a traceback or a silent exit. |
| GUI-007 | MUST | Every GUI run can be expressed as a command line; the window shows that command so a developer can copy it into CI. |
| GUI-008 | SHOULD | Remember the last game folder and options between sessions. |
| GUI-009 | SHOULD | List the findings in the window itself, with file and line, without opening the report. |
| GUI-010 | SHOULD | Manage cached sandbox copies (SAFE-012). |

### 4.15 Interface languages (I18N)

| ID | Pri | Requirement |
| --- | --- | --- |
| I18N-001 | MUST | The console output, the graphical interface, the HTML report and all finding messages are available in English (`en`) and Brazilian Portuguese (`pt-BR`). |
| I18N-002 | MUST | The language is taken from the operating system's locale, falling back to English; `--lang` or the config file overrides it; the GUI has a language selector. |
| I18N-003 | MUST | Machine-readable output is language-neutral: JSON keys, finding class identifiers, severity names, exit codes and JUnit test names are the same whatever the interface language, so CI results and baselines (REP-007) do not depend on it. |
| I18N-004 | MUST | Findings are stored as a message identifier plus parameters, and turned into text when displayed, so one JSON report can be rendered in either language. |
| I18N-005 | MUST | Text that comes from the game or the engine (tracebacks, script lines, lint's own wording) is shown as is, never translated. |
| I18N-006 | MUST | A test fails the build if any message exists in one language and not the other. |
| I18N-007 | SHOULD | The README and user guide are provided in both languages. Source code, the specification and commit messages are English only. |
| I18N-008 | SHOULD | Adding a third language requires adding one message file and no code changes. |

---

## 5. Non-functional requirements (NFR)

| ID | Pri | Requirement |
| --- | --- | --- |
| NFR-001 | MUST | **Determinism.** Same tool version, game, engine, settings and seed give the same findings and coverage, whatever the value of `--jobs`, for any run that finishes without hitting a limit (EXP-003). A run cut short by `--max-time` may differ between machines and says so in the report. |
| NFR-002 | MUST | **No false passes.** If a stage could not run or did not finish, the run does not exit 0 claiming success; the report states what was not checked. |
| NFR-003 | MUST | **Low false positives.** On the reference games (7.1), which are known to work, a default run reports zero findings of severity *error*. |
| NFR-004 | MUST | **Robustness.** A bug in the harness is reported as a tool error (exit 3, "this is a RenPyTester bug"), never as a problem in the user's game. |
| NFR-005 | SHOULD | **Speed.** A default run on a 50,000-word game completes in under 5 minutes on a 4-core desktop. |
| NFR-007 | MUST | **Unobtrusive.** During a default run the user can keep working on the same machine: nothing appears on screen except the tool's own progress display, no sound plays, and focus is never taken (ARCH-006). |
| NFR-008 | MUST | **Documentation lint.** Every Markdown file in the repository passes `markdownlint` using the configuration in `.markdownlint.json`. This is checked in CI and a failure blocks the merge. Rules are changed in that file, never silenced inline without a comment giving the reason. |
| NFR-006 | MUST | **Licence hygiene.** No game content or engine code is committed to this repository or bundled in releases. RenPyTester is GPL-3.0. |

---

## 6. Planned structure

Indicative, not binding.
Settled in the design step of milestone M1.

```text
src/renpytester/            orchestrator (Python 3.11+, stdlib only)
    cli, gui, discovery, launcher, sandbox, protocol, explorer, report/, locale/
src/renpytester/harness/    files injected into the game (engine's Python 3, Ren'Py API)
tests/unit/                 orchestrator logic, no engine needed
tests/e2e/                  real engine against fixture games
tests/fixtures/games/       tiny purpose-built games, one seeded bug each
docs/SPEC.md                this file
docs/report-schema.md       JSON report schema (REP-002)
```

Where the exploration logic lives (in the orchestrator, steering the harness over the protocol; or in the harness, with the orchestrator only supervising) is an open design question, to be answered by the M0 spikes.

---

## 7. Verification

### 7.1 Reference games

| Game | Role | Source |
| --- | --- | --- |
| **The Question** | Smallest real game. Known-good baseline for NFR-003. | Ships inside the Ren'Py SDK. |
| **Ren'Py Tutorial** | Many languages, many engine features. Baseline for translation testing. | Ships inside the Ren'Py SDK. |

Doki Doki Literature Club was a reference game in draft 0.1 and was dropped in 0.2 together with Python 2 engine support (it runs on Ren'Py 6.99).

### 7.2 Fixture games

For each MUST row in 4.5 and 4.7 there is a minimal fixture game in `tests/fixtures/games/` containing exactly one seeded bug of that class, plus one clean fixture with none.
The end-to-end tests assert that each fixture produces exactly its expected finding, at the expected file and line, and that the clean fixture produces none.
Fixtures are original content written for this repository.

### 7.3 Traceability

Every test names the requirement IDs it verifies.
A requirement is *done* when it has at least one passing test that names it.

Version matrix: orchestrator unit tests run on every supported Python from 3.11 to the current release (locally with the `py` launcher and one virtual environment per version; in CI as a matrix).
End-to-end tests run against the oldest supported and the newest Ren'Py 8.x SDK.
The harness's Python version cannot be chosen with a virtual environment, because it is the one inside each SDK; testing several SDK versions is what covers it.

### 7.4 Acceptance for 1.0

1. All MUST requirements done per 7.3.
2. `renpytester <The Question>` with no other arguments: exit 0, 100% statement coverage, zero errors.
3. `renpytester <Tutorial>`: completes within limits, zero errors, per-language translation summary present.
4. Every fixture game yields exactly its expected finding.
5. A fixture game that writes to its own directory, run with `--sandbox`: the original is byte-for-byte unchanged, and a second run copies only the files changed in between.
6. Items 2 and 4 also pass using the Windows single-file executable.
7. The same run started from the graphical interface gives the same findings as the command line, in both English and Brazilian Portuguese.
8. During items 2 to 4 no game window is shown and no audio is played.

---

## 8. Milestones

| | Milestone | Delivers | Requirements |
| --- | --- | --- | --- |
| M0 | Feasibility spikes | Throwaway experiments answering every item in 9.1, on the oldest and newest Ren'Py 8.x. Spec revised with the results. | — |
| M1 | Walking skeleton | Discover, launch invisibly, inject, clean up, play one path (`--strategy first`), catch exceptions, console + JSON report. Message catalogue in both languages from the first message onward. | GAME-001–007, I18N-001–006, SAFE-001–005, RUN-001–005, -007, -008, -011, EXP-006, ERR-001, -002, REP-001, -002, CLI-001, -003 |
| M2 | Lint | Lint stage and finding merge. | LINT, ERR-010 |
| M3 | Exploration | Coverage-guided branching, snapshots, parallel processes, label runs and their resolution, limits, coverage report, custom screens. | EXP-001–005, -007, -011–015, RUN-006, -009, -010, -012, -014–016, ERR-003–006 |
| M4 | Translations | Language discovery and all TL MUSTs. | TL |
| M5 | Reports and config | JUnit, HTML, config file, ignore rules, baseline. | REP-003–008, CFG, remaining CLI |
| M6 | Sandbox | Cached copy with incremental synchronisation, cache commands. | SAFE-006, -007, -009–012 |
| M7 | Graphical interface | The window described in 4.14. | GUI, CLI-007 |
| M8 | Packaging | Single-file executables, release CI. | DIST |
| M9 | Hardening | Screen smoke test, performance, acceptance. | UI, NFR, 7.4 |

---

## 9. Open items

### 9.1 Technical assumptions to verify in M0

Nothing below has been tested yet.
Each is a belief about the engine that the design depends on.
If one turns out false, the affected requirements are revised before M1 starts.

1. A loose `.rpy` file added to `game/` is loaded by a built distribution whose own scripts are archived.
2. A built distribution can run engine commands such as `lint` from its bundled engine, without the SDK.
3. Saves and persistent data can be redirected by command-line option or environment variable (SAFE-004).
4. There is a hook point to intercept uncaught exceptions before the engine shows its error screen (ERR-002, RUN-011).
5. Game state can be snapshotted and restored at a menu from inside the harness, quickly and without touching disk more than necessary (EXP-002).
   Candidates: the rollback system, or in-memory saves.
6. The engine can run with no window, no audio device and no focus stealing on Windows, Linux and macOS (GAME-007, ARCH-006).
   This is now a MUST, so it is the first spike to run.
   If true headless operation is not possible, find out whether a hidden or off-screen window is.
7. The elements of an arbitrary screen that a player could click can be enumerated from inside the harness (RUN-006).
8. A translated line can be looked up and substituted for another language without changing the active language of the running game (TL-004 and the no-multiplication rule).
9. How much of lint already covers TL-003, -005 and -007, so that it is reused, not duplicated.
10. A font's glyph coverage can be queried from inside the engine (TL-008).
11. Several processes of the same game can run at once from one game directory without conflicting, for example over compiled script files or a single-instance lock (RUN-014, RUN-015).
12. How parallel processes behave in sandbox mode when the game writes to its own directory: whether one shared copy is enough or each process needs its own.
13. Which is the oldest Ren'Py 8.x release worth supporting, and which Python it embeds (ARCH-001, COMPAT-002).
14. `tkinter` can accept a folder dropped onto the open window using only the standard library; if not, GUI-001 is met by browsing and by dropping on the executable.

### 9.2 Decisions

No decisions are open.

Settled on 2026-10-06:

| # | Decision |
| --- | --- |
| D1 | Test in place by default. Sandbox copy is opt-in (flag and GUI checkbox), cached between runs and synchronised incrementally (SAFE-006, -009 to -012). |
| D2 | A graphical interface is required for 1.0 (4.14). |
| D3 | Python 2 engines (Ren'Py 7 and older) are out of scope for now. Doki Doki Literature Club is dropped as a reference game. |
| D4 | Untranslated lines are warnings. |
| D5 | Label runs are on by default, run alongside normal exploration, and their findings are filtered against it and reported separately as possible issues (EXP-007, -011 to -015). |
| D6 | The HTML report is required for 1.0 and must be concise (REP-004). |
| D7 | Command name `renpytester`. Interface in English and Brazilian Portuguese (4.15). |

---

## 10. Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-06 | 0.1 | First draft. |
| 2026-10-06 | 0.2 | Owner decisions D1–D4, D6, D7. Dropped Python 2 engines and DDLC (COMPAT-003 withdrawn). Cached incremental sandbox (SAFE-009 to -012). GUI required (4.14, CLI-009 withdrawn). Interface languages en and pt-BR (4.15). HTML report now MUST. Invisible operation now MUST (ARCH-006, GAME-007, NFR-007). Parallel exploration (RUN-014 to -016). |
| 2026-10-06 | 0.3 | D5 settled: label runs on by default alongside normal exploration, resolved and reported as possible issues (EXP-007 now MUST, EXP-011 to -015 added). Markdown lint requirement (NFR-008); tables reformatted to pass it. |
