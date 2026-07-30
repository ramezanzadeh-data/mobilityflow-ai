"""
Which cantons this product actually covers.

One definition, derived from the data rather than declared in code: a
canton is supported if and only if there is a knowledge base file for it
in ``data/``. Nothing else decides.

Why it is derived and not a list
--------------------------------
The scope used to be stated in six places - the case form, its default,
the dashboard filter, the validator's vocabulary, the workflow engine and
the risk engine - and they disagreed. The form offered Vaud, the form
defaulted to Vaud, the risk engine added five points for Vaud, and
``core.rules.rules.get_canton_knowledge("VAUD")`` returned ``None``
because no such file had ever existed.

That is worse than not supporting a canton. A case in Vaud produced a
workflow, a risk score and a document checklist that looked exactly as
authoritative as a Valais one, assembled from numbers with no source. For
a product sold on compliance, a confident answer with nothing behind it
is the most expensive kind of wrong: nobody checks it, because nothing
about it looks uncertain.

Deriving the scope from the files makes the two impossible to separate.
Adding ``data/canton_vaud_rules.json`` - reviewed, sourced, with its
verification block filled in - is what makes Vaud selectable. There is no
second step where someone remembers to add it to a list, and no way to
put it in the list and forget the file.

Existing data is never rejected
-------------------------------
Narrowing the scope must not make records already in the database
unreadable. A case created when Vaud was on the menu stays viewable and
editable; only creating a new one is refused. See ``is_selectable`` and
``is_readable`` below - they are deliberately different questions.
"""

import os


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

# data/canton_<code>_rules.json -> the canton code, upper-cased.
_FILENAME_PREFIX = "canton_"
_FILENAME_SUFFIX = "_rules.json"


class CantonNotSupportedError(ValueError):
    """
    Raised when work is requested for a canton with no knowledge base.

    A distinct type rather than a bare ValueError, so a caller can tell
    "we do not cover this canton yet" - which is a product boundary and
    has a real answer for the user - apart from "that input is malformed".
    """

    def __init__(self, canton):
        self.canton = canton
        super().__init__(
            f"No knowledge base for canton {canton!r}. "
            f"Covered: {', '.join(supported_cantons()) or 'none'}."
        )


def supported_cantons():
    """
    Every canton with a knowledge base, sorted.

    Read from disk on each call rather than captured at import. The cost
    is one directory listing, and it means a knowledge base added while a
    developer has the app running takes effect on the next page rather
    than at the next restart - which is how the file gets noticed at all.
    """

    if not os.path.isdir(_DATA_DIR):
        return []

    found = []

    for filename in os.listdir(_DATA_DIR):

        if not filename.startswith(_FILENAME_PREFIX):
            continue

        if not filename.endswith(_FILENAME_SUFFIX):
            continue

        code = filename[len(_FILENAME_PREFIX):-len(_FILENAME_SUFFIX)]

        if code:
            found.append(code.upper())

    return sorted(found)


def is_selectable(canton):
    """
    May a *new* case be created in this canton?

    The narrow question. Answering yes commits the product to producing a
    workflow, a deadline set and a risk score for it, so it is true only
    where there is something to produce them from.
    """

    return bool(canton) and canton.upper() in supported_cantons()


def is_readable(canton):
    """
    May a case already recorded in this canton still be opened?

    Always yes. The record exists; refusing to display it would lose a
    customer's data to a scope decision made afterwards, which is never an
    acceptable trade. What the screens must not do is present derived
    output - deadlines, risk, checklists - as though it were grounded.
    Use ``is_selectable`` to decide that.
    """

    return bool(canton)


def require_supported(canton):
    """
    Return the normalised code, or raise CantonNotSupportedError.

    For paths that are about to compute something a customer may act on.
    Raising is the point: silently returning an empty workflow for an
    unknown canton is how the previous behaviour looked correct.
    """

    if not is_selectable(canton):
        raise CantonNotSupportedError(canton)

    return canton.upper()


def knowledge_base_filename(canton):
    """The data file a canton's knowledge is expected to live in."""

    return f"{_FILENAME_PREFIX}{canton.lower()}{_FILENAME_SUFFIX}"
