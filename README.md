# RenPyTester

Test all routes on a RenPy game to ensure it's working properly.

RenPyTester plays through a Ren'Py game by itself, with no window on screen, and reports crashes and script errors with the file and line where they happened.
It also runs Ren'Py's own lint, so problems in scenes the playthrough did not reach, such as a missing image or a jump to a label that does not exist, are reported too.
It works on any Ren'Py 8 game, built or in development, and leaves the game folder exactly as it found it.

It tries every choice of every menu, and tells you how much of the script it played and which labels it never reached.

If the game has translations, each language is checked too.
You are told which lines of dialogue and which other texts have no translation yet, with the file and line of each.
You are also told about translations with a broken text tag, translations that show different `[variables]` from the original, and languages the game cannot be switched to.
As the story is played, every translation of each line is tried out in the state the game is really in, so a translation that uses a variable the game does not have is found without playing the game again in each language.

This is an early version.

## Getting it

The simplest way is the single program on the [releases page](https://github.com/CyBearNairus/RenPyTester/releases/latest): `renpytester-windows-x64.exe` for Windows.
It needs no Python and no installation.
Double-click it to open the window, or drop a game's folder on it to open the window with that game chosen.
In a terminal it takes everything described below: write its name where the examples say `python -m renpytester`.
The first time, Windows may warn that the program is from an unknown publisher, because it is not signed; choose *More info*, then *Run anyway*.

When they could be built, the same page has programs for Linux (`renpytester-linux-x64`) and macOS (`renpytester-macos-arm64` for Apple Silicon, `renpytester-macos-x64` for Intel).
After downloading one of those, allow it to run with `chmod +x`.

To run from the source instead, you need Python 3.11 or later and a copy of this repository.
Nothing else has to be installed.
`pipx install .` or `uv tool install .` in that copy gives you a `renpytester` command.

## Usage

### In a window

```text
python -m renpytester
```

A window opens.
Choose the game's folder and press *Run*.
*Show advanced settings* lets you choose what is checked, which languages, whether to test a copy of the game, and where the reports are saved.
The window shows the progress, then whether the game passed, the problems found with their file and line, and a button that opens the full report.
*Cancel* stops a run and puts the game folder back as it was.
The window also shows the command that makes the same run from a terminal, to copy into a script or a build server.
Its reports are saved in a folder named `renpytester-report` in your home folder, unless you choose another among the advanced settings.

`python -m renpytester gui PATH_TO_GAME` opens the window with that game already chosen.
On some Linux systems Python comes without the part that draws windows; RenPyTester then tells you which package to install, and everything below still works.

### In a terminal

```text
python -m renpytester PATH_TO_GAME
```

`PATH_TO_GAME` is the game's folder, or any file inside it.
A game that ships its own engine needs nothing more.
For a project that lives in the Ren'Py launcher's projects folder, add the SDK:

```text
python -m renpytester PATH_TO_GAME --sdk PATH_TO_RENPY_SDK
```

The result is printed and also saved in the `renpytester-report` folder, in files named after the game and the time of the run, such as `report-the-question-2026-10-06-143005.html`.
Earlier reports are never overwritten.
Three files are written each time:

- `.html`: the report to read. Open it in any browser; it needs no internet connection.
- `.json`: everything the run found, for other programs. Its format is described in [docs/report-schema.md](docs/report-schema.md).
- `.xml`: a JUnit report, which CI systems show as test results.

The exit code is 0 when no errors were found, 1 when errors were found, 2 when an option or the settings file is wrong, and 3 when the game could not be tested or the run did not finish.
If you stop a run with Ctrl+C, the game folder is restored and a report of what was found until then is still written.

To check only some of the game's languages, name them: `--languages french,spanish`.
To see only problems that an earlier run did not have, give that run's JSON report: `--baseline OLD_REPORT.json`.
To see what a game is without playing it, run `python -m renpytester info PATH_TO_GAME`.

Messages are in English or Brazilian Portuguese, following your system; use `--lang en` or `--lang pt-BR` to choose.
Run `python -m renpytester --help` for all options.

## Games that write their own files

RenPyTester puts back everything that it and the engine write into the game folder.
It cannot do that for files the game's own script changes or deletes there, such as a data file the game rewrites.
When a game does that, the report says so and names the files.

For such a game, add `--sandbox`:

```text
python -m renpytester PATH_TO_GAME --sandbox
```

A copy of the game is then tested, and the game itself is only read.
The copy is kept, so only the first run has to copy everything; later runs copy just the files that changed.
If file dates on your disk cannot be trusted, `--sandbox-verify` compares the contents of every file, which is slower.

The copies are kept in your user profile.
`python -m renpytester cache list` shows where, and how much space each takes.
`python -m renpytester cache clear` deletes them all, and `python -m renpytester cache clear PATH_TO_GAME` deletes the copy of one game.

## Settings file

Settings can be kept in a file named `renpytester.toml` in the game's folder, beside the `game` folder, so that every run uses them.
The file is optional, and so is everything in it.
An option given on the command line wins over the file, and `--config FILE` uses another file in its place.
A setting the tool does not know is reported as a mistake, never skipped.

```toml
# Any option, by its name with underscores.
stages = ["lint", "routes"]
max_time = 300
fail_on = "warning"
lang = "pt-BR"

# Labels that are not to be played, such as a minigame.
# A call to one returns at once, and a jump to one ends the story there.
exclude_labels = ["pong_game", "debug_*"]

# How serious a kind of problem is to you.
[severity]
untranslated = "error"

# What to type at a particular prompt. Other prompts get --input-value.
[inputs]
"What is the door code?" = "4721"

# Values that variables of the game have when the story starts.
[variables]
tickets = 2

# Problems you do not want listed. They are still counted.
# A problem is left out when it matches every part of a rule.
[[ignore]]
class = "untranslated"
language = "french"

[[ignore]]
file = "game/old/*.rpy"
message = "is not defined"
```

The parts of an ignore rule are `class` (the kind of problem, as the JSON report names it), `file` and `label` (patterns with `*`), `language`, and `message` (a regular expression looked for in the problem's message).
