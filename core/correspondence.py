"""
Which language a case is corresponded in.

Two languages exist in this product and they answer different questions:

    i18n.translator.get_lang()      what the person at the screen reads
    resolve_correspondence_language()   what a letter must be written in

They were one setting. Everything followed the Streamlit session,
including the emails the product drafts to Swiss authorities, so the
language of a letter to a commune depended on which colleague happened to
open the case.

For the canton this product covers, that is not a rounding error. Valais
is officially bilingual. The lower Valais - Martigny, Monthey, Sion -
administers in French; the Oberwallis - Brig, Visp, Zermatt - administers
in German, and the language boundary runs through the middle of the
canton near Sierre/Siders. A German-speaking mobility manager in Zurich
handling an arrival in Martigny needs a German interface and a French
letter. One setting cannot express that.

The failure is also quiet. A letter in the wrong language is fluent,
correctly formatted, and looks exactly like a correct one; nothing goes
wrong until the commune replies asking for a resubmission, by which time
the fourteen-day registration window has been eating into itself.

Where the answer comes from
---------------------------
In order: the language stored on the case, then the commune's own
administrative language, then the canton default.

The commune step was added once migration 0007 gave cases a commune. It
consults core.communes, which knows only the communes traced to a
published source - three, against more than a hundred in Valais - and
returns nothing for the rest. So it narrows the answer where there is
evidence and never widens the claim: an untraced commune falls through to
the canton default, which the screen still labels as an assumption.

Filling that file in from memory would be the same mistake as the
invented Vaud risk score this codebase already removed: a lookup table
that looks researched and is not.
"""

# The languages this product will generate correspondence in.
#
# English only, by product decision - the same decision that reduced the
# interface to English in i18n/translator.py.
#
# Recorded plainly, because it is a real limitation rather than a
# neutral setting. Swiss authorities conduct business in German, French
# and Italian; a commune in Martigny works in French and one in Brig in
# German. A generated letter in English is not a translation problem for
# the recipient, it is a submission they may return - and the draft will
# look fluent and correctly formatted while that is true, so nothing on
# screen will suggest anything is wrong.
#
# The machinery for the other languages is intact and tested: the prompt
# builders in core/ai/prompts.py still take a language and instruct the
# model in it, cases still carry correspondence_language (migration
# 0006), and this resolver still honours it. Re-enabling is this tuple
# and CANTON_DEFAULT_LANGUAGE below:
#
#     CORRESPONDENCE_LANGUAGES = ("de", "fr", "it", "en")
#     CANTON_DEFAULT_LANGUAGE = {"VALAIS": "fr"}
CORRESPONDENCE_LANGUAGES = ("en",)


# The language a canton's correspondence defaults to.
#
# Valais is officially bilingual - French in the lower canton, German in
# the Oberwallis - so the honest entry here is 'fr' with a per-case
# override, and that is what this held until the product was set to
# English only. Left as an explicit entry rather than deleted, so the
# canton is still named and the decision is visible at the point it takes
# effect.
CANTON_DEFAULT_LANGUAGE = {
    "VALAIS": "en",
}

# Cantons where the default is a coin toss rather than a fact, and the
# user must be told. Listing them explicitly rather than deriving it:
# officially multilingual cantons are a short, stable, checkable set.
CANTON_IS_BILINGUAL = {"VALAIS", "BERN", "FRIBOURG"}

# Used when the canton is unknown and nothing else applies. English is
# not a Swiss administrative language, and a letter written in it would
# be wrong everywhere - but it is the language this product's own
# interface is complete in, so it fails visibly rather than plausibly.
LAST_RESORT_LANGUAGE = "en"


def resolve_correspondence_language(case_language, canton, commune=None):
    """
    The language to write this case's correspondence in.

    Args:
        case_language: The value stored on the case, or None if the user
            has not chosen. NULL is left meaning "not chosen" rather than
            being backfilled - see migration 0006.
        canton: The case's canton, used only for the default.
        commune: The case's commune, if recorded. Preferred over the
            canton default: in a bilingual canton the canton-level answer
            is a coin toss and the commune's is a fact. Unknown communes
            return nothing rather than a guess, so this narrows the
            answer where it can and never widens the claim.

    Returns:
        A language code from CORRESPONDENCE_LANGUAGES.

    An unrecognised stored value falls through to the canton default
    rather than being passed on. The value reaches an LLM prompt as
    "write this in {language}", and a code nobody recognises produces a
    letter in a language nobody at the commune reads.
    """

    if case_language and case_language in CORRESPONDENCE_LANGUAGES:
        return case_language

    # The commune knows better than the canton wherever it is known.
    # core.communes returns None for anything not traced to a published
    # source, so this can only ever narrow the answer.
    if commune:

        from core.communes import commune_language

        language = commune_language(commune)

        if language in CORRESPONDENCE_LANGUAGES:
            return language

    if canton:
        default = CANTON_DEFAULT_LANGUAGE.get(canton.upper())

        if default in CORRESPONDENCE_LANGUAGES:
            return default

    return LAST_RESORT_LANGUAGE


def is_using_a_default(case_language, canton):
    """
    Whether the language above was assumed rather than chosen.

    The screen uses this to say so. An assumption a user cannot see is an
    assumption they cannot correct, and this one is wrong for every
    Oberwallis case until somebody changes it.
    """

    return not (case_language and case_language in CORRESPONDENCE_LANGUAGES)


def needs_an_explicit_choice(canton):
    """
    Whether leaving this to the default is a real risk for this canton.

    True in an officially multilingual canton, where the default is right
    for part of it and wrong for the rest. The form uses this to prompt
    rather than to block: refusing to save a case without a language would
    obstruct the common path for the sake of the uncommon one.
    """

    return bool(canton) and canton.upper() in CANTON_IS_BILINGUAL
