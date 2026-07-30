"""
Every point in the risk score says where it came from.

The weights were hardcoded: +40 for a non-EU national, +60 for an N
permit, +10 for Valais. Each looks researched on its own. None is. The
screen renders their total as "HIGH Risk 100" beside a red badge, and a
customer asking why is owed a better answer than a list of numbers.

This is the same defect that was removed from risk.py when the invented
Vaud weight was deleted - the only difference being that nobody had yet
asked where the survivors came from.

It cannot be fixed by research. No Swiss authority publishes risk weights
for immigration cases, so unlike the statutory deadlines there is no
provision to trace these to. What can be fixed is the pretence: each
weight now declares whether it reflects a documented administrative step
or is operational judgement, and the product can say so.
"""

import json
from pathlib import Path

import pytest

from core.rules.risk import (
    HEURISTIC,
    PROCEDURAL,
    STATUTORY,
    calculate_risk_from_rules,
    score_disclaimer,
)


def case(nationality="NON_EU", canton="VALAIS", permit="B", mode="SME"):
    return (1, "Test", nationality, canton, permit, mode)


WEIGHTS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "risk_weights.json"
)


# ------------------------------------------------------- provenance ---

def test_every_contribution_declares_a_basis():
    """
    A point with no stated basis is indistinguishable from a sourced one,
    which is the whole problem being fixed.
    """

    _, trace = calculate_risk_from_rules(case())

    assert trace["contributions"]

    for item in trace["contributions"]:
        assert item["basis"] in (STATUTORY, PROCEDURAL, HEURISTIC)
        assert item["reason"], f"{item['label']} gives no reason"


def test_the_score_does_not_claim_to_be_sourced():
    """
    is_fully_sourced must be False while any weight is judgement - which
    is all of them. A screen reading this flag decides whether to show the
    number plainly or with the caveat, so a wrong True here is how the
    caveat disappears.
    """

    _, trace = calculate_risk_from_rules(case())

    assert trace["is_fully_sourced"] is False


def test_a_procedural_weight_names_the_step_it_reflects():
    """
    'Procedural' claims a documented administrative step exists. That
    claim needs a source even though the number does not have one.
    """

    weights = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))["weights"]

    for group in weights.values():
        for key, weight in group.items():
            if weight.get("basis") == PROCEDURAL:
                assert weight.get("reason"), key
                assert weight.get("source_url") or "Art." in weight["reason"], (
                    f"{key} is marked procedural but names no source and no "
                    f"provision - which makes it heuristic with a better name"
                )


def test_nothing_claims_to_be_statutory():
    """
    Not a limitation to be fixed later. No authority publishes risk
    weights, so a 'statutory' entry here would be a fabrication with a
    citation attached - worse than the unsourced number it replaced.
    """

    weights = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))["weights"]

    for group in weights.values():
        for key, weight in group.items():
            assert weight.get("basis") != STATUTORY, (
                f"{key} claims statutory basis. If a provision genuinely "
                f"sets this weight, cite it here and delete this test."
            )


def test_the_disclaimer_says_what_the_score_is_not():
    """
    One wording, from one place. A caveat present on one screen and
    absent on another is not a caveat.
    """

    text = score_disclaimer()

    assert "not a legal assessment" in text.lower()
    assert len(text) > 100


# ---------------------------------------------------------- refusal ---

def test_an_unrecognised_value_contributes_nothing_and_appears_nowhere():
    """
    Same refusal as the uncovered canton. Listing a value as considered
    while scoring it zero is the more dangerous half: it implies the
    product had a view.
    """

    _, trace = calculate_risk_from_rules(
        case(permit="UNKNOWN_PERMIT", canton="UNCOVERED")
    )

    labels = " ".join(item["label"] for item in trace["contributions"])

    assert "UNKNOWN_PERMIT" not in labels
    assert "UNCOVERED" not in labels


def test_the_breakdown_keeps_its_original_shape():
    """
    The PDF export, the AI prompts and several screens read this list of
    strings. Changing its shape while moving the weights to data would
    have broken them silently.
    """

    _, trace = calculate_risk_from_rules(case())

    assert all(line.startswith("+") for line in trace["breakdown"])
    assert len(trace["breakdown"]) == len(trace["contributions"])


def test_a_capped_score_says_it_was_capped():
    """
    A total that silently stops at 100 makes two very different cases
    look identical. The trace records the uncapped figure.
    """

    _, trace = calculate_risk_from_rules(
        case(nationality="NON_EU", permit="N", mode="RELOCATION")
    )

    assert trace["total"] == 100
    assert trace["was_capped"] is True
    assert trace["raw_total"] > 100


# ------------------------------------------------------- the data ---

def test_the_file_states_what_the_score_is_not_before_what_it_is():
    """
    The metadata is read by whoever changes a weight next. It has to lead
    with the limitation, because the temptation when editing a number is
    to treat the score as more authoritative than it is.
    """

    meta = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))["_meta"]

    assert meta["what_this_score_is"]
    assert meta["what_this_score_is_not"]
    assert meta["how_to_improve_this"]

    assert "no swiss authority publishes" in (
        meta["what_this_score_is_not"].lower()
    )
