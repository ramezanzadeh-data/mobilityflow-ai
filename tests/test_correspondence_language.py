"""
Correspondence goes out in the language of the authority, not the user.

There was one language setting - the Streamlit session - and everything
followed it, including the emails and letters this product drafts for
Swiss authorities. Two separate consequences:

  * the prompts were English, so the model replied in English whatever
    the user had selected. Choosing French translated the buttons around
    an English letter.

  * even once the prompts took a language, taking it from the session
    would mean the letter followed whoever happened to open the case.

For the canton this product covers, the second is not hypothetical.
Valais is officially bilingual: the lower Valais administers in French,
the Oberwallis in German. A German-speaking mobility manager in Zurich
handling an arrival in Martigny needs a German interface and a French
letter, and one setting cannot express that.

The failure mode is what makes it worth pinning. A letter in the wrong
language is fluent, correctly formatted and indistinguishable from a
correct one. Nothing goes wrong until the commune replies asking for a
resubmission - by which point the fourteen-day registration window has
been running.
"""

import pytest

from core.ai.prompts import (
    build_checklist_prompt,
    build_email_prompt,
    build_letter_prompt,
    build_document_classification_prompt,
    build_defect_detection_prompt,
)
from core.correspondence import (
    CANTON_DEFAULT_LANGUAGE,
    CORRESPONDENCE_LANGUAGES,
    LAST_RESORT_LANGUAGE,
    is_using_a_default,
    needs_an_explicit_choice,
    resolve_correspondence_language,
)


# ---------------------------------------------------------- resolution ---

def test_correspondence_is_currently_english_only():
    """
    The shipped configuration, asserted rather than assumed.

    This is a product decision and a real limitation: Swiss authorities
    work in German, French and Italian. Pinned here so that turning the
    languages back on is a deliberate change with a failing test to
    update, not something that drifts.
    """

    assert CORRESPONDENCE_LANGUAGES == ("en",)

    assert resolve_correspondence_language(None, "VALAIS") == "en"
    assert resolve_correspondence_language("fr", "VALAIS") == "en", (
        "a case still carrying a French correspondence language must not "
        "produce a French letter while the product ships English only - "
        "half the output in a language nobody configured is worse than "
        "all of it in the wrong one"
    )


def test_a_language_that_is_shipped_is_honoured_when_stored():
    """
    The mechanism, independent of the current configuration.

    resolve_correspondence_language() is still the place a per-case
    language takes effect; only the set it may choose from has been
    reduced. This is what re-enabling German and French will rely on.
    """

    only_language = CORRESPONDENCE_LANGUAGES[0]

    assert resolve_correspondence_language(only_language, "VALAIS") == (
        only_language
    )


def test_the_canton_default_applies_when_the_case_says_nothing():

    assert resolve_correspondence_language(None, "VALAIS") == (
        CANTON_DEFAULT_LANGUAGE["VALAIS"]
    )


def test_an_unknown_canton_falls_back_rather_than_guessing():

    assert resolve_correspondence_language(None, "UNCOVERED") == (
        LAST_RESORT_LANGUAGE
    )


@pytest.mark.parametrize("stored", ["xx", "klingon", "", "  ", "FR-fr", None])
def test_an_unrecognised_stored_language_never_reaches_the_prompt(stored):
    """
    The value is interpolated into "write the entire output in {name}".
    A code nobody recognises produces a confident letter in something,
    and the person reviewing the draft has no way to know what went
    wrong - they cannot read it either.
    """

    resolved = resolve_correspondence_language(stored, "VALAIS")

    assert resolved in CORRESPONDENCE_LANGUAGES


def test_every_canton_default_is_a_language_we_can_write_in():
    """
    A canton defaulting to a language the product will not generate
    would produce correspondence in something nobody chose.
    """

    for canton, language in CANTON_DEFAULT_LANGUAGE.items():
        assert language in CORRESPONDENCE_LANGUAGES, (
            f"{canton} defaults to {language!r}, which is not a language this "
            f"product can generate correspondence in"
        )


# ------------------------------------------------------ visible defaults ---

def test_a_default_is_reported_as_a_default():
    """
    An assumption the user cannot see is one they cannot correct.

    Both cases below are defaults while the product ships English only:
    a case that stored nothing, and a case that stored French - because
    French is no longer a language the product will write in, so that
    stored value is not being honoured either. Reporting the second as a
    deliberate choice would tell the user their setting is in effect when
    it is not.
    """

    assert is_using_a_default(None, "VALAIS")
    assert is_using_a_default("fr", "VALAIS")

    # A language that is shipped, and stored, is not a default.
    assert not is_using_a_default(CORRESPONDENCE_LANGUAGES[0], "VALAIS")


def test_valais_is_flagged_as_needing_an_explicit_choice():
    """
    Prompting, not blocking. Refusing to save a case without a language
    would obstruct the common path for the sake of the uncommon one.
    """

    assert needs_an_explicit_choice("VALAIS")
    assert not needs_an_explicit_choice("UNCOVERED")


# ------------------------------------------------------------- prompts ---

@pytest.mark.parametrize(
    "language,expected_name",
    [("de", "Deutsch"), ("fr", "Français"), ("en", "English")],
)
def test_correspondence_prompts_name_the_output_language(
    language, expected_name
):
    """
    Named in the language's own name rather than as an ISO code.
    "Antwort auf Deutsch" is followed more reliably than "answer in de".
    """

    prompts = [
        build_email_prompt("Anna Müller", "VALAIS", "Register", language=language),
        build_checklist_prompt("Anna Müller", ["Step"], language=language),
        build_letter_prompt(
            "Anna Müller", "EU", "VALAIS", "B", "Lonza AG", 20,
            {"breakdown": []}, ["Step"], language=language,
        ),
    ]

    for prompt in prompts:
        assert expected_name in prompt


def test_correspondence_prompts_forbid_leaving_part_of_it_in_english():
    """
    Stated as a prohibition as well as an instruction, because a model
    given English instructions and asked for French routinely returns a
    French body with an English subject line - and a half-translated
    letter to an authority reads worse than an English one.
    """

    prompt = build_email_prompt(
        "Anna Müller", "VALAIS", "Register", language="fr"
    )

    assert "subject line" in prompt.lower()
    assert "do not leave any part in english" in prompt.lower()


def test_an_unknown_language_code_does_not_reach_the_model():

    prompt = build_email_prompt(
        "Anna Müller", "VALAIS", "Register", language="klingon"
    )

    assert "klingon" not in prompt.lower()
    assert "English" in prompt


@pytest.mark.parametrize(
    "builder,arguments",
    [
        (build_document_classification_prompt, ("some extracted text",)),
        (build_defect_detection_prompt, ("some text", "Passport")),
    ],
)
def test_analytical_prompts_take_no_language(builder, arguments):
    """
    The line: if it goes to an authority it takes a language, if it comes
    back into the product it does not.

    These return structured data - a JSON document type, a list of
    defects - consumed by code. Asking for structured output in a
    language the instructions are not written in is how schema-conforming
    replies stop conforming, and the result is read by a specialist who
    already has a translated interface around it.
    """

    import inspect

    assert "language" not in inspect.signature(builder).parameters

    # And still produce a prompt, so this is a design choice rather than
    # a builder that was missed.
    assert builder(*arguments)
