"""
Checking that generated text came back in the language we asked for.

``core/ai/prompts.py`` instructs the model twice - name the language, and
do not leave any part in English. A large model follows that. The model
this product runs locally does not always, and the failure is specific:
a prompt dense with "Switzerland", "canton VALAIS" and "Contrôle des
habitants" pulls a small model towards German or French regardless of the
instruction.

That produced a real report from a user: the interface was set to
English, the case resolved to English, and Generate Email returned
German.

Why this is checked in code rather than fixed in the prompt
-----------------------------------------------------------
Because it cannot be fixed in the prompt with certainty. An instruction
is a request; a smaller model will sometimes decline. The output is
fluent, correctly formatted and looks exactly like a correct draft, so
nothing about it prompts the user to look twice - and if they cannot
read the language, they cannot tell at all.

So the product checks its own output and says when it does not match. It
does not silently retranslate: a draft the user is about to send to an
authority should not be quietly rewritten by the same component that got
it wrong.

What this is not
----------------
A language identifier. It is a smoke alarm built from function-word
counts, and it is documented as one:

* short texts are unreliable - a two-line note has too few function words
  to be conclusive, so this abstains rather than guessing;
* proper nouns and Swiss administrative terms appear in every language
  here, so they are excluded from the evidence;
* it distinguishes only the languages this product generates.

Abstaining is the designed behaviour when the evidence is thin. A false
warning on a correct draft teaches the user to ignore warnings, which
costs more than the one it would have caught.
"""

import re


# Function words, which are the useful signal: they are frequent, short,
# and almost never shared between these three languages. Content words
# are excluded deliberately - "permit", "document" and "canton" appear in
# all three in this domain and would only add noise.
_MARKERS = {
    "en": {
        "the", "and", "of", "to", "is", "this", "with", "for", "that",
        "your", "we", "have", "please", "will", "be", "are", "in", "as",
    },
    "de": {
        "der", "die", "das", "und", "ist", "mit", "für", "sich", "nicht",
        "wir", "sie", "wird", "den", "dem", "ein", "eine", "bitte",
        "sehr", "geehrte", "freundlichen", "grüssen", "haben",
    },
    "fr": {
        "le", "la", "les", "et", "de", "des", "est", "pour", "avec",
        "dans", "nous", "vous", "une", "un", "du", "que", "veuillez",
        "cordialement", "madame", "monsieur", "votre",
    },
}

# Below this, the sample is too small for the counts to mean anything.
# A subject line alone would otherwise be classified confidently and
# wrongly.
MINIMUM_WORDS = 25

# How far ahead the leading language must be before this reports a
# mismatch. Set high on purpose: a draft in the right language that
# happens to quote a French office name should not raise an alarm, and a
# warning that fires on correct output is a warning people learn to
# dismiss.
MINIMUM_MARGIN = 2.0


def _counts(text):

    words = re.findall(r"\b[\w'äöüéèàçÄÖÜÉÈÀÇ]+\b", (text or "").lower())

    return words, {
        language: sum(1 for word in words if word in markers)
        for language, markers in _MARKERS.items()
    }


def detect_language(text):
    """
    The language this text appears to be in, or None if unclear.

    None means "not enough evidence", not "unknown language". Callers
    treat it as "no opinion" and say nothing to the user.
    """

    words, counts = _counts(text)

    if len(words) < MINIMUM_WORDS:
        return None

    ranked = sorted(counts.items(), key=lambda pair: -pair[1])

    best, best_count = ranked[0]
    _, runner_up_count = ranked[1]

    if best_count == 0:
        return None

    # Ahead by a clear margin, not merely ahead. A one-word lead is noise.
    if best_count < max(runner_up_count * MINIMUM_MARGIN, 3):
        return None

    return best


# Closing formulas, which a model reaches for even when the rest of the
# letter is in the requested language. "Mit freundlichen Grüßen" at the
# foot of an otherwise English email is not caught by counting function
# words - the English wins the count easily - but it is exactly what a
# recipient notices first.
#
# Note the ß in the German entries. Swiss standard German does not use
# it, so its presence is doubly wrong here: wrong language, and the
# German-from-Germany spelling of it. Both spellings are listed because
# the point is to detect the phrase, not to grade it.
_CLOSING_FORMULAS = {
    "de": [
        "mit freundlichen grüßen",
        "mit freundlichen grüssen",
        "sehr geehrte damen und herren",
        "hochachtungsvoll",
        "beste grüße",
        "beste grüsse",
    ],
    "fr": [
        "veuillez agréer",
        "cordialement",
        "meilleures salutations",
        "salutations distinguées",
        "madame, monsieur",
    ],
    "it": ["distinti saluti", "cordiali saluti"],
}


def foreign_phrases(text, expected):
    """
    Fixed phrases from a language other than the requested one.

    Separate from detect_language() because the failure is different in
    kind: the letter is in the right language and one formula is not.
    Counting function words cannot see it - the correct language wins the
    count - yet a German sign-off on an English letter is the first thing
    a reader notices.

    Returns a list of (language, phrase) for whatever was found.
    """

    if not text or not expected:
        return []

    lowered = text.lower()

    return [
        (language, phrase)
        for language, phrases in _CLOSING_FORMULAS.items()
        if language != expected
        for phrase in phrases
        if phrase in lowered
    ]


def looks_like_the_wrong_language(text, expected):
    """
    Whether generated text is confidently in a language we did not ask for.

    False when the check has no opinion. The question this answers is
    "should we warn the user?", and the honest answer to thin evidence is
    no.
    """

    if not expected:
        return False

    # A foreign closing formula is conclusive on its own. "Mit
    # freundlichen Grüßen" is not a word that happens to appear in
    # English text; it is a German sign-off, and one is enough.
    if foreign_phrases(text, expected):
        return True

    detected = detect_language(text)

    return detected is not None and detected != expected
