"""The optional configuration file, renpytester.toml (spec 4.11).

Everything in it is optional (CFG-001), and anything given on the command line wins over it
(CFG-002). A key the tool does not know is an error, not something to ignore: a misspelt setting
that silently did nothing would be worse than no setting (CFG-004).
"""

import fnmatch
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from renpytester import i18n
from renpytester.errors import UsageError
from renpytester.model import SEVERITIES

FILE_NAME = "renpytester.toml"

STRATEGIES = ("explore", "first")
FAIL_ON = (*SEVERITIES, "never")
# What a finding can be matched on by an ignore rule (CFG-003).
RULE_KEYS = ("class", "file", "label", "language", "message")


def _text(value):
    return isinstance(value, str) and bool(value)


def _whole(minimum):
    return lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _flag(value):
    return isinstance(value, bool)


def _one_of(choices):
    return lambda value: value in choices


def _texts(value):
    return isinstance(value, list) and all(_text(item) for item in value)


def _plain(value):
    """True for a value that can be handed to the game as it is: no dates, nothing TOML-only."""
    if isinstance(value, list):
        return all(_plain(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _plain(item) for key, item in value.items())
    return isinstance(value, (str, int, float, bool))


def _table_of(check):
    return lambda value: isinstance(value, dict) and all(check(item) for item in value.values())


# Every key the file may have: what its value must be, and the words that say so in an error message.
# The run settings have the names of their command-line options, with underscores.
SETTINGS = {
    "sdk": (_text, "config.expected.text"),
    "output": (_text, "config.expected.text"),
    "baseline": (_text, "config.expected.text"),
    "stages": (_texts, "config.expected.texts"),
    "languages": (_texts, "config.expected.texts"),
    "strategy": (_one_of(STRATEGIES), "config.expected.strategy"),
    "labels": (_flag, "config.expected.flag"),
    "jobs": (_whole(1), "config.expected.whole"),
    "seed": (_whole(0), "config.expected.whole"),
    "timeout": (_number, "config.expected.number"),
    "input_value": (lambda value: isinstance(value, str), "config.expected.text"),
    "max_steps": (_whole(1), "config.expected.whole"),
    "max_paths": (_whole(1), "config.expected.whole"),
    "max_time": (_number, "config.expected.number"),
    "max_depth": (_whole(1), "config.expected.whole"),
    "fail_on": (_one_of(FAIL_ON), "config.expected.fail_on"),
    "fail_on_possible": (_flag, "config.expected.flag"),
    "show_window": (_flag, "config.expected.flag"),
}
OTHER = {
    "lang": (lambda value: _text(value) and i18n.normalise(value) is not None, "config.expected.lang"),
    "exclude_labels": (_texts, "config.expected.texts"),
    "severity": (_table_of(_one_of(SEVERITIES)), "config.expected.severity"),
    "inputs": (_table_of(lambda value: isinstance(value, str)), "config.expected.inputs"),
    "variables": (_table_of(_plain), "config.expected.variables"),
    "ignore": (lambda value: isinstance(value, list), "config.expected.ignore"),
}
# Settings that name a file or folder. A relative one is relative to the config file, not to
# wherever the tool happens to be started from.
PATHS = ("sdk", "output", "baseline")


@dataclass
class Rule:
    """One ignore rule. A finding is ignored when it matches every part the rule has (CFG-003)."""

    cls: str | None = None
    file: str | None = None
    label: str | None = None
    language: str | None = None
    message: str | None = None

    def matches(self, finding):
        if self.cls is not None and finding.cls != self.cls:
            return False
        if self.file is not None and not fnmatch.fnmatchcase(finding.file or "", self.file):
            return False
        if self.label is not None and not fnmatch.fnmatchcase(finding.label or "", self.label):
            return False
        if self.language is not None and finding.language != self.language:
            return False
        if self.message is not None:
            # The words of a message depend on the interface language. A rule must not stop working
            # when someone else runs the tool in another one, so it is tried on the message in each.
            texts = [i18n.t(finding.message_id, _language=name, **finding.params) for name in i18n.LANGUAGES]
            if not any(re.search(self.message, text) for text in texts):
                return False
        return True

    def to_dict(self):
        parts = {"class": self.cls, "file": self.file, "label": self.label, "language": self.language,
                 "message": self.message}
        return {name: value for name, value in parts.items() if value is not None}


@dataclass
class Config:
    path: Path | None = None
    # Run settings, by the name of their field in runner.Options.
    settings: dict = field(default_factory=dict)
    lang: str | None = None
    # Finding class -> the severity its findings are to have (TL-005, CFG-007).
    severity: dict = field(default_factory=dict)
    ignore: list = field(default_factory=list)
    # Text of a prompt -> what to type there (CFG-005).
    inputs: dict = field(default_factory=dict)
    # Game variable -> the value it has when the story starts (CFG-005).
    variables: dict = field(default_factory=dict)
    exclude_labels: list = field(default_factory=list)


def find(basedir, explicit=None):
    """The config file to use: the one named, or the one in the game folder, or None (CFG-002)."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise UsageError("error.config_missing", path=str(path))
        return path.resolve()
    path = Path(basedir) / FILE_NAME
    return path if path.is_file() else None


def _bad(path, key, expected):
    return UsageError("error.config_bad_value", file=str(path), key=key, expected=i18n.t(expected))


def _unknown(path, key, known):
    return UsageError("error.config_unknown_key", file=str(path), key=key, known=", ".join(sorted(known)))


def _rule(path, number, entry):
    key = "ignore[%d]" % number
    if not isinstance(entry, dict) or not entry:
        raise _bad(path, key, "config.expected.ignore")
    for name, value in entry.items():
        if name not in RULE_KEYS:
            raise _unknown(path, "%s.%s" % (key, name), RULE_KEYS)
        if not _text(value):
            raise _bad(path, "%s.%s" % (key, name), "config.expected.text")
    if "message" in entry:
        try:
            re.compile(entry["message"])
        except re.error:
            raise _bad(path, key + ".message", "config.expected.pattern") from None
    return Rule(entry.get("class"), entry.get("file"), entry.get("label"), entry.get("language"),
                entry.get("message"))


def load(path):
    """Reads and checks a config file. Raises UsageError, which is exit code 2, for anything wrong in it."""
    if path is None:
        return Config()
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise UsageError("error.config_unreadable", file=str(path), message=str(error)) from None

    known = {**SETTINGS, **OTHER}
    for key, value in data.items():
        if key not in known:
            raise _unknown(path, key, known)
        check, expected = known[key]
        if not check(value):
            raise _bad(path, key, expected)

    config = Config(path=path)
    for key in SETTINGS:
        if key in data:
            value = data[key]
            if key in PATHS:
                value = str((path.parent / Path(value).expanduser()).resolve())
            config.settings[key] = tuple(value) if isinstance(value, list) else value
    config.lang = i18n.normalise(data["lang"]) if "lang" in data else None
    config.severity = dict(data.get("severity", {}))
    config.inputs = dict(data.get("inputs", {}))
    config.variables = dict(data.get("variables", {}))
    config.exclude_labels = list(data.get("exclude_labels", []))
    config.ignore = [_rule(path, number, entry) for number, entry in enumerate(data.get("ignore", []), 1)]
    return config
