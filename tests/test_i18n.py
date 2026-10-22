import string
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatisworth import i18n  # noqa: E402
from whatisworth.format import counted, left, number, pct, right, usd, width  # noqa: E402


@pytest.fixture(autouse=True)
def reset_language():
    yield
    i18n.set_language(None)


def placeholders(text):
    """`{name}` placeholders, and `%(name)s` / `%s` ones for argparse texts."""
    import re

    braces = set() if "%(" in text or "%s" in text else {
        name for _, name, _, _ in string.Formatter().parse(text) if name}
    return braces | set(re.findall(r"%\(\w+\)[sr]|%s", text))


@pytest.mark.parametrize("code", [c for c in i18n.LANGUAGES if c != "en"])
def test_every_language_has_every_key_with_the_same_placeholders(code):
    english, other = i18n.catalog("en"), i18n.catalog(code)
    plural_extras = {k for k in other if k.endswith((".few", ".many"))}
    assert set(other) - plural_extras == set(english)
    for key, text in english.items():
        assert placeholders(other[key]) == placeholders(text), key


def test_language_detection(monkeypatch):
    monkeypatch.setenv("WIW_LANG", "")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("LC_MESSAGES", "ru_RU.UTF-8")
    assert i18n.detect_language() == "ru"
    monkeypatch.setenv("WIW_LANG", "ja")
    assert i18n.detect_language() == "ja"
    monkeypatch.setenv("WIW_LANG", "")
    monkeypatch.setenv("LC_MESSAGES", "fr_FR.UTF-8")
    assert i18n.detect_language() == "en"


@pytest.mark.parametrize("n, expected", [
    (1, "1 сессия"), (2, "2 сессии"), (5, "5 сессий"), (11, "11 сессий"),
    (21, "21 сессия"), (22, "22 сессии"), (112, "112 сессий"),
])
def test_russian_plurals(n, expected):
    i18n.set_language("ru")
    assert counted(n, "session") == expected


@pytest.mark.parametrize("code, money, percent", [
    ("de", "1.234,50 $", "51 %"),
    ("en", "$1,234.50", "51%"),
    ("es", "1.234,50 US$", "51 %"),
    ("ru", "1 234,50 $", "51 %"),
    ("zh", "US$1,234.50", "51%"),
    ("ja", "$1,234.50", "51%"),
])
def test_money_and_percent_formats(code, money, percent):
    i18n.set_language(code)
    assert usd(1234.5) == money
    assert pct(51) == percent
    assert number(1234) in money


def test_padding_uses_display_width_for_cjk():
    assert width("账户") == 4
    assert width(left("账户", 8)) == 8
    assert width(right("API 価値", 12)) == 12
    assert width(left("プロジェクト別のとても長い名前", 10)) <= 10


def test_translated_argparse_texts_still_exist_in_argparse():
    import argparse
    import inspect

    source = inspect.getsource(argparse)
    for english in i18n._ARGPARSE_KEYS:
        assert repr(english)[1:-1] in source or english in source, english
