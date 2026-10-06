# M0 feasibility spike results

Run on 2026-10-06 on Windows 11 against Ren'Py 8.6.0 (Python 3.12.7) and Ren'Py 8.0.3 (Python 3.9.10).
The spike scripts are in `spikes/` and are throwaway code.
Run one with `python spikes/run.py SPIKE.rpy [--game tutorial] [--sdk 8.0.3]`.

Each row answers one assumption from section 9.1 of [SPEC.md](SPEC.md).

## Results

| # | Assumption | Result | Evidence |
| --- | --- | --- | --- |
| 1 | A loose `.rpy` in `game/` is loaded by a built distribution with archived scripts | **Confirmed** | Built The Question with all scripts in `scripts.rpa`, added the spike file, explored 3 paths, 121 of 121 statements. |
| 2 | A built distribution can run `lint` from its bundled engine | **Confirmed** | `python.exe the_question.py <dir> lint <file> --error-code` wrote a report. Lint also has `--no-orphan-tl`, `--check-unclosed-tags` and `--all-problems`. |
| 3 | Saves and persistent data can be redirected | **Confirmed, with a catch** | `--savedir DIR` works. The engine still creates an empty `game/saves` folder. |
| 4 | Uncaught exceptions can be intercepted before the error screen | **Confirmed** | Replacing `renpy.execution.Context.handle_exception` receives every statement-level exception with file and line. |
| 5 | Game state can be snapshotted and restored in memory | **Confirmed** | `renpy.game.log.freeze` plus `renpy.loadsave.dump` to a byte buffer, restored with `loads` and `log.unfreeze`. 58 KB and about 3 ms per snapshot on The Question, 267 KB on the Tutorial. |
| 6 | The engine runs with no window, audio or focus stealing | **Confirmed on Windows only** | `SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`, `RENPY_RENDERER=sw`, `RENPY_PERFORMANCE_TEST=0`. No window is created at all. Linux and macOS are untested. |
| 7 | Clickable elements of a screen can be enumerated | **Confirmed** | After `ScreenDisplayable.update()`, `visit_all` finds `Button` objects; `renpy.run(button.action)` returns the value the screen would return. The Tutorial's chapter-select screen was driven this way. |
| 8 | Translations can be read for another language without switching to it | **Confirmed** | `translator.language_translates[(identifier, language)]` and `translator.strings[language]`. All 8 Tutorial languages read in one pass, about 820 of 825 dialogue lines each. |
| 9 | How much lint already covers | **Partly answered** | Lint reports orphan translations and, with a flag, unclosed tags. `renpy.check_text_tags` does not report an unclosed tag. Lint exits 1 on The Question because of "unreachable statements" in its test cases, so lint output cannot be mapped straight to errors. |
| 10 | Font glyph coverage can be queried | **Not tested** | |
| 11 | Several processes can share one game folder | **Confirmed** | 4 simultaneous processes on the Tutorial, all exit 0, identical results in all four. |
| 12 | Parallel processes in sandbox mode when the game writes to its folder | **Not tested** | Design question for M6. |
| 13 | Oldest Ren'Py 8.x worth supporting | **8.0.3 works** | Embeds Python 3.9.10. Exploration ran unchanged. Two API differences were hit: `sys.exception()` does not exist before Python 3.11, and `script.initcode` holds functions as well as nodes. |
| 14 | `tkinter` accepts a dropped folder with the standard library alone | **Not tested** | Believed not possible without an extension; GUI-001 already allows for that. |

## Measurements

| Game | Paths | Interactions | Statement coverage | Time inside the engine | Whole process |
| --- | --- | --- | --- | --- | --- |
| The Question, 8.6.0 | 3 | 112 | 121 of 121 | 0.08 s | 2.2 s |
| The Question, 8.0.3 | 3 | 112 | 190 of 191 | 0.11 s | about 3 s |
| Tutorial, 8.6.0 | 65 | 13,114 | 1,536 of 1,574 (97.6%) | about 24 s | 25.7 s |

Engine start-up costs between 0.3 and 1.7 seconds per process, so many paths per process is the right shape, and a restart per path is not.
The Tutorial number is from a naive explorer that writes an event per decision and re-walks long menu loops; it is a floor, not a target.

