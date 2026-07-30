"""
Properties a translation must hold beyond simply existing.

Coverage is checked elsewhere. This file is about the two ways a present,
plausible-looking translation is still wrong.

Placeholders
------------
Translated strings are passed to ``str.format``. A German string that
writes ``{due_data}`` where English writes ``{due_date}`` raises KeyError
at the moment a user opens the screen - not at build time, not in review,
and only in German. 438 strings were written by hand in one pass, and a
transposed placeholder is invisible to anyone reading for meaning.

So every language must use exactly the placeholders English uses: no
missing ones, no invented ones.

Swiss orthography
-----------------
Switzerland does not use ß. Swiss standard German writes ss everywhere -
"Massnahme", not "Maßnahme"; "abschliessen", not "abschließen". This is
not a preference; it is the orthography of the market this product is
sold into, and a German interface full of ß reads as German-from-Germany
to a Swiss administrator. For a product whose entire claim is Swiss
specificity, that is the wrong first impression.
"""

import json
import re
from pathlib import Path

import pytest

from i18n.translator import TRANSLATED_LANGUAGES


TRANSLATIONS_DIR = (
    Path(__file__).resolve().parent.parent / "i18n" / "translations"
)

REFERENCE_LANGUAGE = "en"

# {name} but not {{escaped}}. Format specs are not used in this
# catalogue, so a bare identifier is the whole grammar.
_PLACEHOLDER = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _load(language):
    return json.loads(
        (TRANSLATIONS_DIR / f"{language}.json").read_text(encoding="utf-8")
    )


def _placeholders(text):
    return set(_PLACEHOLDER.findall(text))


NON_REFERENCE_LANGUAGES = [
    language for language in TRANSLATED_LANGUAGES
    if language != REFERENCE_LANGUAGE
]


@pytest.mark.parametrize("language", NON_REFERENCE_LANGUAGES)
def test_placeholders_match_english_exactly(language):
    """
    The failure is a KeyError on a live screen, in one language only.
    """

    english = _load(REFERENCE_LANGUAGE)
    translated = _load(language)

    problems = []

    for key, source in english.items():

        if key not in translated:
            continue

        expected = _placeholders(source)
        actual = _placeholders(translated[key])

        if expected == actual:
            continue

        missing = expected - actual
        invented = actual - expected

        detail = []

        if missing:
            detail.append(f"missing {sorted(missing)}")
        if invented:
            detail.append(f"unexpected {sorted(invented)}")

        problems.append(f"  {key}: {', '.join(detail)}")

    assert not problems, (
        f"{language}.json placeholders do not match English:\n"
        + "\n".join(problems)
        + "\n\nEvery one of these raises KeyError from str.format the "
          "moment the screen is opened in this language."
    )


@pytest.mark.parametrize("language", TRANSLATED_LANGUAGES)
def test_no_translation_is_left_empty(language):
    """
    An empty string is worse than a missing key: the fallback chain in
    i18n.translator only fires on a missing key, so an empty value
    renders as a blank label with nothing to explain it.
    """

    blank = [
        key for key, value in _load(language).items()
        if not isinstance(value, str) or not value.strip()
    ]

    assert not blank, f"{language}.json has blank values: {sorted(blank)}"


def test_german_uses_swiss_orthography():
    """
    ss, never ß.

    Switzerland abolished ß; Swiss standard German uses ss in every
    position. A Swiss HR administrator reading "Maßnahme" sees software
    localised for Germany, which is the opposite of what this product
    claims to be.
    """

    german = _load("de")

    offenders = {
        key: value for key, value in german.items() if "ß" in value
    }

    assert not offenders, (
        "de.json contains ß, which Swiss standard German does not use:\n"
        + "\n".join(f"  {key}: {value}" for key, value in offenders.items())
    )


@pytest.mark.parametrize("language", NON_REFERENCE_LANGUAGES)
def test_a_translation_is_not_just_the_english_string(language):
    """
    Catches keys added to a language file to satisfy a coverage check
    without being translated.

    Not every match is a mistake - "Canton", "Status", "Pages" and the
    permit codes are genuinely identical - so this bounds the proportion
    rather than forbidding it. A language where a third of the strings
    are still English has not been translated; it has been filled in.
    """

    english = _load(REFERENCE_LANGUAGE)
    translated = _load(language)

    shared = [key for key in english if key in translated]

    identical = [
        key for key in shared
        if english[key].strip() == translated[key].strip()
        # Emoji-only and punctuation-only values are the same in every
        # language by design.
        and any(character.isalpha() for character in english[key])
    ]

    proportion = len(identical) / len(shared)

    assert proportion < 0.15, (
        f"{len(identical)} of {len(shared)} {language} strings are "
        f"identical to English ({proportion:.0%}):\n"
        + "\n".join(f"  {key}" for key in sorted(identical)[:25])
    )


def test_every_translated_language_has_a_file_that_parses():

    for language in TRANSLATED_LANGUAGES:

        path = TRANSLATIONS_DIR / f"{language}.json"

        assert path.exists(), f"{path.name} is missing"

        data = json.loads(path.read_text(encoding="utf-8"))

        assert isinstance(data, dict) and data, f"{path.name} is empty"
