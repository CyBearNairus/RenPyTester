# RenPyTester Specification

| Field | Value |
| --- | --- |
| Status | Version 0.16 **approved** by the project owner on 2026-10-06. Version 0.17 amendments (from building M7) await approval. Versions 0.18 to 0.21 add requirements the owner asked for. |
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

**ARCH-007 (No rendering).** The harness replaces the engine's interaction layer, so a run draws no frames and waits for nothing.
A consequence is that problems which a player would only see when a frame is drawn do not surface by themselves.
Every such class in 4.5 (missing files, undefined images, malformed text, screen errors) is therefore checked explicitly by the harness at the moment the statement executes.

**ARCH-008 (Exploration lives in the harness).** Decisions, snapshots and coverage are handled inside the game process, which explores many paths per launch.
The orchestrator launches, supervises and divides work between processes; it does not steer individual choices.

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
| GAME-010 | MUST | The engine never opens a file in another program during a run. By default Ren'Py opens `traceback.txt` or `errors.txt` in the system text editor when a game fails; this is suppressed, and the same files are kept in the output directory instead (REP-008). |
| GAME-008 | SHOULD | `--sdk` may be used with a built distribution to override the bundled engine. |
| GAME-009 | COULD | `--download-sdk VERSION` fetches a matching SDK into a cache directory. |

### 4.2 Safety and isolation (SAFE)

A user must be able to trust the tool with their only copy of a project.

| ID | Pri | Requirement |
| --- | --- | --- |
| SAFE-001 | MUST | Default mode is **in place**: the game is tested where it is. RenPyTester itself only adds harness files with a reserved name prefix (`zzz_renpytester_`). When the run ends the game directory is byte-for-byte what it was before (SAFE-013). |
| SAFE-013 | MUST | The engine writes into the game directory on its own during any launch: it rewrites the compiled caches under `game/cache/`, creates `game/saves/`, and writes log files beside the game. Logs are redirected to the output directory. Files the engine modifies are backed up before the run and restored after it; files and folders it creates are removed. This holds after a crash, Ctrl+C or timeout, and leftovers from a killed run are repaired on the next start (SAFE-003). |
| SAFE-014 | MUST | The engine's own script backup into the user's profile is disabled for test runs, so nothing is written outside the game directory, the output directory and the tool's cache. |
| SAFE-002 | MUST | All harness files, including compiled files the engine generates from them, are removed when the run ends, including on error, Ctrl+C, or timeout. |
| SAFE-003 | MUST | On startup, detect harness files left behind by a previous run that was killed, remove them, and say so. |
| SAFE-004 | MUST | Saves and persistent data are redirected to a temporary directory. The user's real saves and persistent data are never read or written. |
| SAFE-005 | MUST | Refuse to start if another RenPyTester run is active on the same game directory. |
| SAFE-006 | MUST | `--sandbox` (a checkbox in the GUI) runs against a copy of the game instead of the original, for games whose own script writes or deletes files in the game directory. In this mode nothing at all is written to the original. The copy is tested exactly as a game is tested in place, and the report is the game's: its path, its name, and file names relative to its folder. `--sandbox-verify` alone also turns the sandbox on, and `sandbox = true` in the config file does the same as the option. Files that RenPyTester itself left in the original, after a run that was killed, are not copied. A copy is used by one run at a time (SAFE-005); a run in place and a sandbox run of the same game do not get in each other's way. |
| SAFE-009 | MUST | The sandbox copy is kept in a per-user cache directory after the run and reused by later runs of the same game. The directory is `%LOCALAPPDATA%\RenPyTester\cache` on Windows, `~/Library/Caches/RenPyTester` on macOS, and `$XDG_CACHE_HOME/renpytester` or `~/.cache/renpytester` elsewhere; the `RENPYTESTER_CACHE` environment variable names another. Each game folder has one copy, told apart by the folder's full path. |
| SAFE-010 | MUST | Before each sandbox run the copy is synchronised with the original, rsync-style: only files that are new or changed in the original are copied, files that no longer exist in the original are removed from the copy, and files the game itself altered in the copy during an earlier run are restored. After synchronisation the copy is identical to the original. Folders are part of this: empty ones are made, and ones that are gone are removed. |
| SAFE-011 | MUST | Change detection compares file size and modification time by default; `--sandbox-verify` compares content hashes instead, for when timestamps cannot be trusted. By default a file is left alone when the original and the copy each still have the size and modification time they had after the last synchronisation; each side is compared only with its own earlier state, so disks that keep time with different precision do not cause needless copying. A copy with no such record is copied again in full. With `--sandbox-verify` the record is not used: the contents of both files are read and compared. |
| SAFE-012 | MUST | The report states where the sandbox copy is and how much disk space it uses. `renpytester cache list` and `renpytester cache clear [GAME]` show and delete cached copies; the GUI offers the same. In the report: the path of the copy, its size in bytes and in files as the run left it, and how many files were copied and removed to bring it up to date. `cache list` also says where the cache is and when each copy was last used. `cache clear` leaves alone a copy that is being tested at that moment, and says so. |
| SAFE-007 | SHOULD | Detect when the game itself created, changed or deleted files in the game directory during an in-place run, and list them in the report as a warning recommending `--sandbox`. This is a note in the report, not a finding: writing files is not a fault in the game. It counts and lists the files created, changed and deleted. Created files are removed again; changed and deleted ones had no backup and stay as the game left them, which the note says. Files the engine or RenPyTester write are not counted. In a sandbox run the same is reported about the copy, without the recommendation. When several game processes ran, a second note says that they shared the one folder, so one may have read what another wrote, and recommends `--jobs 1` if results vary. |
| SAFE-008 | MUST | No network access, no telemetry. (GAME-009 is the single opt-in exception.) |

### 4.3 Driving the game (RUN)

The harness must get through a game with no human present.

