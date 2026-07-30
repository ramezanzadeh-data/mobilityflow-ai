"""
Generated correspondence has to come back in the language we asked for.

Reported directly: the interface was English, the case resolved to
English, and Generate Email returned German. The prompt says the language
twice and forbids leaving any part in English; a small local model
declines anyway, pulled towards German by a prompt full of "Switzerland",
"canton VALAIS" and "Contrôle des habitants".

An instruction is a request. So the product checks its own output.

The tests below hold the two halves of that, and the second matters more
than the first: this must not warn about correct drafts. A check that
cries wolf gets dismissed, and then it is worth less than nothing -
people learn to click past the one warning that was real.
"""

import pytest

from core.communication.language_check import (
    MINIMUM_WORDS,
    detect_language,
    looks_like_the_wrong_language,
)


ENGLISH = """
Dear Sir or Madam, we are writing to you with regard to the residence
permit application for our employee. We have enclosed the documents that
are required for this application and we would be grateful if you would
confirm receipt of them. Please do not hesitate to contact us if any
further information is needed for the file.
"""

GERMAN = """
Sehr geehrte Damen und Herren, wir schreiben Ihnen bezüglich des Gesuchs
um eine Aufenthaltsbewilligung für unsere Mitarbeiterin. Wir haben die
Unterlagen beigelegt, die für dieses Gesuch erforderlich sind, und wir
wären Ihnen dankbar, wenn Sie den Erhalt bestätigen würden. Bitte melden
Sie sich, wenn weitere Angaben nötig sind.
"""

FRENCH = """
Madame, Monsieur, nous vous écrivons au sujet de la demande
d'autorisation de séjour pour notre collaboratrice. Nous avons joint les
documents qui sont nécessaires pour cette demande et nous vous serions
reconnaissants de bien vouloir en accuser réception. Veuillez nous
contacter si des informations complémentaires vous sont utiles.
"""


# ------------------------------------------------------------ detection ---

@pytest.mark.parametrize(
    "text,expected",
    [(ENGLISH, "en"), (GERMAN, "de"), (FRENCH, "fr")],
)
def test_a_full_letter_is_identified(text, expected):
    assert detect_language(text) == expected


def test_the_reported_failure_is_caught():
    """
    The exact case: English requested, German returned.
    """

    assert looks_like_the_wrong_language(GERMAN, "en") is True


@pytest.mark.parametrize(
    "text,expected", [(ENGLISH, "en"), (GERMAN, "de"), (FRENCH, "fr")]
)
def test_a_correct_draft_never_warns(text, expected):
    """
    The property that keeps the warning worth reading.
    """

    assert looks_like_the_wrong_language(text, expected) is False


# ----------------------------------------------------------- abstaining ---

def test_a_short_text_is_not_judged():
    """
    A subject line has too few function words to mean anything, and
    guessing on it would produce confident nonsense.
    """

    assert detect_language("Subject: residence permit") is None
    assert looks_like_the_wrong_language("Subject: residence permit", "en") is False


def test_the_minimum_is_a_real_threshold_not_a_formality():
    """
    Guards the constant. Set to something tiny, the check would classify
    fragments and warn on correct drafts.
    """

    assert MINIMUM_WORDS >= 15


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_output_is_not_judged(text):
    assert detect_language(text) is None
    assert looks_like_the_wrong_language(text, "en") is False


def test_swiss_place_and_office_names_do_not_trigger_a_warning():
    """
    An English letter naming a French-speaking office is still an English
    letter. Function words carry the signal; the proper nouns in this
    domain are French or German in every language and would otherwise
    make every correct English draft look French.
    """

    text = (
        "Dear Sir or Madam, we are writing with regard to the registration "
        "of our employee at the Contrôle des habitants in Martigny, in the "
        "canton of Valais. We have enclosed the documents that are required "
        "and we would be grateful for your confirmation that the file is "
        "complete for the Service de la population et des migrations."
    )

    assert detect_language(text) == "en"
    assert looks_like_the_wrong_language(text, "en") is False


def test_no_opinion_is_given_when_the_evidence_is_mixed():
    """
    Abstaining is the designed answer to thin evidence, not a gap.
    """

    mixed = " ".join(["the und le das and la der et"] * 6)

    assert detect_language(mixed) is None


def test_nothing_is_expected_means_nothing_is_warned():

    assert looks_like_the_wrong_language(GERMAN, None) is False
    assert looks_like_the_wrong_language(GERMAN, "") is False
