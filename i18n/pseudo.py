"""
Pseudo-localization: a generated language for finding layout bugs.

German runs roughly 30% longer than English, and Swiss immigration
vocabulary is worse than that - "Permit C (Settlement)" becomes
"Ausweis C (Niederlassung)", and "Aufenthaltsbewilligung" is a single
word longer than most English button labels.

Polishing every screen against English and adding German afterwards would
reintroduce exactly the failures this project already spent a week
fixing: text wrapping one character per line, buttons breaking across
five rows, a risk badge clipped to "🔺 H". Those were all English text in
a container sized for English text.

Pseudo-localization finds them now, without waiting for a translator. It
takes each English string and:

* **expands it** by roughly 40% - past German's typical 30%, so a layout
  that survives this survives real translation;
* **accents the letters** - "Çŕèàťè çàšè" is still readable, so a human
  can navigate the app, but anything left in plain ASCII on screen is
  instantly visible as a string that never went through t();
* **brackets it** - a truncated or clipped string is obvious, because the
  closing bracket is missing.

Placeholders such as ``{count}`` are passed through untouched. Corrupting
them would break str.format and turn a layout test into a crash.

Enabled with MOBILITYFLOW_PSEUDO_LOCALE=1. Off by default and never
offered in the language selector - this is a development tool, not a
language, and a customer must never be able to reach it.
"""

import os


PSEUDO_LANGUAGE = "zz"

ENVIRONMENT_FLAG = "MOBILITYFLOW_PSEUDO_LOCALE"

# 1.4 rather than 1.3: the point is to clear German with margin, so that
# passing here means real translation is safe rather than borderline.
EXPANSION_FACTOR = 1.4

PADDING_CHARACTER = "–"   # en dash: visible, and clearly not a letter

PREFIX = "⟦"              # ⟦
SUFFIX = "⟧"              # ⟧

# Latin letters mapped to accented equivalents of the same width. Chosen
# to stay legible: a tester has to be able to use the app in this mode,
# not just look at it.
_ACCENTS = str.maketrans({
    "a": "à", "b": "ƀ", "c": "ç", "d": "ď", "e": "è", "f": "ƒ", "g": "ĝ",
    "h": "ĥ", "i": "ì", "j": "ĵ", "k": "ķ", "l": "ĺ", "m": "ɱ", "n": "ñ",
    "o": "ò", "p": "ƥ", "q": " q", "r": "ŕ", "s": "š", "t": "ť", "u": "ù",
    "v": "ṽ", "w": "ŵ", "x": "ẋ", "y": "ý", "z": "ž",
    "A": "À", "B": "Ɓ", "C": "Ç", "D": "Ď", "E": "È", "F": "Ƒ", "G": "Ĝ",
    "H": "Ĥ", "I": "Ì", "J": "Ĵ", "K": "Ķ", "L": "Ĺ", "M": "Ṁ", "N": "Ñ",
    "O": "Ò", "P": "Ƥ", "Q": "Q", "R": "Ŕ", "S": "Š", "T": "Ť", "U": "Ù",
    "V": "Ṽ", "W": "Ŵ", "X": "Ẋ", "Y": "Ý", "Z": "Ž",
})


def is_pseudo_enabled():
    """
    Whether pseudo-localization is switched on.

    Read from the environment on every call rather than captured at
    import, so it can be toggled in a test without reloading the module.
    """

    return os.environ.get(ENVIRONMENT_FLAG, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _split_preserving_placeholders(text):
    """
    Split into segments, marking which are ``{placeholders}``.

    Yields ``(segment, is_placeholder)``. Placeholders must survive
    untouched: accenting ``{count}`` into ``{çòùñť}`` would make
    str.format raise KeyError, and a layout tool that crashes the page
    tells you nothing about the layout.
    """

    segment = ""
    depth = 0

    for character in text:

        if character == "{":
            if depth == 0 and segment:
                yield segment, False
                segment = ""
            depth += 1
            segment += character

        elif character == "}":
            segment += character
            depth -= 1
            if depth == 0:
                yield segment, True
                segment = ""

        else:
            segment += character

    if segment:
        # An unbalanced brace means malformed source text; pass it
        # through rather than guessing at what was meant.
        yield segment, depth == 0 and segment.startswith("{")


def pseudo_localize(text):
    """
    Turn one English string into its pseudo-localized form.

    Non-string input is returned unchanged - translation files should
    only hold strings, but a report that crashes on a stray number would
    hide the layout problems this exists to reveal.
    """

    if not isinstance(text, str) or not text:
        return text

    accented = "".join(
        segment if is_placeholder else segment.translate(_ACCENTS)
        for segment, is_placeholder in _split_preserving_placeholders(text)
    )

    # Padding is sized on the visible text only. Including placeholders
    # would over-pad strings whose runtime value is short, exaggerating
    # the width and producing layout fixes for a problem that does not
    # exist.
    visible_length = sum(
        len(segment)
        for segment, is_placeholder in _split_preserving_placeholders(text)
        if not is_placeholder
    )

    padding_length = max(1, int(visible_length * (EXPANSION_FACTOR - 1)))

    return f"{PREFIX}{accented}{PADDING_CHARACTER * padding_length}{SUFFIX}"


def build_pseudo_translations(english):
    """
    Generate the whole pseudo language from the English catalogue.

    Generated rather than stored: a checked-in zz.json would drift the
    moment an English string changed, and would then be testing a layout
    nobody ships.
    """

    return {key: pseudo_localize(value) for key, value in english.items()}