| ID | Pri | Requirement |
| --- | --- | --- |
| RUN-001 | MUST | Start from the same entry point a player would (including `splashscreen` if defined), bypassing the main menu by starting a new game. |
| RUN-002 | MUST | Advance through dialogue and narration without waiting for clicks. |
| RUN-003 | MUST | Resolve `menu` statements by selecting the choice the explorer (4.4) asks for. Choices whose condition is false are not selectable and are recorded as such. |
| RUN-004 | MUST | Pass through timed pauses, hard pauses, transitions and movies without waiting real time. |
| RUN-018 | MUST | A hand-built interaction that offers nothing to activate and is not a screen call, such as a movie cutscene, is passed through like a pause (extends RUN-004). |
| RUN-017 | MUST | A minigame or other interaction with nothing to activate does not end the path. The interaction is skipped: the tool never tries to play it, and instead continues the story after it with each plausible outcome (RUN-019). A `stuck` finding of severity *info* records that the interaction itself was not exercised. |
| RUN-019 | MUST | Plausible outcomes of a skipped interaction are found by reading the script that follows it: the values its result, and any variable read there that the story has not set, are compared against in the conditions that come next (for example `if _return == "eileen"`), plus one value that matches none of them. Each outcome is explored as a separate branch from a snapshot, the same way menu choices are. |
| RUN-020 | MUST | When no outcome can be inferred from the script, the story continues with a neutral result, and with each label that the script's next conditional blocks jump or call to. |
| RUN-024 | MUST | Inference reads at most the next 40 statements after the interaction, follows up to three unconditional jumps, and stops at a menu or a return. It recognises the result being copied to another variable (`$ winner = _return`), comparisons with constants, membership in a list of constants, and use as a yes-or-no test. For a numeric comparison such as `score > 10` it tries the value and the values on either side of it. |
| RUN-021 | MUST | Everything reached after a skipped interaction ran in a state the tool made up, so findings there are *possible issues* (EXP-013) and coverage there counts as low confidence (EXP-014), exactly as for label runs. A finding also reached by a path with no skipped interaction is confirmed (EXP-012). |
| RUN-022 | SHOULD | The config file can state the outcome of a named interaction (for example "the `pong` screen returns `player`"), which replaces guessing and makes what follows normal, confirmed exploration. |
| RUN-005 | MUST | Answer text input prompts with a configurable value (default `Tester`), honouring the prompt's length and allowed-character limits. |
| RUN-006 | MUST | Handle `call screen` and other custom interactions by enumerating the activatable elements on screen and choosing among them as decisions, the same way menu choices are. If nothing activatable can be found, report a `stuck` finding and end the path. |
| RUN-007 | MUST | Treat return to main menu, end of script, and a game-initiated quit as a normal end of path, not an error, and continue with the next path. |
| RUN-008 | MUST | Emit a heartbeat with the current script location. If the orchestrator sees no progress for `--timeout` seconds (default 60) it kills the game, reports a `hang` finding with the last known location and path, and continues with remaining work. |
| RUN-009 | MUST | Detect a path that keeps executing without reaching new statements (step budget per path, default configurable) and end it with a `loop` finding of severity *warning*. |
| RUN-010 | MUST | Seed the game's random number generator so that the same command on the same game produces the same paths and findings. The seed is configurable and recorded in the report. |
| RUN-011 | MUST | After an error on one path, continue testing other paths. One crash never ends the run. |
| RUN-012 | MUST | If the game process dies without the harness reporting why, report an `engine-crash` finding with the process exit code and the tail of the engine's log, then relaunch and continue with the branches that were waiting to be explored. The same applies after a hang (RUN-008). After 20 relaunches in one run, exploration stops and the report says how many branches were left. |
| RUN-025 | MUST | The engine's *safe mode* is switched off during a run. On Windows the engine enters it whenever the Shift key is down as the game starts, which someone typing in another program can cause, and then shows a screen for choosing a renderer in place of the game. |
| RUN-026 | MUST | The engine is started with a fixed hash seed, so that sets and dictionaries are ordered the same way on every run. Without it the engine's lint lists different unreachable statements from one run to the next. |
| RUN-023 | MUST | A project in development can reload itself when its script files change on disk. This is switched off during a run, because a reload restarts the game in the middle of a path. |
| RUN-013 | SHOULD | Typical performance: at least 500 dialogue statements per second per game process on a mid-range desktop. |
| RUN-014 | MUST | Explore several routes at the same time by running multiple game processes in parallel. `--jobs N` sets how many; the default is chosen from the number of CPU cores and available memory. `--jobs 1` is always supported. The story itself is explored by one process, because what exploration finds depends on the order it is done in (EXP-016, NFR-001); label runs, which do not depend on each other (EXP-019), are shared out between the other processes, and the engine's lint runs at the same time as both. The default is one process fewer than the computer has cores, at most 8, and no more than there is free memory for at 768 MB each. An extra process is not started for fewer than 8 labels. |
| RUN-015 | MUST | Parallel processes do not interfere with each other: each has its own save and persistent directory, its own event file and its own engine log. The engine's second copy of saves and persistent data, which it keeps in `game/saves`, is switched off for the run. |
| RUN-016 | MUST | Nothing in a run waits on real time: no rendering to a display, no frame-rate limit, no audio playback, no animation or transition delays (extends RUN-004). |

### 4.4 Route exploration (EXP)

Exhaustive path coverage is impossible (choices multiply), so the target is **statement coverage**: execute every reachable statement at least once, in a realistic game state.

