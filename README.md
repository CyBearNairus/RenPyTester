# RenPyTester

Test all routes on a RenPy game to ensure it's working properly.

RenPyTester plays through a Ren'Py game by itself, with no window on screen, and reports crashes and script errors with the file and line where they happened.
It also runs Ren'Py's own lint, so problems in scenes the playthrough did not reach, such as a missing image or a jump to a label that does not exist, are reported too.
It works on any Ren'Py 8 game, built or in development, and leaves the game folder exactly as it found it.

It tries every choice of every menu, and tells you how much of the script it played and which labels it never reached.

This is an early version.
Checking translations, HTML reports and a graphical interface are planned; see [docs/SPEC.md](docs/SPEC.md).

## Usage

You need Python 3.11 or later.
Nothing else has to be installed.

```text
python -m renpytester PATH_TO_GAME
```

`PATH_TO_GAME` is the game's folder, or any file inside it.
A game that ships its own engine needs nothing more.
For a project that lives in the Ren'Py launcher's projects folder, add the SDK:

```text
python -m renpytester PATH_TO_GAME --sdk PATH_TO_RENPY_SDK
```

The result is printed and also saved in the `renpytester-report` folder, in a file named after the game and the time of the run, such as `report-the-question-2026-10-06-143005.json`.
Earlier reports are never overwritten.
The exit code is 0 when no errors were found, 1 when errors were found, and 3 when the game could not be tested.

Messages are in English or Brazilian Portuguese, following your system; use `--lang en` or `--lang pt-BR` to choose.
Run `python -m renpytester --help` for all options.
