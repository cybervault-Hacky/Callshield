"""Translation lookup with a strict fall back to English.

`Translator.text(key)` never raises: an unknown language degrades to English,
a key missing from a translation degrades to the English string, and a key
missing everywhere degrades to the key itself so the interface still renders.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .catalog import (
    CATALOGS,
    DEFAULT_LANGUAGE,
    EN,
    LANGUAGE_NAMES,
    LANGUAGES,
)


def normalize_language(name: Any) -> str:
    """Map a user supplied language name to a supported catalogue key."""

    if not isinstance(name, str):
        return DEFAULT_LANGUAGE
    key = name.strip().lower().replace("_", "-")
    if not key:
        return DEFAULT_LANGUAGE
    if key in CATALOGS:
        return key
    # Accept regional tags such as "es-ES" or "pt-BR".
    base = key.split("-", 1)[0]
    if base in CATALOGS:
        return base
    aliases = {
        "english": "en",
        "hindi": "hi",
        "hinglish": "hinglish",
        "roman-hindi": "hinglish",
        "spanish": "es",
        "espanol": "es",
        "french": "fr",
        "francais": "fr",
        "japanese": "ja",
        "chinese": "zh",
        "mandarin": "zh",
        "portuguese": "pt",
        "portugues": "pt",
        "russian": "ru",
    }
    return aliases.get(key, DEFAULT_LANGUAGE)


def language_label(code: str) -> str:
    return LANGUAGE_NAMES.get(normalize_language(code), LANGUAGE_NAMES["en"])


def available_languages() -> Tuple[Tuple[str, str], ...]:
    return tuple((code, LANGUAGE_NAMES[code]) for code in LANGUAGES)


def missing_keys(code: str) -> List[str]:
    """Keys a translation does not define (they fall back to English)."""

    catalog = CATALOGS.get(normalize_language(code), EN)
    return sorted(key for key in EN if key not in catalog)


class Translator:
    """Bound to one language; resolves keys with an English fallback."""

    __slots__ = ("language", "_catalog")

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = normalize_language(language)
        self._catalog: Dict[str, str] = CATALOGS.get(self.language, EN)

    # ------------------------------------------------------------------ api
    def text(self, key: str, **fields: Any) -> str:
        value = self._catalog.get(key)
        if value is None:
            value = EN.get(key)
        if value is None:
            return key
        if fields:
            try:
                return value.format(**fields)
            except (KeyError, IndexError, ValueError):
                return value
        return value

    # Short alias used heavily by the screens.
    def __call__(self, key: str, **fields: Any) -> str:
        return self.text(key, **fields)

    def has(self, key: str) -> bool:
        return key in self._catalog or key in EN

    def is_translated(self, key: str) -> bool:
        return key in self._catalog

    def switch(self, language: str) -> "Translator":
        return Translator(language)

    @property
    def label(self) -> str:
        return language_label(self.language)


__all__ = [
    "CATALOGS",
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "LANGUAGE_NAMES",
    "Translator",
    "available_languages",
    "language_label",
    "missing_keys",
    "normalize_language",
]
