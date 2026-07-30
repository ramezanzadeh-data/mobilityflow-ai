"""
Per-commune practice, where it differs from the canton.

Two things this product computes turn out to be properties of the
commune rather than the canton, and both were found by tracing the
obligation rules to their published sources:

* **Renewal windows.** General cantonal guidance says a permit renewal
  may be filed at the earliest three months before expiry. Sierre
  publishes two months. Grimisuat states applications are filed fourteen
  days before expiry. These are not the same rule, and the single -90 day
  offset the engine used is wrong for at least two of the three.

* **Correspondence language.** Valais is officially bilingual and the
  boundary runs through the middle of the canton. Which language a letter
  to the Contrôle des habitants must be written in is decided by where
  the case registers.

What this module refuses to do
------------------------------
It knows three communes. Valais has more than a hundred. The rest are
absent, and an absent commune returns None - not a canton default
dressed up as a commune answer.

That restraint is the whole design. Filling the file in from inference
would produce a registry that looks researched and is not, which is
precisely the defect removed from this codebase when the invented Vaud
risk score was deleted. "We do not know this commune's window" is a true
statement a user can act on and a specialist can close in one call. A
plausible wrong number is neither.
"""

import json
import os


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

COMMUNE_DATA_FILE = "canton_valais_communes.json"

_CACHE = None


def _load():

    global _CACHE

    if _CACHE is not None:
        return _CACHE

    path = os.path.join(_DATA_DIR, COMMUNE_DATA_FILE)

    if not os.path.exists(path):
        _CACHE = {"communes": []}
        return _CACHE

    with open(path, "r", encoding="utf-8") as handle:
        _CACHE = json.load(handle)

    return _CACHE


def clear_cache():
    """Drop the cached file. For tests that rewrite it."""

    global _CACHE
    _CACHE = None


def _normalise(name):
    """Comparable form of a commune name: case and spacing only."""

    return " ".join(str(name or "").split()).strip().lower()


def find_commune(name):
    """
    The record for a commune, or None if it is not one we have traced.

    Matches the name and its aliases, so "Siders" finds Sierre - the
    German exonym is what a German-speaking user will type for the same
    place, and treating them as different communes would silently produce
    two different answers for one office.
    """

    target = _normalise(name)

    if not target:
        return None

    for commune in _load().get("communes", []):

        if _normalise(commune.get("name")) == target:
            return commune

        for alias in commune.get("aliases", []):
            if _normalise(alias) == target:
                return commune

    return None


def known_communes():
    """Every commune traced to a source, by name."""

    return sorted(
        commune["name"] for commune in _load().get("communes", [])
    )


def renewal_window_days(commune_name):
    """
    How many days before expiry this commune opens its renewal window.

    None when the commune is unknown *or* known but unresolved - Monthey
    is listed with a null window on purpose. Both mean the same thing to
    a caller: do not compute a renewal date from a canton-level guess.
    """

    commune = find_commune(commune_name)

    return commune.get("renewal_window_days") if commune else None


def commune_language(commune_name):
    """
    The language this commune administers in, or None if unknown.

    Read by core/correspondence.py in preference to the canton default,
    because the canton default is a coin toss in a bilingual canton and
    this is not.
    """

    commune = find_commune(commune_name)

    return commune.get("official_language") if commune else None


def explain(commune_name):
    """
    What the product knows about this commune, for display.

    Returns a dict with ``known``, ``window``, ``language``, ``source_url``
    and ``note``. The note is what a user reads when the answer is "we do
    not know" - an unexplained blank is the one thing this whole file
    exists to avoid.
    """

    commune = find_commune(commune_name)

    if commune is None:
        return {
            "known": False,
            "window": None,
            "language": None,
            "source_url": None,
            "note": (
                "This commune has not been traced to a published source. "
                "Renewal windows differ between Valais communes - two "
                "months in Sierre, fourteen days in Grimisuat - so no "
                "deadline is computed from the canton default."
            ),
        }

    verification = commune.get("verification", {})

    return {
        "known": True,
        "window": commune.get("renewal_window_days"),
        "language": commune.get("official_language"),
        "source_url": verification.get("source_url"),
        "note": commune.get("renewal_note") or verification.get("note", ""),
    }
