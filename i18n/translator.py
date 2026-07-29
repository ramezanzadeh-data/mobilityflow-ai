"""
Translation lookup with an explicit fallback chain.

Switzerland has four national languages and this product is sold to Swiss
HR and mobility teams, so English-only is a commercial ceiling rather
than a cosmetic gap: a Valais employer works in French, a Zurich one in
German, and neither expects to administer permits in English.

The important design decision here is what happens when a translation is
missing.

The previous implementation returned the *key*::

    translations.get(key, key)      # -> "obligations_header"

With one language that was survivable - a missing key was simply a bug to
fix. With three it is not: a partially translated language would show raw
source identifiers to a customer, and the pressure to ship a language
before it is complete is constant. So lookup falls back to English and
only then to the key. A German user seeing an English sentence has a
product with a gap; a German user seeing ``obligations_header`` has a
product that looks broken.

Coverage therefore becomes a quality measure rather than a crash risk,
and translation_coverage() below reports it.
"""

import json
import os

from i18n.pseudo import PSEUDO_LANGUAGE, is_pseudo_enabled


DEFAULT_LANGUAGE = "en"

# Order matters: the first entry is the fallback for every other
# language, so it must always be the most complete one.
SHIPPED_LANGUAGES = ["en", "de", "fr"]

# Shown in the language selector. Each language is named in itself -
# somebody looking for German is looking for "Deutsch", not "German".
LANGUAGE_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    PSEUDO_LANGUAGE: "⟦Pseudo⟧ (layout test)",
}


def supported_languages():
    """
    Languages a user may select.

    The pseudo language appears only when the environment flag is set, so
    a customer can never reach it. Computed per call rather than at
    import so a test can toggle the flag without reloading the module.
    """

    if is_pseudo_enabled():
        return SHIPPED_LANGUAGES + [PSEUDO_LANGUAGE]

    return list(SHIPPED_LANGUAGES)


# Kept as a module attribute for the call sites that only ever want the
# real languages - translation coverage, the parity tests, the docs.
SUPPORTED_LANGUAGES = SHIPPED_LANGUAGES

# Where the chosen language lives in Streamlit's session. Defined here
# rather than in the view so the UI and this module cannot disagree.
SESSION_KEY = "language"

_I18N_DIR = os.path.dirname(os.path.abspath(__file__))
_TRANSLATIONS_DIR = os.path.join(_I18N_DIR, "translations")

_TRANSLATIONS_CACHE = {}


def _load_language(lang_code):
    """
    Parsed translations for one language, or an empty mapping.

    A missing or malformed file must not raise. A language file that
    fails to load degrades to "everything falls back to English", which
    is a visible but working product; an exception here would take down
    every page in the app.
    """

    if lang_code in _TRANSLATIONS_CACHE:
        return _TRANSLATIONS_CACHE[lang_code]

    # Generated from English rather than read from disk. A checked-in
    # zz.json would drift the moment an English string changed, and would
    # then be exercising a layout nobody ships.
    if lang_code == PSEUDO_LANGUAGE:
        from i18n.pseudo import build_pseudo_translations

        data = build_pseudo_translations(_load_language(DEFAULT_LANGUAGE))
        _TRANSLATIONS_CACHE[lang_code] = data
        return data

    path = os.path.join(_TRANSLATIONS_DIR, f"{lang_code}.json")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

    except (OSError, ValueError):
        data = {}

    _TRANSLATIONS_CACHE[lang_code] = data

    return data


def clear_cache():
    """Drop parsed translations. Used by tests."""

    _TRANSLATIONS_CACHE.clear()


def normalize_language(lang_code):
    """
    Map anything to a supported language code.

    Accepts 'de-CH', 'DE', ' de ' - browsers and stored preferences all
    produce variants, and 'de-CH' in particular is what a Swiss browser
    sends. An unsupported language falls back to the default rather than
    raising: a bad preference must never lock a user out.
    """

    if not lang_code:
        return DEFAULT_LANGUAGE

    code = str(lang_code).strip().lower().replace("_", "-").split("-")[0]

    return code if code in supported_languages() else DEFAULT_LANGUAGE


def set_language(lang_code):
    """
    Record the chosen language for this session.

    Held in Streamlit's session state so it survives every rerun and
    applies to every page without being threaded through call sites.
    Streamlit is imported lazily to keep this module usable from the REST
    API and from tests, neither of which has a session.
    """

    normalized = normalize_language(lang_code)

    try:
        import streamlit as st

        st.session_state[SESSION_KEY] = normalized

    except Exception:  # noqa: BLE001 - no session here; caller passes lang
        pass

    return normalized


def get_lang():
    """
    The language for the current session, defaulting to English.

    Read from the session on every call rather than cached in a module
    global. Streamlit reruns the script on every interaction, potentially
    on a different worker thread, so a module-level cache would leak one
    user's choice into another user's request - the same reasoning that
    makes the tenant context a ContextVar in db.database.
    """

    try:
        import streamlit as st

        return normalize_language(st.session_state.get(SESSION_KEY))

    except Exception:  # noqa: BLE001 - no session (API, worker, test)
        return DEFAULT_LANGUAGE


def translate(key, lang=None, **kwargs):
    """
    Look up ``key``, falling back to English and then to the key itself.

    Args:
        key: Translation key.
        lang: Language code. Defaults to the session language, so call
            sites do not have to thread it through.
        **kwargs: Substituted into the result with str.format.

    A formatting failure returns the unformatted string rather than
    raising. A placeholder that exists in one language but not another is
    a content bug; it should show as odd text, not as a crashed page in
    the middle of a compliance screen.
    """

    language = normalize_language(lang) if lang else get_lang()

    text = _load_language(language).get(key)

    if text is None and language != DEFAULT_LANGUAGE:
        # The reason this function exists: a missing German string shows
        # the English one, never the raw key.
        text = _load_language(DEFAULT_LANGUAGE).get(key)

    if text is None:
        text = key

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass

    return text


def t(key, **kwargs):
    """Shorthand for translate() in the session's language."""

    return translate(key, **kwargs)


def translation_coverage(lang_code):
    """
    How much of the interface exists in one language.

    Returns ``(translated, total, missing_keys)`` measured against
    English, so an incomplete language is a known and quantified state
    rather than something a customer discovers.
    """

    english = _load_language(DEFAULT_LANGUAGE)
    target = _load_language(normalize_language(lang_code))

    missing = sorted(
        key for key in english
        if key not in target or not str(target.get(key, "")).strip()
    )

    return len(english) - len(missing), len(english), missing