| ID | Pri | Requirement |
| --- | --- | --- |
| EXP-001 | MUST | Explore branches so as to maximise statement coverage: at each decision point, prefer options that can lead to statements not yet executed. |
| EXP-016 | MUST | Each option of each decision point is explored at least once. Exploration does not try every combination of choices, so content that needs a particular combination of earlier choices (for example an ending that depends on a score) may not be reached; it then shows as not covered, and is left to label runs (EXP-007). |
| EXP-017 | MUST | When a path comes back to a decision point it has already passed, and none of that point's options is new, the last option not yet taken on this path is chosen: a hub menu's way out is conventionally listed last, and its other options are already being explored from snapshots. |
| EXP-018 | MUST | The game's main menu is not part of the story: when it appears during a run it is left at once, the way a player pressing *Start* would leave it, and its buttons are not explored. |
| EXP-002 | MUST | Reach deep branches without replaying the game from the start for every path (snapshot and restore of game state at decision points). |
| EXP-003 | MUST | Bound the work: `--max-paths` (default 5000), `--max-time` (default 600 seconds) and `--max-depth` (default 500 decisions on one path, after which the path is played to its end without branching), with defaults that finish a typical short game in minutes. When a limit stops exploration early, the report says so and gives the coverage reached. `--max-time` is for the whole stage, however many processes run and however often one is started again; `--max-paths` is for each process. |
| EXP-004 | MUST | Record for each finding the full path that led to it. |
| EXP-005 | MUST | Report coverage: statements executed / total, per file and per label, plus the list of labels never reached. The total counts only statements a playthrough could execute: init-time code, translation blocks, engine test cases and the implicit return at the end of each file are excluded. |
| EXP-006 | MUST | `--strategy first` plays a single path taking the first available choice everywhere. This is the fast smoke test. When the same decision point is reached again on that path, the next untried choice is taken, so that hub menus are walked through instead of looped; when every choice there has been tried, the path ends. |
| EXP-007 | MUST | The `labels` strategy starts execution at every label in isolation, to reach code that normal exploration cannot. It is on by default and runs alongside normal exploration in the same pool of game processes (RUN-014). `--no-labels` turns it off. `--strategy first` plays one path only and makes no label runs. |
| EXP-019 | MUST | A label run plays its own label and nothing else. It starts from the state the game has at the first statement of the story, explores each option of each decision it meets once (EXP-016), plays the labels it calls, and ends where the story moves on to a different label, by a jump or by running off the end into the next one. A label's local labels count as part of it. What was explored before a label run has no effect on it. |
| EXP-020 | MUST | Label runs start at every label in the game's own script except: the `start` label, which is where normal exploration begins; labels that need arguments, since there is nothing to call them with; and labels whose name starts with an underscore, which belong to the engine. |
| EXP-011 | MUST | Normal exploration has priority on the process pool; label runs use only spare capacity and never delay it. With a single game process, label runs start when normal exploration has finished. The limits of EXP-003 cover both together; when one stops the run, the report says how many labels were not played. |
| EXP-012 | MUST | When both strategies have finished, each finding from a label run is resolved against normal exploration: if normal exploration executed the same statement without error, the finding is dropped; if normal exploration reported the same problem, the two are merged into one confirmed finding (ERR-010); if normal exploration never executed that statement, the finding is kept as a *possible issue*. The same resolution applies to findings made after a skipped interaction (RUN-021). The report says how many findings were dropped. An engine crash or a hang during a label run is a possible issue too. |
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
| ERR-008 | SHOULD | Menu with no selectable choice in some reached state. A menu that uses a `set` is exempt: it runs out of choices by design. | error |
| ERR-012 | MUST | The game used something that only works with a real screen, such as the clipboard. This is a limit of testing with no window, not a fault in the game: the path ends there and the finding says so. | info |
| ERR-009 | COULD | Save and load round-trip fails at a point in the game (unpicklable state). | error |

Every finding MUST carry: a stable ID, class, severity, message, script file and line, enclosing label, the stage that found it, the language active at the time, the reproduction path, and the engine traceback where one exists.

**ERR-013 (MUST).** ERR-003, ERR-004 and ERR-005 are found while playing, not only by lint (ARCH-007).
Undefined images are found when a `show` or `scene` runs, and image, audio and movie files when the statement that uses them runs.
Text tags are checked in dialogue, speaker names, menu captions and choices, and the text of buttons on screens the tool interacts with.
These findings do not end the path, since the game itself would carry on.
Interpolation failures need no separate check: the engine raises on them, which is reported under ERR-002.

**ERR-010 (MUST).** The same underlying problem reached by many paths is reported once, with a count and the shortest reproduction path.

**ERR-011 (MUST).** Intentional errors are not reported: an exception the game's own script catches is not a finding.

### 4.6 Lint stage (LINT)

| ID | Pri | Requirement |
| --- | --- | --- |
| LINT-001 | MUST | Run the engine's built-in lint and convert its output into findings, with file and line where lint provides them. Each kind of lint message is mapped to a severity; lint's own exit code is not used, because it reports informational items such as unreachable statements as failures. |
| LINT-002 | MUST | Lint findings that duplicate a finding from another stage are merged with it (ERR-010). A lint error at the same file and line as an error found by playing is the same problem: the played finding is kept, because it has the path and the traceback, and lint's wording is attached to it. |
| LINT-004 | MUST | Lint is asked for everything it can report (all problems, unclosed text tags). An engine version that lacks one of these options is run without it, and the report says which checks were skipped (COMPAT-005). |
| LINT-005 | MUST | Unreachable statements and orphan translations reported by lint are findings of severity *info* (ERR-007, TL-007). A kind of lint message the tool does not recognise is a *warning*, never an error. |
| LINT-003 | SHOULD | Include lint's statistics (word count, dialogue blocks, per-language counts) in the report summary. |

### 4.7 Translation testing (TL)

