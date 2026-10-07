# Security Policy

## Supported Versions

Only the newest release gets security fixes.
A fix is published as a new release; older releases are not patched.

| Version | Supported |
| --- | --- |
| Newest 0.1.x release | :white_check_mark: |
| Any older release | :x: |

The newest release is the one at the top of the [releases page](https://github.com/CyBearNairus/RenPyTester/releases).

## What counts as a vulnerability

RenPyTester plays a game by running it, with the game's own Ren'Py engine.
A game's script is a program, and it runs with the same rights as the person who started the test.
**Testing a game is as safe as playing it: only test games you trust.**
The `--sandbox` option tests a copy so that the game folder is not written to; it does not confine what the game's code can do, and that is not a vulnerability.

These are vulnerabilities, and reports of them are welcome:

- A report (HTML, JUnit XML or JSON) that runs or loads something the game wrote, when it is opened.
  Everything that comes from a game is meant to be shown as text only.
- RenPyTester writing, changing or deleting files outside the places it says it uses: its files in the game folder while a run lasts, the report folder, its cache and its temporary folders.
- A `renpytester.toml`, a cached copy or a report from an earlier run making RenPyTester run code or reach files it should not, by itself and without the game being played.
- A released executable that holds or loads something other than what this repository builds.
- A weakness in how releases are built and published by the workflows in this repository.

A problem in Ren'Py itself belongs with the [Ren'Py project](https://github.com/renpy/renpy).
A bug that is not a security problem goes in the ordinary [issue tracker](https://github.com/CyBearNairus/RenPyTester/issues).

## Reporting a Vulnerability

Please do not open a public issue for a vulnerability.
Report it privately with GitHub's [Report a vulnerability](https://github.com/CyBearNairus/RenPyTester/security/advisories/new) form, which only the maintainer can read.

Say, as far as you can:

- the version of RenPyTester (`renpytester --version`, or the *About* dialog) and whether it was run from source or as an executable;
- the operating system and the version of Ren'Py;
- the steps that show the problem, with the smallest game or file that does;
- what someone could do with it.

Do not attach a game, or part of one, that is not yours to share.

## What to expect

This project is kept by one person in their spare time.

- An accepted vulnerability will be fixed in a new release.
- When the fix is released, a security advisory is published that names you as the finder, unless you ask not to be named.
- Please keep the details private until the fix is released, or until 90 days after your report, whichever comes first.

A report that is declined can still be opened as an ordinary issue if it describes a bug.
