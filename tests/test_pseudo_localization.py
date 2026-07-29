"""
Tests for pseudo-localization.

This exists to find layout breakage from longer text before any
translation exists. German runs roughly 30% longer than English, and
Swiss permit vocabulary is worse - "Permit C (Settlement)" becomes
"Ausweis C (Niederlassung)".

Every layout defect this project has already fixed was English text in a
container sized for English text: characters wrapping one per line,
buttons breaking across five rows, a risk badge clipped to "🔺 H". Adding
German after polishing every screen would reintroduce all of them.

The properties that matter here are about not breaking the app while
testing it:

* placeholders must survive, or str.format raises and the page crashes
  instead of showing a layout;
* the pseudo language must be unreachable in a customer build;
* the output must stay readable, so a human can actually navigate the
  app in this mode rather than only screenshot it.
"""

import os

import pytest

from i18n.pseudo import (
    ENVIRONMENT_FLAG,
    EXPANSION_FACTOR,
    PSEUDO_LANGUAGE,
    build_pseudo_translations,
    is_pseudo_enabled,
    pseudo_localize,
)
from i18n.translator import (
    SHIPPED_LANGUAGES,
    clear_cache,
    normalize_language,
    supported_languages,
    translate,
)


@pytest.fixture
def pseudo_enabled(monkeypatch):
    monkeypatch.setenv(ENVIRONMENT_FLAG, "1")
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def pseudo_disabled(monkeypatch):
    monkeypatch.delenv(ENVIRONMENT_FLAG, raising=False)
    clear_cache()
    yield
    clear_cache()


# ------------------------------------------------------ the flag ---

def test_disabled_by_default(pseudo_disabled):
    assert not is_pseudo_enabled()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_enabled_by_common_truthy_values(monkeypatch, value):
    monkeypatch.setenv(ENVIRONMENT_FLAG, value)
    assert is_pseudo_enabled()


@pytest.mark.parametrize("value", ["0", "false", "no", "", "  "])
def test_not_enabled_by_falsy_values(monkeypatch, value):
    monkeypatch.setenv(ENVIRONMENT_FLAG, value)
    assert not is_pseudo_enabled()


def test_a_customer_build_cannot_reach_the_pseudo_language(pseudo_disabled):
    """
    The property that keeps this a development tool.

    If the pseudo language appeared in a shipped selector, a customer
    could switch their product into ⟦Ĝìƀƀèŕìšĥ⟧ and would reasonably
    conclude it was broken.
    """

    assert PSEUDO_LANGUAGE not in supported_languages()
    assert supported_languages() == SHIPPED_LANGUAGES

    # Even asked for explicitly, it must not resolve.
    assert normalize_language(PSEUDO_LANGUAGE) == "en"


def test_the_pseudo_language_is_selectable_when_enabled(pseudo_enabled):

    assert PSEUDO_LANGUAGE in supported_languages()
    assert normalize_language(PSEUDO_LANGUAGE) == PSEUDO_LANGUAGE


# ------------------------------------------------- transformation ---

def test_text_is_expanded_past_german():
    """
    A layout that survives this survives real translation, rather than
    being borderline at German's typical 30%.
    """

    original = "Create case"
    result = pseudo_localize(original)

    assert len(result) >= len(original) * EXPANSION_FACTOR


def test_text_stays_readable():
    """
    A tester has to be able to use the app in this mode, not just look at
    it. Accented Latin is legible; boxes and question marks are not.
    """

    result = pseudo_localize("Create case")

    for word in ("Çŕèàťè", "çàšè"):
        assert word in result


def test_it_is_obvious_where_a_string_starts_and_ends():
    """
    Brackets make truncation visible: a clipped string is missing its
    closing bracket, which is far easier to spot than guessing whether a
    sentence was meant to be longer.
    """

    result = pseudo_localize("Overdue")

    assert result.startswith("⟦")
    assert result.endswith("⟧")


# -------------------------------------------------- placeholders ---

@pytest.mark.parametrize(
    "template,placeholders",
    [
        ("Due {due_date}", ["{due_date}"]),
        ("{unverified} of {total} rules", ["{unverified}", "{total}"]),
        ("Set by {username} on {timestamp}", ["{username}", "{timestamp}"]),
        ("Due {due_date} — {offset} days {direction} {trigger}",
         ["{due_date}", "{offset}", "{direction}", "{trigger}"]),
    ],
)
def test_placeholders_survive_untouched(template, placeholders):
    """
    The one thing that must not break. Accenting {count} into {çòùñť}
    makes str.format raise KeyError, and a layout tool that crashes the
    page tells you nothing about the layout.
    """

    result = pseudo_localize(template)

    for placeholder in placeholders:
        assert placeholder in result


def test_a_pseudo_localized_string_still_formats(pseudo_enabled):
    """End to end: through the translator, with real arguments."""

    result = translate(
        "obligation_due_on",
        lang=PSEUDO_LANGUAGE,
        due_date="2026-08-15",
        offset=14,
        direction="after",
        trigger="arrival",
    )

    assert "2026-08-15" in result
    assert "{" not in result, "a placeholder was left unsubstituted"


def test_every_shipped_string_survives_pseudo_localization(pseudo_enabled):
    """
    Runs the real English catalogue through the transformation and
    formats every template that has placeholders.

    Catches the case where one string has an unusual placeholder shape
    that the splitter mishandles - which would surface as a crashed page
    on whichever screen uses it.
    """

    import json
    import pathlib
    import re

    english = json.loads(
        (
            pathlib.Path(__file__).resolve().parents[1]
            / "i18n" / "translations" / "en.json"
        ).read_text(encoding="utf-8")
    )

    pseudo = build_pseudo_translations(english)

    assert set(pseudo) == set(english), "keys must be preserved exactly"

    for key, original in english.items():

        names = re.findall(r"\{(\w+)\}", original)

        if not names:
            continue

        arguments = {name: "X" for name in names}

        try:
            pseudo[key].format(**arguments)
        except (KeyError, IndexError, ValueError) as error:
            pytest.fail(
                f"'{key}' cannot be formatted after pseudo-localization: "
                f"{error}\n  original: {original}\n  pseudo:   {pseudo[key]}"
            )


def test_empty_and_non_string_values_pass_through():
    """
    A malformed catalogue entry must not crash the tool that exists to
    find problems.
    """

    assert pseudo_localize("") == ""
    assert pseudo_localize(None) is None
    assert pseudo_localize(42) == 42