| ID | Pri | Requirement |
| --- | --- | --- |
| TL-001 | MUST | Discover all languages the game defines. `--languages a,b` restricts the set; default is all. Naming a language the game does not have is a usage error (exit 2). A game with no translations finishes the stage with nothing to check. |
| TL-002 | MUST | For each language, switching to it succeeds: its `translate python` and `translate style` blocks execute without exception. The switch is made in a game process of its own that plays nothing, so that a language's set-up code cannot change what exploring the story finds. A failure is a `language-switch` finding of severity *error*, placed at the line of the translation file that failed. |
| TL-003 | MUST | For each language, every translated dialogue line and string is checked for malformed text tags (ERR-005). The finding is placed at the translation, not at the original line. A translation is not reported when its original reads as malformed too: such text is either not shown as game text (for example `"Page {}"`, which Python code fills in) or wrong in the original, where the other stages report it. |
| TL-004 | MUST | For each language, every translated line reached during route exploration is rendered with the real game state at that point, so that a bad `[variable]` reference in a translation is found. This is done for every language at once, as each line of dialogue or menu choice is played, by the same processes that play the story and the label runs; no route is played again for a language. A failure is a `bad-interpolation` finding of severity *error*, placed at the translation. It does not end the path, and it is a possible issue under the same rules as any other finding (EXP-012, RUN-021). A translation is not reported when the original line cannot be rendered either. A game that reads each language's script only when the player picks that language has every checked language loaded for the run. When the routes stage does not run, translations are not tried out, and the report says so (NFR-002). |
| TL-005 | MUST | Report untranslated dialogue lines and untranslated strings per language, with counts and locations. Severity *warning*; can be raised to *error* in the config file. A line of dialogue is untranslated when the language has no translation block for it, and a string when the language has no translation of it. The strings are those the engine's own scanner lists in the game's script files (menu choices, and text marked for translation in screens and Python); the engine's built-in interface texts are not counted. Each finding is placed at the original line. A game with no script source has only its dialogue and menu choices listed, and the report says so. The console lists the first ten findings for each language and says how many more are in the report. |
| TL-006 | MUST | Report differences between source and translation in the set of interpolated `[variables]` (a variable dropped, added or misspelt). Severity *warning*, placed at the translation. The variables are read by the engine's own text parser; conversion flags and formats (`[name!t]`, `[price:.2f]`) are not part of the comparison. When the same translation also fails as its line is played (TL-004), the difference is attached to that finding and not listed by itself (ERR-010). |
| TL-012 | MUST | For each language checked, the report says whether it could be switched to, and how many lines of dialogue and how many strings are translated, out of how many. The console summary shows the same, one line per language. |
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
| REP-003 | MUST | JUnit XML report, so CI systems show findings as failed tests. There is one test suite for each stage that was asked for and one test for each finding. A finding that makes the run fail (CLI-004, EXP-013) is a failed test; any other finding is a skipped test, which CI systems list with its message without failing the build. Each stage also has a test of its own, which is in error when the stage did not finish (NFR-002). Test and suite names are the same in every interface language (I18N-003). |
| REP-004 | MUST | Self-contained single-file HTML report (no internet needed to view it), written for the game developer and concise: a one-screen summary first (pass/fail, counts by severity, coverage, per-language translation status), then confirmed findings grouped by script file, then possible issues (EXP-013) in a separate section, each finding collapsed to one line that expands to show the reproduction path and traceback. Filter by severity, stage and language. |
| REP-005 | MUST | Reports are written to `--output DIR` (default `./renpytester-report/`), never inside the game directory. |
| REP-006 | MUST | Messages are written for game developers, not engine developers: say what is wrong and where in *their* script, with the raw traceback available but secondary. |
| REP-007 | SHOULD | `--baseline REPORT.json` reports only findings that are not in an earlier report, so a project with known issues can still gate on new ones. Findings are matched by their stable id. Those left out are counted in the summary of every output. A baseline that is not a RenPyTester JSON report is a usage error (exit 2), found before the game is started. |
| REP-010 | MUST | Every run writes the JSON, JUnit and HTML reports, under the same name (REP-009) with the extensions `.json`, `.xml` and `.html`. The JUnit and HTML reports are made from the data of the JSON report and nothing else, so the three always agree. |
| REP-009 | MUST | Report files are named after the game and the time of the run, `report-<game name>-<yyyy-mm-dd>-<hhmmss>`, with the extension of their format, so that reports of different games, and of successive runs of one game, never overwrite each other. The game name is reduced to lowercase letters, digits and hyphens. Engine logs for the run go in a folder of the same name ending in `-logs`. The console prints the full path. |
| REP-008 | MUST | The engine's own log, `traceback.txt` and `errors.txt` output from the run are preserved in the output directory. |

### 4.10 Command line (CLI)

| ID | Pri | Requirement |
| --- | --- | --- |
| CLI-001 | MUST | `renpytester GAME` runs all default stages (`lint`, `routes`, `translations`) with default settings. The `routes` stage includes label runs (EXP-007). |
| CLI-002 | MUST | `--stages a,b` selects stages. |
| CLI-003 | MUST | Exit codes: `0` no findings at or above the failure threshold; `1` findings at or above it; `2` bad usage or configuration; `3` the game could not be launched or the tool failed internally. |
| CLI-004 | MUST | `--fail-on error\|warning\|info\|never` sets the threshold (default `error`). |
| CLI-005 | MUST | `--help` documents every option with its default; `--version` prints the version. |
| CLI-006 | MUST | Ctrl+C stops the game, cleans up (SAFE-002), and still writes a partial report marked incomplete. The report is written in every format, has what was found until then, and gives each stage that had not finished the status `interrupted`. The exit code is 3, as for any run that is not complete. |
| CLI-007 | MUST | Launched with no arguments (for example by double-click), the executable opens the graphical interface (4.14). Dragging a game folder onto the executable opens the graphical interface with that game already selected. `renpytester gui [GAME]` does the same from a terminal. `renpytester gui` takes `--lang`. A dropped folder is told from a game named in a terminal by where the program was started: the folder is the only argument, and the program has a console window to itself, which is what Windows gives a program started by a double click or a drop. Anything typed into a terminal with a game after it is a run in the terminal (CLI-001). How this works for a packaged executable is settled with M8. |
| CLI-008 | SHOULD | `renpytester info GAME` prints what GAME-006 detects and exits, without running the game's story. It writes no report. When the game cannot start, it says why and exits with code 1. |
| CLI-009 | — | *Withdrawn in 0.2.* Replaced by section 4.14. |
| CLI-010 | MUST | `--lang en\|pt-BR` selects the interface language (4.15). |
| CLI-011 | MUST | Run settings that requirements call configurable are available as options: `--seed` (RUN-010), `--timeout` (RUN-008), `--max-steps` (RUN-009), `--input-value` (RUN-005), `--show-window` (GAME-007), `--output` (REP-005), `--languages` (TL-001), `--config` (CFG-002), `--baseline` (REP-007), `--sandbox` (SAFE-006), `--sandbox-verify` (SAFE-011). |

