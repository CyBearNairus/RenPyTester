# RenPyTester: everything beyond the first run

The [README](../README.md) shows how to get RenPyTester and test a game.
This page has the rest.

The examples say `python -m renpytester`, which is how it is run from the source.
With a downloaded program, write the program's name there.
Installed with `pipx install .` or `uv tool install .` from a copy of the repository, the command is `renpytester`.

## What is checked

A run makes four checks, and all four are made unless you say otherwise.

| Check | What it does |
| --- | --- |
| `lint` | Runs Ren'Py's own lint, which reads the script without playing it. It finds problems in scenes the playthrough did not reach, such as a missing image or a jump to a label that does not exist. |
| `routes` | Plays the game, trying every choice of every menu, and reports crashes and script errors where they happen. It also plays each label by itself, to reach what the story never reaches. |
| `translations` | For each language the game has: lines and texts with no translation, translations with a broken text tag, translations that show different `[variables]` from the original, and languages the game cannot be switched to. |
| `screens` | Puts together each menu screen the game has (main menu, preferences, save, load, history, about, help and the yes-or-no question), in every language, and reports one that fails, has a broken text tag, or shows a picture whose file is missing. |

`--stages lint,routes` makes only the checks you name.
`--languages french,spanish` checks only those of the game's languages.

As the story is played, every translation of each line is tried out in the state the game is really in.
A translation that uses a variable the game does not have is found that way, without playing the game again in each language.

The report also says how much of the script was played and which labels were never reached.
Something the tool cannot play, such as a minigame, is skipped, and the story carries on from it once for each result the script goes on to check for.
What is found after that, or by playing a label by itself, is listed apart as a *possible issue*: the game was then in a state the tool made up, so a player may never meet it.

## The window

`python -m renpytester` with nothing after it opens the window, and so does `python -m renpytester gui PATH_TO_GAME`, with that game already chosen.
Dropping a game's folder on the downloaded program does the same.

*Show advanced settings* lets you choose what is checked, which languages, whether to test a copy of the game, and where the reports are saved.
*Cancel* stops a run and puts the game folder back as it was.
The window also shows the command that makes the same run from a terminal, to copy into a script or a build server.
Its reports are saved in a folder named `renpytester-report` in your home folder, unless you choose another.

On some Linux systems Python comes without the part that draws windows; RenPyTester then tells you which package to install, and the command line still works.

### The two programs for Windows

The release page has two files for Windows, which are the same program.

- `renpytester-windows-x64.exe` is for a double click. It opens the window and never shows a console window.
- `renpytester-windows-x64-console.exe` is for a terminal, a script or a build server. The terminal waits for it to finish and gets its exit code.

The first also takes every option described here, and that works when another program starts it and waits for it.
Typed into a terminal by hand it is not waited for, which is why there is a second one.

## The command line

```text
python -m renpytester PATH_TO_GAME
```

`PATH_TO_GAME` is the game's folder, or any file inside it.
A game that ships its own engine needs nothing more.
For a project that lives in the Ren'Py launcher's projects folder, add `--sdk PATH_TO_RENPY_SDK`, or set the `RENPY_SDK` environment variable.

The result is printed and also saved in the `renpytester-report` folder, in files named after the game and the time of the run, such as `report-the-question-2026-10-06-143005.html`.
`--output FOLDER` saves them elsewhere.
Earlier reports are never overwritten.
Three files are written each time:

- `.html`: the report to read. Open it in any browser; it needs no internet connection.
- `.json`: everything the run found, for other programs. Its format is described in [report-schema.md](report-schema.md).
- `.xml`: a JUnit report, which CI systems show as test results.

If you stop a run with Ctrl+C, the game folder is restored and a report of what was found until then is still written.

Other things you can ask for:

- `--baseline OLD_REPORT.json` lists only problems that an earlier run did not have.
- `--fail-on warning` makes warnings fail the run too; `--fail-on-possible` does the same for possible issues.
- `--jobs N` sets how many copies of the game run at once. The result is the same for any number.
- `--strategy first` plays a single path, taking the first choice everywhere: a quick check that the game runs at all.
- `--no-labels` does not play each label by itself.
- `--max-time`, `--max-paths` and `--max-depth` limit how far the game is explored; the report says when a limit was reached.
- `--timeout SECONDS` is how long the game may go without making progress before it is taken to have hung.
- `python -m renpytester info PATH_TO_GAME` says what a game is, without playing it.

Run `python -m renpytester --help` for all options, each with its default.

Messages are in English or Brazilian Portuguese, following your system; use `--lang en` or `--lang pt-BR` to choose.

## Exit codes and build servers

| Exit code | Meaning |
| --- | --- |
| 0 | No errors were found. |
| 1 | Errors were found. |
| 2 | An option or the settings file is wrong. |
| 3 | The game could not be tested, or the run did not finish. |

On a build server, run the command and keep the `.xml` file as the test results and the `.html` file as something to read.
A project with known problems can still fail only on new ones: keep the `.json` report of a run you accept, and give it to later runs as `--baseline`.

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
# The checks are lint, routes, translations and screens; all four are made unless you say otherwise.
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