## What the spikes changed in the design

1. **The driver replaces the engine's interaction layer.**
   Replacing `renpy.display.core.Interface.interact` means nothing is rendered and nothing waits.
   This is what makes the speed possible, and it is also why problems that only appear when a frame is drawn are not seen for free.
   Missing image files, text tag errors and screen errors must be checked on purpose by the harness.
2. **Exploration belongs inside the harness.**
   Snapshots are in memory and restore in milliseconds, so one process explores many paths.
   The orchestrator supervises processes and shares work between them.
3. **A decision is a menu choice or a screen button, handled by the same code.**
   A menu or screen revisited on the same path takes the next untried option, which walks hub-style menus in one path.
4. **The kind of interaction must be captured at `renpy.ui.interact`.**
   Transitions call `Interface.interact` directly and leave a stale type behind; the spike mistook a transition for a screen because of it.
5. **`renpy.input` needs its own handler.**
   The spike returned `True` for every interaction, which produced 62 false errors in the Tutorial at the first text prompt.
6. **A custom engine command gives a second, display-free mode.**
   `renpy.arguments.register_command` from an injected script runs after init with no display and with every translation file loaded.
   Games that defer translation loading (`config.defer_tl_scripts`, used by the Tutorial) expose no translations in a normal run until the language is changed, so the static translation checks run through a command.
7. **The engine itself writes into the game folder.**
   In place, a run rewrote `game/cache/bytecode-*.rpyb` and `game/cache/screens.rpyb`, created `game/saves/`, compiled the injected script to `.rpyc`, and wrote `log.txt` and `traceback.txt` beside the game.
   It also copies scripts to a backup folder in the user's profile.
   `RENPY_LOG_BASE` moves the logs and `RENPY_DISABLE_BACKUPS` stops the backup.
   The cache files and the `saves` folder have to be restored or removed by the orchestrator.
8. **Useful engine switches found:** `RENPY_SKIP_MAIN_MENU`, `RENPY_SKIP_SPLASHSCREEN`, `RENPY_PERFORMANCE_TEST=0`, `RENPY_LOG_BASE`, `--savedir`.
   Found later, while building M1: `RENPY_SIMPLE_EXCEPTIONS` stops the interactive error screen, and `RENPY_EDIT_PY` replaces the editor.
   Without the second one, a failing game run with the `run` command opens `traceback.txt` or `errors.txt` in the system text editor, which is Notepad on Windows.
9. **Coverage needs a definition of "statement".**
   Init-time code, other languages' translation blocks, test cases and the implicit `return` at the end of each file must be left out of the total.
10. **Minigames end a path as "stuck".**
    The Tutorial's Pong example has no buttons to press; the 38 statements after it are the whole of the uncovered remainder.
11. **A saved state is restored to the last hard checkpoint, then replayed forward.**
    Found while building M3d: `log.unfreeze` rolls back greedily past soft checkpoints, so a snapshot taken in a statement goes back to the statement after the last interaction.
    A label run jumps away from the story's first statement by the harness's own doing, so it marks a hard checkpoint there; without it, restoring a snapshot taken inside the label landed back at the story's start.
12. **On Windows, Shift held down while the engine starts puts it in safe mode.**
    Found while building M3e, from the kept logs of a test that failed once: `get_safe_mode` reads the real keyboard, even with no window.
    The engine then shows its renderer screen in place of the game, and the harness explored that screen's 15 buttons and found nothing of the story.
    Setting `safe_mode_checked` on the engine's top module before the interface is created stops it.
    This was the cause of the intermittent failure first seen in M3a.
13. **The engine keeps a second copy of saves and persistent data in `game/saves`**, whatever `--savedir` says.
    Several processes writing it at once crashed one of them with a missing file as the game ended.
    The save locations are a list on `renpy.loadsave.location`; the engine rebuilds it after init code on 8.6, so `renpy.savelocation.init` is wrapped.
14. **The engine's lint depends on the order of sets.**
    Its list of unreachable statements differed between runs of the same script until `PYTHONHASHSEED` was fixed.
