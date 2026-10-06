# JSON report schema

RenPyTester writes one JSON report per run into the output folder (spec REP-002).
The file is named `report-<game name>-<yyyy-mm-dd>-<hhmmss>.json`, in local time, so earlier reports are never overwritten (spec REP-009).
This document describes schema version 1.
The file is UTF-8, and nothing in it depends on the interface language (spec I18N-003).

`schema_version` increases whenever a field is removed, renamed or changes meaning.
Adding a field does not change it, so readers should ignore fields they do not know.

## Top level

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | `1` |
| `tool` | object | `name` (`"renpytester"`) and `version`. |
| `complete` | boolean | `false` when the run was cut short. A report that is not complete proves nothing about what it does not list. |
| `started`, `finished` | string | ISO 8601 timestamps in UTC. |
| `game` | object | See below. |
| `settings` | object | The settings the run used, including `seed`, so the run can be repeated. `jobs` is the number of game processes that were allowed to run at once. `languages` is the list given with `--languages`, or `null` when every language was to be checked. |
| `stages` | object | One entry per stage, keyed by stage name. See below. |
| `summary` | object | Number of confirmed findings per severity (`error`, `warning`, `info`), and `possible`, the number of possible issues of any severity. |
| `coverage` | object or null | See below. `null` when the game never started. |
| `statistics` | object | `statements` and `interactions` executed, and `script`: what lint counted (see below). |
| `notes` | array | Things worth knowing that are not problems in the game. Each has `message_id` and `params`. |
| `findings` | array | See below. Sorted by severity, then file, then line. |

## `game`

| Field | Type | Meaning |
| --- | --- | --- |
| `path` | string | The game folder that was tested. |
| `kind` | string | `distribution` (ships its own engine) or `project` (run with an SDK). |
| `name`, `version` | string or null | As the game declares them. |
| `renpy_version` | string or null | The engine version. |
| `python` | string | The version of the Python inside the engine. |
| `languages` | array of strings | Languages the game has translations for. |

## `statistics.script`

Present when the lint stage ran.

| Field | Type | Meaning |
| --- | --- | --- |
| `dialogue` | object | `blocks`, `words` and `characters` of dialogue in the game's own language. |
| `menus`, `images`, `screens` | integer | How many the game defines. |
| `translations` | object | For each language, the same three counts as `dialogue`. |

## `stages`

Each stage has a `status`:

| Status | Meaning |
| --- | --- |
| `done` | The stage ran to its end. |
| `blocked` | The stage could not run because of a problem in the game, which is listed in `findings`. |
| `not_run` | The stage did not run. |
| `not_selected` | The stage was left out with `--stages`. |
| `failed` | The stage could not finish, for a reason given in `reason`. The report is then not complete. |
| `not_implemented` | This version of RenPyTester does not have the stage yet. It was not checked. |

The `lint` stage also has `findings` (how many it produced) and, on engine versions that lack some lint checks, `unsupported_options`.

The `routes` stage also has:

- `paths`: how many paths were played.
- `end_reasons`: how many paths ended for each reason (`end`, `quit`, `exception`, `stuck`, `loop`, `exhausted`, `hang`, `engine-crash`, `max_time`, and `label end` for a label run that reached another label).
- `label_runs`: how many labels were played by themselves. Absent when label runs were turned off.
- `possible_dropped`: how many possible issues were left out of the report because the story itself played the same statement without that problem.
- `launches`: how many times the game was started for this stage.
- `jobs`: how many game processes explored at the same time. When `launches` is greater than `jobs`, a process died or hung and another carried on from it.
  The first process explores the story and keeps its logs in the log folder itself; each of the others plays label runs and keeps its logs in a subfolder named `labels-1`, `labels-2` and so on.
- `limited`: present only when a limit stopped exploration early. It has `kind` (`max_paths`, `max_time` or `relaunches`), `unexplored`, the number of branches left, and `labels`, the number of labels not played by themselves.

The `translations` stage also has:

- `languages`: one entry for each language that was checked, keyed by the language's name, in alphabetical order.
  Each has `switched` (`false` when the game could not be switched to that language), and `dialogue` and `strings`, each with `translated` and `total`.
  `dialogue` counts lines of dialogue.
  `strings` counts the game's other translatable texts: menu choices, and text marked for translation in screens and Python.
  The object is empty for a game with no translations.