### 4.11 Configuration (CFG)

| ID | Pri | Requirement |
| --- | --- | --- |
| CFG-001 | MUST | Zero configuration is a supported mode: every setting has a default. |
| CFG-002 | MUST | Optional `renpytester.toml`, looked for in the game directory, or given by `--config`. Command-line options override the file. A file given by `--config` is used in place of the one in the game directory, not on top of it. Run settings have the names of their command-line options, with underscores (`max_paths = 100`); `--no-labels` is `labels = false`. A file or folder named in the file (`sdk`, `output`, `baseline`) is relative to the file. |
| CFG-003 | MUST | Ignore rules: suppress findings by class, file glob, label, language, or message pattern. Suppressed findings are counted in the summary, never silently dropped. Each rule is an `[[ignore]]` table, and a finding is ignored when it matches every part the rule has. `file` and `label` are glob patterns. `message` is a regular expression looked for in the finding's message; it is tried on the message in each interface language, so that a rule keeps working whatever language the tool is run in. The JSON report says how many findings each rule left out. |
| CFG-004 | MUST | Unknown keys in the config file are an error (exit 2), not ignored. So are a value of the wrong kind and a file that is not valid TOML. The message names the file and the key, and nothing is started. |
| CFG-005 | SHOULD | Per-prompt input values, and initial values for chosen game variables, so games that gate content on input can be explored. The `[inputs]` table gives the exact text of a prompt the text to type there; other prompts get the usual value (RUN-005). The `[variables]` table gives variables their values at the first statement of the story, after the game's own defaults, for the story and for every label run. What is found in a state set this way is an ordinary finding, not a possible issue: the developer chose that state. |
| CFG-006 | SHOULD | Mark labels as excluded from exploration (e.g. a minigame that cannot be automated). `exclude_labels` is a list of glob patterns. An excluded label is never played: no label run starts at it, and reaching it acts as an immediate `return`, so a call to it carries on after the call and a jump to it ends the story there. Its statements are left out of the coverage total, and the report lists the labels that were excluded. |
| CFG-007 | MUST | The `[severity]` table gives a class of finding the severity the developer wants (for example `untranslated = "error"`, TL-005). It applies to every finding of that class, before ignore rules, the baseline and the failure threshold. |

### 4.12 Compatibility (COMPAT)

