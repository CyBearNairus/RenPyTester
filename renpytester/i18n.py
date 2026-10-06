"""Message catalogue (spec 4.15).

Every piece of text shown to the user comes from here, by identifier. Machine-readable output
never does.
"""

import json
import locale
import os
import sys
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent / "locale"
LANGUAGES = ("en", "pt-BR")
DEFAULT = "en"

_catalogues = {}
_current = DEFAULT


def _load(language):
    if language not in _catalogues:
        path = LOCALE_DIR / (language.replace("-", "_") + ".json")
        _catalogues[language] = json.loads(path.read_text(encoding="utf-8"))
    return _catalogues[language]


def normalise(code):
    """Maps a locale name such as 'pt_BR.UTF-8' or 'Portuguese_Brazil' to a supported language, or None."""
    if not code:
        return None
    code = code.replace("_", "-").lower()
    if code.startswith("pt") or code.startswith("portuguese"):
        return "pt-BR"
    if code.startswith("en") or code.startswith("english"):
        return "en"
    return None


def detect():
    """The interface language suggested by the operating system (I18N-002)."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        found = normalise(os.environ.get(name))
        if found:
            return found

    if sys.platform == "win32":
        try:
            import ctypes

            # The primary language identifier is the low ten bits; 0x16 is Portuguese.
            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x16:
                return "pt-BR"
            return DEFAULT
        except Exception:
            pass

    try:
        return normalise(locale.getlocale()[0]) or DEFAULT
    except Exception:
        return DEFAULT


def set_language(language=None):
    global _current
    _current = normalise(language) or detect()
    return _current


def get_language():
    return _current


def t(message_id, _language=None, **params):
    """Returns the text for a message identifier in the current language."""
    catalogue = _load(_language or _current)
    text = catalogue.get(message_id)
    if text is None:
        text = _load(DEFAULT).get(message_id, message_id)
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        return text
