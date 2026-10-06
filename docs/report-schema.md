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
| `settings` | object | The settings the run used, including `seed`, so the run can be repeated. |
| `stages` | object | One entry per stage, keyed by stage name. See below. |
| `summary` | object | Number of findings per severity: `error`, `warning`, `info`. |
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
- `end_reasons`: how many paths ended for each reason (`end`, `quit`, `exception`, `stuck`, `loop`, `exhausted`, `hang`, `engine-crash`, `max_time`).
- `launches`: how many times the game was started. More than one means it died or hung and exploration carried on in a new process.
- `limited`: present only when a limit stopped exploration early. It has `kind` (`max_paths`, `max_time` or `relaunches`) and `unexplored`, the number of branches left.

## `coverage`

| Field | Type | Meaning |
| --- | --- | --- |
| `executed` | integer | Statements that were played. |
| `total` | integer | Statements a playthrough could play. Start-up code, translation blocks and engine test cases are not counted. |
| `files` | object | For each script file, `[executed, total]`. |
| `labels` | object | For each label, its `file` and `line`, and `executed` and `total` for the statements under it. |
| `unreached_labels` | array of strings | Labels none of whose statements were played, in script order. |

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
| `language` | string or null | The game language active at the time. |
| `path` | array | The decisions that led here, in order. Each has `kind` (`menu`, `screen` or `input`), `file`, `line`, `choice` (the text chosen or typed) and `index`. |
| `traceback` | string or null | The engine's traceback, when there is one. |
| `count` | integer | How many times this problem was reached. |
| `also` | array | The same problem as other stages reported it. Each entry has `stage`, `class`, `message_id` and `params`. |

## Finding classes

| Class | Severity | Meaning |
| --- | --- | --- |
| `parse-error` | error | A script file could not be read. The game cannot start. |
| `load-failure` | error | The game failed while starting up. |
| `exception` | error | A statement raised an error the game did not handle. |
| `hang` | error | The game stopped making progress and was shut down. |
| `engine-crash` | error | The engine process ended without explanation. |
| `stuck` | warning | The game waited for something the tool cannot do, such as a minigame. |
| `loop` | warning | A path ran past the statement limit without ending. |
| `undefined-image` | error | Lint: an image is shown that was never defined. |
| `missing-file` | error | Lint: a file the script uses cannot be loaded. |
| `missing-label` | error | Lint: a jump or call names a label that does not exist. |
| `bad-text` | error | Lint: a text tag is unknown or was never closed. |
| `undefined-name` | error | Lint: a name, such as a character, was never defined. |
| `lint` | warning | Lint: a kind of problem this tool does not classify. The message is lint's own. |
| `unreachable` | info | Lint: a statement no path can reach. |
| `orphan-translation` | info | Lint: a translation whose original line no longer exists. |
