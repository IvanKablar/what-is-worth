"""User-facing texts per language.

Each language is one module in `locales/` with the same keys as English. The
language comes from WIW_LANG, else from the first set locale variable
(LC_ALL, LC_MESSAGES, LANG); unknown languages fall back to English.
"""

from __future__ import annotations

import importlib
import os

LANGUAGES = ("de", "en", "es", "ja", "ru", "zh")
FALLBACK = "en"
_language: str | None = None
_catalogs: dict[str, dict[str, str]] = {}


def catalog(code: str) -> dict[str, str]:
    if code not in _catalogs:
        _catalogs[code] = importlib.import_module(f".locales.{code}", __package__).MESSAGES
    return _catalogs[code]


def detect_language() -> str:
    explicit = os.environ.get("WIW_LANG", "").lower()[:2]
    if explicit in LANGUAGES:
        return explicit
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if value:
            code = value.split("_")[0].split(".")[0].lower()
            return code if code in LANGUAGES else FALLBACK
    return FALLBACK


def language() -> str:
    global _language
    if _language is None:
        _language = detect_language()
    return _language


def set_language(code: str | None) -> None:
    """Force a language, or None to detect it again (used by tests)."""
    global _language
    _language = code if code is None or code in LANGUAGES else FALLBACK


def t(key: str, **values: object) -> str:
    text = catalog(language()).get(key) or catalog(FALLBACK)[key]
    return text.format(**values) if values else text


def plural_category(n: int, code: str | None = None) -> str:
    """CLDR plural category for cardinal numbers, for the languages we ship."""
    code = code or language()
    if code in ("ja", "zh"):
        return "other"
    if code == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    return "one" if n == 1 else "other"


def noun(key: str, n: int) -> str:
    """Plural form of `noun.<key>` for count `n`."""
    messages = catalog(language())
    category = plural_category(n)
    return messages.get(f"noun.{key}.{category}") or messages.get(f"noun.{key}.other") \
        or catalog(FALLBACK)[f"noun.{key}.other"]


# argparse looks up its own texts through a module-level gettext `_`. These
# are the ones users see; everything else stays as argparse ships it.
_ARGPARSE_KEYS = {
    "usage: ": "argparse.usage",
    "positional arguments": "argparse.positionals",
    "options": "argparse.options",
    "show this help message and exit": "argparse.help",
    "%(prog)s: error: %(message)s\n": "argparse.error",
    "the following arguments are required: %s": "argparse.required",
    "invalid choice: %(value)r (choose from %(choices)s)": "argparse.invalid_choice",
    "unrecognized arguments: %s": "argparse.unrecognized",
    "argument %(argument_name)s: %(message)s": "argparse.argument",
    "expected one argument": "argparse.expected_one",
    "invalid %(type)s value: %(value)r": "argparse.invalid_value",
    " (default: %(default)s)": "argparse.default",
    "ambiguous option: %(option)s could match %(matches)s": "argparse.ambiguous",
}


def localize_argparse() -> None:
    import argparse

    def translate(message: str) -> str:
        key = _ARGPARSE_KEYS.get(message)
        return t(key) if key else message

    argparse._ = translate
