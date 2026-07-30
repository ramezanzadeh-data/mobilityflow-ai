"""
Case complexity scoring, with every weight declaring where it came from.

What changed and why
--------------------
The weights were hardcoded here: +40 for a non-EU national, +60 for an N
permit, +10 for Valais, +20 for a relocation mandate. Read one at a time
each looks researched. None of them is. They are operational judgement,
and the screen renders their total as **HIGH Risk 100** beside a red
badge with nothing to say so.

That is the same defect that was removed from this file when the invented
Vaud weight was deleted - the difference being only that nobody had asked
where the other numbers came from yet. A customer who asks "why is this
case 100?" is owed an answer, and "those are the numbers we chose" is
acceptable *only if the product says so on the same screen*.

So the weights moved to data/risk_weights.json, where each one carries a
``basis``:

    statutory   traceable to a named provision
    procedural  reflects a documented administrative step; the step is
                sourced, the number attached to it is not
    heuristic   neither the step nor the number is sourced

Nothing in the file is statutory, and that is not an oversight. No Swiss
authority publishes risk weights for immigration cases, so unlike the
statutory deadlines in obligations.json these cannot be researched into
being defensible - there is no provision to trace them to.

What the score is, and is not
-----------------------------
It is a complexity and attention indicator for sorting a caseload: which
files involve more authorities, more approval layers, more that can go
wrong procedurally. It is not a legal assessment, not a probability of
refusal, and not a compliance verdict.

The trace returned by calculate_risk_from_rules() now carries that
distinction per line, so a caller can show it rather than presenting
judgement and procedure as the same kind of fact.

The defensible successor
------------------------
A composite score cannot be made checkable, because the composition is
the judgement. What can be checked is a count of concrete conditions -
three required documents missing, two deadlines uncomputable because the
arrival date is not recorded, one obligation overdue, permit expiring in
17 days. Every one of those a customer can dispute by pointing at data.

That is where this should end up. Until then, the score stays and says
what it is.
"""

import json
import os


_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

WEIGHTS_FILE = "risk_weights.json"

MAXIMUM_SCORE = 100

# Basis values, in descending order of how much they can be defended.
STATUTORY = "statutory"
PROCEDURAL = "procedural"
HEURISTIC = "heuristic"

_CACHE = None


def clear_cache():
    """Drop the cached weights. For tests that rewrite the file."""

    global _CACHE
    _CACHE = None


def _weights():

    global _CACHE

    if _CACHE is not None:
        return _CACHE

    path = os.path.join(_DATA_DIR, WEIGHTS_FILE)

    with open(path, "r", encoding="utf-8") as handle:
        _CACHE = json.load(handle)

    return _CACHE


def _lookup(group, key):
    """One weight, or None if this value has no entry."""

    if not key:
        return None

    return _weights()["weights"].get(group, {}).get(key)


def calculate_risk_from_rules(case):
    """
    Score a case for complexity, and explain every point of it.

    Returns ``(score, trace)``. The trace is::

        {
            "total": int,
            "breakdown": [str, ...],        # unchanged, for existing callers
            "contributions": [
                {
                    "points": int,
                    "label": str,
                    "basis": "statutory" | "procedural" | "heuristic",
                    "reason": str,
                    "source_url": str | None,
                },
                ...
            ],
            "basis_summary": {"procedural": int, "heuristic": int, ...},
            "is_fully_sourced": bool,
        }

    ``breakdown`` is kept in its original shape because the PDF export,
    the AI prompts and several screens read it. ``contributions`` is what
    a screen should use to show a customer why the number is what it is.

    A value with no entry contributes nothing and appears nowhere - the
    same refusal applied to uncovered cantons. Silently scoring an
    unrecognised permit at zero while listing it as considered would be
    the more dangerous half of that.
    """

    nationality = case[2]
    canton = case[3]
    permit = case[4]
    business_mode = case[5]

    contributions = []

    for group, key in (
        ("nationality", nationality),
        ("permit", permit),
        ("canton", (canton or "").upper() or None),
        ("business_mode", business_mode),
    ):
        weight = _lookup(group, key)

        if weight:
            contributions.append({
                "points": weight["points"],
                "label": weight["label"],
                "basis": weight.get("basis", HEURISTIC),
                "reason": weight.get("reason", ""),
                "source_url": weight.get("source_url"),
            })

    raw_total = sum(item["points"] for item in contributions)

    score = min(raw_total, MAXIMUM_SCORE)

    basis_summary = {}

    for item in contributions:
        basis_summary[item["basis"]] = basis_summary.get(item["basis"], 0) + 1

    trace = {
        "total": score,
        # Unchanged shape: "+40 Non-EU/EFTA national".
        "breakdown": [
            f"+{item['points']} {item['label']}" for item in contributions
        ],
        "contributions": contributions,
        "basis_summary": basis_summary,
        # True only if every contributing weight is traceable to a
        # provision. Currently always False, and the screen should say so
        # rather than let a red badge imply otherwise.
        "is_fully_sourced": bool(contributions) and all(
            item["basis"] == STATUTORY for item in contributions
        ),
        # Kept so a caller can show "capped at 100" rather than a total
        # that silently stops moving.
        "raw_total": raw_total,
        "was_capped": raw_total > MAXIMUM_SCORE,
    }

    return score, trace


def score_disclaimer():
    """
    The sentence that must accompany the number wherever it is shown.

    Provided here rather than written into each screen so there is one
    wording, and so it cannot be omitted from one place and present in
    another - which is how a caveat stops being a caveat.
    """

    return _weights()["_meta"]["what_this_score_is_not"]