| ID | Pri | Requirement |
| --- | --- | --- |
| COMPAT-001 | MUST | Host platforms: Windows 10+ x64, Linux x64, macOS (Intel and Apple Silicon). |
| COMPAT-002 | MUST | Ren'Py 8.x games (Python 3 engines). |
| COMPAT-003 | — | *Withdrawn in 0.2.* Ren'Py 6.99 support. |
| COMPAT-004 | MUST | A game on Ren'Py 7 or older is detected before anything is launched or injected, and refused with a clear message that Python 2 engines are not supported (exit 3). An unrecognised newer engine version produces a warning and a best-effort run, not a crash. |
| COMPAT-005 | MUST | When a check cannot be performed on a given engine version, the report lists it as *skipped* with the reason. A skipped check is never shown as passed. |
| COMPAT-006 | MUST | Orchestrator runs on Python 3.11 and later. |
| COMPAT-007 | MUST | The graphical interface works wherever the orchestrator does. When run from source on a Python without `tkinter` (some Linux distributions package it separately), the tool says which package to install and the command line remains fully usable. The same message is given when there is no display to open a window on. Tk is loaded only when a window is opened. |

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
| GUI-001 | MUST | Choose the game by browsing for a folder or dropping one on the executable. Once chosen, show what was detected (GAME-006): name, engine version, languages. The game's path can also be typed or pasted. Finding out what the game is runs in the background, as `renpytester info` does it (CLI-008); when the game cannot be started, the window says why. |
| GUI-002 | MUST | Options shown as plain controls with sensible defaults: stages to run, languages to test, sandbox copy on/off (SAFE-006), and an optional SDK folder when the game needs one. Everything else stays at its default or comes from `renpytester.toml`. The SDK control is shown only for a game that has no engine of its own, and starts with the folder the `RENPY_SDK` environment variable names, if any. There is one box for each language the game has, all ticked at first. *Run* is not available while nothing is ticked to check, or translations are ticked with no language. All of these but the SDK folder are among the advanced settings (GUI-016). |
| GUI-003 | MUST | A *Run* button that becomes *Cancel* during a run. Cancelling behaves as Ctrl+C does (CLI-006). Closing the window during a run cancels the run first, and the window closes when the game folder has been restored. |
| GUI-004 | MUST | During a run: one progress bar, the current stage, and running counts of errors and warnings. No game window appears (ARCH-006). The interface stays responsive. The bar shows how much of the script has been played; until the game reports in, it shows only that work is going on. The controls cannot be changed during a run. Notes and possible issues are counted too. |
| GUI-005 | MUST | After a run: a pass/fail result, counts by severity, and a button that opens the HTML report in the default browser. A second button opens the folder the reports are in. |
| GUI-006 | MUST | Problems that stop a run (no engine found, unsupported engine, game already being tested) are shown as a readable message in the window, not as a traceback or a silent exit. This goes for a config file with a mistake in it (CFG-004), and for a failure of RenPyTester itself, which is shown as that (NFR-004). |
| GUI-007 | MUST | Every GUI run can be expressed as a command line; the window shows that command so a developer can copy it into CI. The command has only what differs from the defaults, quoted for the user's own terminal, and the window's language as `--lang`. Given to the command line, it makes a run with the same settings. |
| GUI-008 | SHOULD | Remember the last game folder and options between sessions. Also the SDK folder and the window's language. They are kept in a file in the user's profile, which the `RENPYTESTER_GUI_STATE` environment variable can move. |
| GUI-009 | SHOULD | List the findings in the window itself, with file and line, without opening the report. |
| GUI-010 | SHOULD | Manage cached sandbox copies (SAFE-012). A dialog lists the copies with their size and when they were last used, and deletes the selected ones or all of them. The button that opens it is among the advanced settings, under the sandbox option, since the copies concern only someone who has used the sandbox. |
| GUI-011 | MUST | A run started from the window saves its reports in a folder named `renpytester-report` in the user's home folder, unless the game's config file names another (CFG-002) or the user chooses one. The folder can be typed or browsed for among the advanced settings (GUI-016); the box shows the folder that will be used even when none was chosen, and the choice is remembered (GUI-008). The window also says where the reports are saved, and the command it shows has that folder as `--output`. The command line's default, a folder beside wherever the command was typed (REP-005), means nothing to someone who started the program with a double click. |
| GUI-012 | MUST | The window's language selector shows each interface language by its name (*English*, *Brazilian Portuguese*), not by its code, and the names themselves follow the language the window is in. The name of every language is in every message file, so that adding a language still needs no change to the code (I18N-008). |
| GUI-013 | MUST | The program has an icon of its own, original artwork, which the window, its dialogs and the taskbar or dock entry show in place of Python's. The icon files are part of the package, and are made by a development tool from a drawing in code, so that they can be made again. A window that cannot load the icon opens without it. |
| GUI-014 | MUST | An *About* button opens a dialog with the program's name, icon and version, a credit to its author, CyBearNairus, its licence, and the address of its GitHub repository, which opens in the default browser when clicked. Nothing is fetched from the network unless the user clicks that link (SAFE-008). |
| GUI-015 | MUST | The window looks like the HTML report (REP-004): the same colours, panels with a thin edge on a quieter background, the sums of errors, warnings, notes and possible issues as large coloured numbers, and each listed finding marked with the colour of its kind. The colours are kept in one place that both use. The window is dark when the system is set to dark, and light otherwise, as the report is in a browser. *Run* is the one coloured button. On a screen set to show things larger, the window is drawn sharp at that size. All of this is done with Tk's own styles and small pictures drawn by the program: no library is added (ARCH-005). |
| GUI-016 | MUST | The window opens showing only what a first run needs: the game's folder and *Run*. What to check, which languages, the sandbox, the report folder and the equivalent command are *advanced settings*, shown and hidden by one button, and they apply whether shown or not. Whether they are shown is remembered (GUI-008). The SDK folder is not among them: a game with no engine cannot be tested without one, so it is asked for in plain sight, and only for such a game. They are in this order: the game's languages, first because they are the one setting that differs from game to game; what to check; the sandbox, under the label *Sandbox*; the report folder; and the command. |
| GUI-017 | MUST | A dialog (*About*, the sandbox's copies) opens over the middle of the main window, and appears once, complete: it is built out of sight and shown when ready, so that no empty frame flashes in a corner of the screen first. |

### 4.15 Interface languages (I18N)

| ID | Pri | Requirement |
| --- | --- | --- |
| I18N-001 | MUST | The console output, the graphical interface, the HTML report and all finding messages are available in English (`en`) and Brazilian Portuguese (`pt-BR`). |
| I18N-002 | MUST | The language is taken from the operating system's locale, falling back to English; `--lang` or the config file (`lang`) overrides it, and `--lang` wins over the file; the GUI has a language selector. |
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
| NFR-001 | MUST | **Determinism.** Same tool version, game, engine, settings and seed give the same findings and coverage, whatever the value of `--jobs`, for any run that finishes without hitting a limit (EXP-003). A run cut short by `--max-time` may differ between machines and says so in the report. Findings are put into the report in a fixed order (the story's, then each label's in script order), not in the order processes reported them. |
| NFR-002 | MUST | **No false passes.** If a stage could not run or did not finish, the run does not exit 0 claiming success; the report states what was not checked. |
| NFR-003 | MUST | **Low false positives.** On the reference games (7.1), which are known to work, a default run reports zero findings of severity *error*. |
| NFR-004 | MUST | **Robustness.** A bug in the harness is reported as a tool error (exit 3, "this is a RenPyTester bug"), never as a problem in the user's game. |
| NFR-005 | SHOULD | **Speed.** A default run on a 50,000-word game completes in under 5 minutes on a 4-core desktop. |
| NFR-007 | MUST | **Unobtrusive.** During a default run the user can keep working on the same machine: nothing appears on screen except the tool's own progress display, no sound plays, and focus is never taken (ARCH-006). |
| NFR-008 | MUST | **Documentation lint.** Every Markdown file in the repository passes `markdownlint` using the configuration in `.markdownlint.json`. This is checked in CI and a failure blocks the merge. Rules are changed in that file, never silenced inline without a comment giving the reason. |
| NFR-009 | MUST | **Code lint.** Every script in the repository passes its linter with no problems reported: Python files pass `flake8` with the configuration in `.flake8` (line length 120); Ren'Py script files pass `tools/lint_rpy.py`, which enforces Ren'Py layout rules (spaces only, indentation in multiples of four, line length 120) and runs `flake8` on the Python inside them. This covers product code, tests, tools and spikes alike, is checked in CI, and a failure blocks the merge. |
| NFR-006 | MUST | **Licence hygiene.** No game content or engine code is committed to this repository or bundled in releases. RenPyTester is GPL-3.0. |

---

## 6. Planned structure

Indicative, not binding.
Settled in the design step of milestone M1.

```text
renpytester/                orchestrator (Python 3.11+, stdlib only)
    cli, discovery, workspace, launcher, runner, model, i18n, report/, locale/
renpytester/harness/        files injected into the game (engine's Python 3, Ren'Py API)
tools/                      development tools (linters)
tests/unit/                 orchestrator logic, no engine needed
tests/e2e/                  real engine against fixture games
tests/fixtures/games/       tiny purpose-built games, one seeded bug each
docs/SPEC.md                this file
docs/report-schema.md       JSON report schema (REP-002)
```

The package sits at the repository root, not under `src/`, so that `python -m renpytester` works from a clone with no install step (DIST-001).
The M0 spikes settled where the exploration logic lives: in the harness (ARCH-008).

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
| M0 | Feasibility spikes (**done** 2026-10-06) | Throwaway experiments answering the assumptions in 9.1, on the oldest and newest Ren'Py 8.x. Results in [SPIKES.md](SPIKES.md). | — |
| M1 | Walking skeleton (**done** 2026-10-06) | Discover, launch invisibly, inject, clean up, play one path (`--strategy first`), catch exceptions, console + JSON report. Message catalogue in both languages from the first message onward. | GAME-001–007, I18N-001–006, SAFE-001–005, RUN-001–005, -007, -008, -011, EXP-006, ERR-001, -002, REP-001, -002, CLI-001, -003 |
| M2 | Lint (**done** 2026-10-06) | Lint stage and finding merge. | LINT, ERR-010 |
| M3a | Exploration (**done** 2026-10-06) | Branching with snapshots inside the game process, limits, coverage per file and label, continuing after crashes and hangs. | EXP-001–005, -016–018, RUN-006, -009–012, -023, ERR-006 |
| M3b | Checks that need no rendering (**done** 2026-10-06) | Missing files, undefined images and malformed text found while playing, not only by lint. | ERR-003–005, -008, -012, -013 |
| M3c | Getting past minigames (**done** 2026-10-06) | Skipping unplayable interactions and continuing with inferred outcomes. | RUN-017, -019–021, -024, EXP-012–014 (the parts that concern skipped interactions) |
| M3d | Label runs (**done** 2026-10-06) | Starting at every label, and resolving those findings against normal exploration. | EXP-007, -011–015, -019, -020 |
| M3e | Parallel processes (**done** 2026-10-06) | Several game processes exploring at once. | RUN-014–016, -025, -026 |
| M4 | Translations (**done** 2026-10-06) | Language discovery and all TL MUSTs. The SHOULD and COULD rows of 4.7 are left for later, except orphan translations (TL-007), which lint already reports. | TL-001–006, -012 |
| M5 | Reports and config (**done** 2026-10-06) | JUnit, HTML, config file, ignore rules, baseline, the partial report after Ctrl+C and the `info` command. The two SHOULD rows that add more to the config file, stated outcomes of interactions (RUN-022) and user-authored paths (EXP-009), are left for later. | REP-003, -004, -007, -010, CFG-001–007, CLI-005, -006, -008 |
| M6 | Sandbox (**done** 2026-10-06) | Cached copy with incremental synchronisation, cache commands, and the report of files a game writes by itself. The GUI's part of SAFE-012 comes with M7. | SAFE-006, -007, -009–012 |
| M7 | Graphical interface (**done** 2026-10-06) | The window described in 4.14. | GUI-001–017, CLI-007, COMPAT-007 |
| M8 | Packaging | Single-file executables, release CI. | DIST |
| M9 | Hardening | Screen smoke test, performance, acceptance. | UI, NFR, 7.4 |

---

## 9. Open items

### 9.1 Technical assumptions

The fourteen assumptions listed here in version 0.3 were tested in milestone M0.
The results, evidence and measurements are in [SPIKES.md](SPIKES.md).

Parallel processes in sandbox mode, when the game writes to its own directory, were settled in M6 by a decision and not by a measurement.
All processes share the one copy, as they share the game folder in place, and the report says what that can mean (SAFE-007).

Still unverified, and the requirements that depend on them:

1. Invisible operation on Linux and macOS (GAME-007). Confirmed on Windows only.
2. Querying a font's glyph coverage from inside the engine (TL-008).
3. Dropping a folder onto the open window with the standard library alone (GUI-001 has a fallback).

### 9.2 Decisions

Open:

| # | Question | Recommendation |
| --- | --- | --- |
| D21 | Approve the version 0.17 amendments: GUI-011 added; GUI-001 to GUI-008, GUI-010, CLI-007 and COMPAT-007 made precise. In particular: `renpytester` with nothing after it now opens the window, where it used to print a usage message; and reports of runs started from the window go to the user's home folder. | Approve. |

Settled on 2026-10-06:

| # | Decision |
| --- | --- |
| D25 | Asked for by the owner: among the advanced settings the languages come first, the sandbox has a label, and the button for its copies sits under it (GUI-016, GUI-010). The SDK folder stays in plain sight for a game that needs one. |
| D24 | Asked for by the owner: the window shows only the game at first, with the other choices behind *Show advanced settings* (GUI-016); the report folder can be chosen (GUI-011); and dialogs open centred, without a flash (GUI-017). |
| D23 | Asked for by the owner: the window is to look modern, like the HTML report (GUI-015). The licence stays GPL-3.0. |
| D22 | Asked for by the owner: the window's language selector shows names, not codes (GUI-012); the program has an icon (GUI-013); and an *About* dialog gives the version, credits CyBearNairus and links to the repository (GUI-014). |
| D20 | Version 0.16 amendments approved: SAFE-006, SAFE-007 and SAFE-009 to SAFE-012 made precise. Several game processes share the one sandbox copy, and a game writing its own files is a note, not a finding. |
| D19 | Version 0.15 amendments approved: REP-010 and CFG-007 added; REP-003, REP-007, CFG-002 to CFG-006, CLI-006, CLI-008 and I18N-002 made precise. |
| D18 | Version 0.14 amendments approved: TL-012 added; TL-001 to TL-006 made precise. |
| D17 | Version 0.13 amendments approved: RUN-025 and RUN-026 added; RUN-014, RUN-015, EXP-003 and NFR-001 made precise. Only label runs and lint are spread over several processes; the story is explored by one. |
| D1 | Test in place by default. Sandbox copy is opt-in (flag and GUI checkbox), cached between runs and synchronised incrementally (SAFE-006, -009 to -012). |
| D2 | A graphical interface is required for 1.0 (4.14). |
| D3 | Python 2 engines (Ren'Py 7 and older) are out of scope for now. Doki Doki Literature Club is dropped as a reference game. |
| D4 | Untranslated lines are warnings. |
| D5 | Label runs are on by default, run alongside normal exploration, and their findings are filtered against it and reported separately as possible issues (EXP-007, -011 to -015). |
| D9 | Version 0.5 amendments approved (the owner approved and committed M1). |
| D16 | Version 0.12 amendments approved: EXP-019 and EXP-020 added; EXP-007, EXP-011 and EXP-012 made precise. |
| D15 | Version 0.11 amendments approved: RUN-024 added, RUN-020 made precise. |
| D14 | Version 0.10 amendments approved: checks made while playing (ERR-012, ERR-013, ERR-008). |
| D13 | Version 0.9 amendments approved: exploration rules (EXP-016 to EXP-018), RUN-023, and milestone M3 split into five parts. |
| D12 | Version 0.8 amendments approved: lint rules made precise and reports named after the game and run time (LINT-002, -004, -005, REP-009). |
| D11 | Version 0.7 amendments approved: minigames are skipped and the story continues with inferred outcomes (RUN-017, RUN-019 to RUN-022). |
| D10 | Error files must not open in a text editor during a run (GAME-010), requested by the owner after seeing it happen during development. |
| D8 | Version 0.4 amendments approved (the owner committed M0 and asked for M1). |
| D6 | The HTML report is required for 1.0 and must be concise (REP-004). |
| D7 | Command name `renpytester`. Interface in English and Brazilian Portuguese (4.15). |

---

## 10. Change log

| Date | Version | Change |
| --- | --- | --- |
| 2026-10-06 | 0.1 | First draft. |
| 2026-10-06 | 0.2 | Owner decisions D1–D4, D6, D7. Dropped Python 2 engines and DDLC (COMPAT-003 withdrawn). Cached incremental sandbox (SAFE-009 to -012). GUI required (4.14, CLI-009 withdrawn). Interface languages en and pt-BR (4.15). HTML report now MUST. Invisible operation now MUST (ARCH-006, GAME-007, NFR-007). Parallel exploration (RUN-014 to -016). |
| 2026-10-06 | 0.3 | D5 settled: label runs on by default alongside normal exploration, resolved and reported as possible issues (EXP-007 now MUST, EXP-011 to -015 added). Markdown lint requirement (NFR-008); tables reformatted to pass it. |
| 2026-10-06 | 0.4 | M0 spike results. Added ARCH-007, ARCH-008, SAFE-013, SAFE-014, RUN-017, NFR-009 (code lint). Reworded SAFE-001. Clarified EXP-005 and LINT-001. Section 9.1 replaced by a pointer to SPIKES.md and the four assumptions still unverified. |
| 2026-10-06 | 0.5 | M1 built. EXP-006 clarified. Added RUN-018 and CLI-011. Planned structure updated to the package at the repository root. D8 settled. |
| 2026-10-06 | 0.6 | D9 settled (0.5 approved). Added GAME-010: the engine must not open error files in a text editor. |
| 2026-10-06 | 0.7 | Minigames and other unplayable interactions are skipped and the story continues with inferred outcomes (RUN-017 reworded, RUN-019 to RUN-022). |
| 2026-10-06 | 0.8 | M2 built. D11 settled (0.7 approved). LINT-002 made precise; added LINT-004 and LINT-005. `--stages` (CLI-002) delivered early, in M2. Added REP-009: reports named after the game and the time of the run. |
| 2026-10-06 | 0.9 | First part of M3 built. D12 settled (0.8 approved). Added EXP-016 to EXP-018 and RUN-023; made RUN-012 and EXP-003 precise; split M3 into M3a to M3e. |
| 2026-10-06 | 0.10 | M3b built. D13 settled (0.9 approved). Added ERR-012 and ERR-013; ERR-008 exempts menus that use a set. |
| 2026-10-06 | 0.11 | M3c built. D14 settled (0.10 approved). Added RUN-024; RUN-020 made precise. Possible issues and low-confidence coverage (EXP-012 to EXP-014) built for skipped interactions; label runs will reuse them. |
| 2026-10-06 | 0.12 | M3d built. D15 settled (0.11 approved). Added EXP-019 (what a label run plays) and EXP-020 (which labels are started at); EXP-007, EXP-011 and EXP-012 made precise. |
| 2026-10-06 | 0.13 | M3e built. D16 settled (0.12 approved). Added RUN-025 (no safe mode) and RUN-026 (fixed hash seed); RUN-014, RUN-015, EXP-003 and NFR-001 made precise. |
| 2026-10-06 | 0.14 | M4 built. D17 settled (0.13 approved). Added TL-012 (summary for each language); TL-001 to TL-006 made precise; `--languages` added to CLI-011. |
| 2026-10-06 | 0.15 | M5 built. D18 settled (0.14 approved). Added REP-010 (all three formats, from the same data) and CFG-007 (severity of a class); REP-003, REP-007, CFG-002 to CFG-006, CLI-006, CLI-008 and I18N-002 made precise; `--config` and `--baseline` added to CLI-011. |
| 2026-10-06 | 0.16 | M6 built. D19 settled (0.15 approved). SAFE-006, SAFE-007 and SAFE-009 to SAFE-012 made precise; `--sandbox` and `--sandbox-verify` added to CLI-011; the assumption about parallel processes in a sandbox settled by decision (9.1). |
| 2026-10-06 | 0.17 | M7 built. D20 settled (0.16 approved). Added GUI-011 (where the window saves reports); GUI-001 to GUI-008, GUI-010, CLI-007 and COMPAT-007 made precise. |
| 2026-10-06 | 0.18 | Owner's requests (D22): added GUI-012 (languages shown by name), GUI-013 (the program's icon) and GUI-014 (the *About* dialog). |
| 2026-10-06 | 0.19 | Owner's request (D23): added GUI-015 (the window looks like the HTML report, light or dark); GUI-004 counts notes and possible issues too. |
| 2026-10-06 | 0.20 | Owner's requests (D24): added GUI-016 (advanced settings behind a button) and GUI-017 (dialogs centred, shown once); GUI-011 lets the report folder be chosen; GUI-002 follows. |
| 2026-10-06 | 0.21 | Owner's requests (D25): GUI-016 gives the order of the advanced settings, languages first; GUI-010 puts the button for the sandbox's copies under the sandbox option. |