- `findings`: how many findings in the report belong to this stage.
- `played`: `false` when the routes stage did not run, so translated lines were not tried out in the state the game is in when it reaches them.
  A `bad-interpolation` problem cannot be found then.
- `strings_from_source`: present, and `false`, only when the game has no script source files.
  Text marked for translation in screens and Python could then not be listed, and `strings` counts menu choices only.

## `coverage`

| Field | Type | Meaning |
| --- | --- | --- |
| `executed` | integer | Statements that were played. |
| `low_confidence` | integer | Statements reached only in a label run or after the tool skipped something it could not play, in a state it made up. Not included in `executed`. |
| `total` | integer | Statements a playthrough could play. Start-up code, translation blocks and engine test cases are not counted. |
| `files` | object | For each script file, `[executed, total]`. |
| `labels` | object | For each label, its `file` and `line`, and `executed`, `low_confidence` and `total` for the statements under it. |
| `unreached_labels` | array of strings | Labels none of whose statements were played, even with low confidence, in script order. |

## `findings`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable identifier: the same problem has the same id in every run and every interface language. |
| `class` | string | The kind of problem. See the table below. |
| `severity` | string | `error`, `warning` or `info`. |
| `message_id`, `params` | string, object | The message as an identifier and its values. Text in any supported language is produced from these. |
| `file`, `line` | string, integer, or null | Where in the game's script, relative to the game folder. |
| `label` | string or null | The label being played. |
| `stage` | string | The stage that found it. |
| `language` | string or null | The game language the finding is about: set for findings in or about a translation, `null` for the game's own language. |
| `path` | array | The decisions that led here, in order. Each has `kind` (`menu`, `screen`, `input`, `skip` for the outcome chosen for a skipped interaction, or `label` for the label a label run started at, which is then the first step), `file`, `line`, `choice` (the text chosen or typed) and `index`. |
| `traceback` | string or null | The engine's traceback, when there is one. |
| `count` | integer | How many times this problem was reached. |
| `possible` | boolean | `true` when the problem was only seen in a label run or after the tool skipped something it could not play, so a real player may never reach it. Possible issues do not fail a run unless `--fail-on-possible` is given. |
| `also` | array | The same problem as other stages reported it. Each entry has `stage`, `class`, `message_id` and `params`. |

## Finding classes

| Class | Severity | Meaning |
| --- | --- | --- |
| `parse-error` | error | A script file could not be read. The game cannot start. |
| `load-failure` | error | The game failed while starting up. |
| `exception` | error | A statement raised an error the game did not handle. |
| `hang` | error | The game stopped making progress and was shut down. |
| `engine-crash` | error | The engine process ended without explanation. |
| `stuck` | info | The game waited for something the tool cannot do, such as a minigame. It was skipped and not tested. |
| `loop` | warning | A path ran past the statement limit without ending. |
| `undefined-image` | error | An image is shown that was never defined. Found by playing or by lint. |
| `missing-file` | error | An image, audio or movie file the script uses cannot be loaded. Found by playing or by lint. |
| `missing-label` | error | Lint: a jump or call names a label that does not exist. |
| `bad-text` | error | A text tag is unknown or was never closed. Found by playing or by lint. |
| `no-choice` | error | A menu was reached with every one of its choices switched off. |
| `needs-display` | info | The game used something that only works with a real screen, so the path could not go further. |
| `undefined-name` | error | Lint: a name, such as a character, was never defined. |
| `lint` | warning | Lint: a kind of problem this tool does not classify. The message is lint's own. |
| `unreachable` | info | Lint: a statement no path can reach. |
| `orphan-translation` | info | Lint: a translation whose original line no longer exists. |
| `language-switch` | error | The game could not be switched to a language: the set-up code or styles of its translation failed. `file` and `line` are in the translation. |
| `bad-interpolation` | error | A translated line could not be shown in the state the game was in when the story reached it, usually because it names a variable the game does not have. `file` and `line` are in the translation; `path` is how the story got there. |
| `untranslated` | warning | A line of dialogue (`message_id` `finding.untranslated_line`) or another text (`finding.untranslated_string`) has no translation into the language in `language`. `file` and `line` are the original's. |
| `variable-mismatch` | warning | A translation does not show the same `[variables]` as its original. `params` has `missing` and `extra`, each a list separated by commas, or `-` for none. |

A `bad-text` finding with a `language` is about a translation, and its `file` and `line` are in the translation.
