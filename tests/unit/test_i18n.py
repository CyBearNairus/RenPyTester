import json
import re
from pathlib import Path

import pytest

from renpytester import i18n

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "renpytester"
PARAMETER = re.compile(r"\{(\w+)\}")
MESSAGE_ID = re.compile(r"""["']((?:cli|error|note|finding|console|kind)\.[a-z0-9_.]+)["']""")


def catalogue(language):
    return json.loads((i18n.LOCALE_DIR / (language.replace("-", "_") + ".json")).read_text(encoding="utf-8"))


@pytest.mark.req("I18N-001", "I18N-006")
def test_every_message_exists_in_every_language():
    english = catalogue("en")
    for language in i18n.LANGUAGES:
        assert set(catalogue(language)) == set(english), language


@pytest.mark.req("I18N-006")
def test_translations_use_the_same_parameters():
    english = catalogue("en")
    for language in i18n.LANGUAGES:
        for key, text in catalogue(language).items():
            assert set(PARAMETER.findall(text)) == set(PARAMETER.findall(english[key])), key


@pytest.mark.req("I18N-001")
def test_every_message_used_in_code_is_in_the_catalogue():
    english = catalogue("en")
    used = set()
    for source in list(PACKAGE.rglob("*.py")) + list(PACKAGE.rglob("*.rpy")):
        used.update(MESSAGE_ID.findall(source.read_text(encoding="utf-8")))
    used = {key for key in used if not key.endswith(".")}
    assert used, "no message identifiers found; the pattern is out of date"
    assert used <= set(english), sorted(used - set(english))


@pytest.mark.req("I18N-002")
@pytest.mark.parametrize("code, expected", [
    ("pt_BR.UTF-8", "pt-BR"), ("pt-BR", "pt-BR"), ("Portuguese_Brazil", "pt-BR"), ("en_US", "en"),
    ("fr_FR", None), ("", None), (None, None)])
def test_locale_names_are_recognised(code, expected):
    assert i18n.normalise(code) == expected


@pytest.mark.req("I18N-002")
def test_language_can_be_chosen_and_detected(monkeypatch):
    assert i18n.set_language("pt-BR") == "pt-BR"
    assert i18n.t("console.passed") == "APROVADO"
    assert i18n.set_language("en") == "en"
    assert i18n.t("console.passed") == "PASSED"
    for name in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.set_language(None) == "pt-BR"
    i18n.set_language("en")


def test_unknown_message_is_shown_as_its_identifier():
    assert i18n.t("no.such.message") == "no.such.message"
