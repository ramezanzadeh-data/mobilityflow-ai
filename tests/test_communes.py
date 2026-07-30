"""
Renewal windows and correspondence language are commune properties.

Found by tracing the obligation rules to their sources rather than by
anyone asking for the field. Three Valais communes publish three
different renewal windows:

    general cantonal guidance   3 months before expiry
    Sierre                      2 months
    Grimisuat                   14 days

The engine used a single -90 day offset, which is therefore wrong for at
least two of them - and wrong in the direction that tells a customer they
still have time when they do not.

The property these tests defend hardest is the refusal: an unknown
commune returns None, never a canton-level default wearing a commune's
name. Valais has more than a hundred communes and three are traced. A
registry filled in from inference would look researched and would not be,
which is the defect this codebase already removed once when the invented
Vaud risk score was deleted.
"""

import json
from pathlib import Path

import pytest

from core.communes import (
    commune_language,
    explain,
    find_commune,
    known_communes,
    renewal_window_days,
)


# ------------------------------------------------------------ lookup ---

def test_a_traced_commune_is_found():
    assert find_commune("Sierre") is not None


@pytest.mark.parametrize("name", ["sierre", "SIERRE", "  Sierre  "])
def test_lookup_ignores_case_and_spacing(name):
    """
    The name arrives from a free-text field. Spacing is not a different
    commune.
    """

    assert find_commune(name)["name"] == "Sierre"


def test_the_german_exonym_finds_the_same_commune():
    """
    Siders is Sierre. A German-speaking user types one and a French-
    speaking colleague types the other for the same office; treating them
    as different communes would produce two different answers for one
    place.
    """

    assert find_commune("Siders")["name"] == "Sierre"


@pytest.mark.parametrize("name", [None, "", "   ", "Zermatt", "Paris"])
def test_an_untraced_commune_is_not_found(name):
    assert find_commune(name) is None


# ------------------------------------------------- the refusal itself ---

def test_the_published_windows_actually_differ():
    """
    The finding, asserted. If these ever became equal, the per-commune
    field would be unnecessary - and this test failing is how anyone
    would learn that.
    """

    assert renewal_window_days("Sierre") == 60
    assert renewal_window_days("Grimisuat") == 14

    assert renewal_window_days("Sierre") != renewal_window_days("Grimisuat")


def test_an_unknown_commune_yields_no_window_rather_than_a_default():
    """
    The single most important behaviour here.

    Returning the canton's 90 days for an untraced commune would be
    indistinguishable, on screen, from a researched answer - and wrong
    for two of the three communes actually examined.
    """

    assert renewal_window_days("Zermatt") is None
    assert renewal_window_days(None) is None


def test_a_known_but_unresolved_commune_also_yields_no_window():
    """
    Monthey is listed with a null window on purpose: known to exist,
    known to be unresolved. It must not fall back to a number either.
    """

    assert find_commune("Monthey") is not None
    assert renewal_window_days("Monthey") is None


# ---------------------------------------------------------- language ---

def test_a_traced_commune_gives_its_administrative_language():
    assert commune_language("Sierre") == "fr"


def test_an_unknown_commune_gives_no_language():
    """
    So core/correspondence.py falls back to the canton default *and says
    it is guessing*, rather than being handed a confident wrong answer.
    """

    assert commune_language("Zermatt") is None


# ----------------------------------------------------------- display ---

def test_an_unknown_commune_explains_itself():
    """
    An unexplained blank is what this file exists to avoid. The user has
    to be told why there is no deadline, or they will assume there is no
    obligation.
    """

    result = explain("Zermatt")

    assert result["known"] is False
    assert result["window"] is None
    assert len(result["note"]) > 60


def test_a_known_commune_shows_where_the_number_came_from():

    result = explain("Sierre")

    assert result["known"] is True
    assert result["window"] == 60
    assert result["source_url"]
    assert result["note"]


# -------------------------------------------------------- the data ---

def test_every_commune_records_its_provenance():
    """
    Same rule as the obligation rules: a number with no source is a
    number nobody can check, and this file feeds a compliance deadline.
    """

    path = (
        Path(__file__).resolve().parent.parent
        / "data" / "canton_valais_communes.json"
    )

    for commune in json.loads(path.read_text(encoding="utf-8"))["communes"]:

        verification = commune["verification"]

        assert verification.get("source_url"), f"{commune['name']}: no source"
        assert verification.get("sourced_on"), f"{commune['name']}: no date"
        assert verification.get("note"), f"{commune['name']}: no note"

        if commune.get("renewal_window_days") is not None:
            assert verification["status"] in ("sourced", "verified"), (
                f"{commune['name']} publishes a window but is not even "
                f"sourced - a number with no traced source is exactly what "
                f"this file was created to stop"
            )


def test_no_commune_is_marked_verified_without_a_named_reviewer():
    """
    Same contract as the obligation rules. 'Verified' means a person took
    responsibility, and a person has a name and a date.
    """

    path = (
        Path(__file__).resolve().parent.parent
        / "data" / "canton_valais_communes.json"
    )

    for commune in json.loads(path.read_text(encoding="utf-8"))["communes"]:

        verification = commune["verification"]

        if verification["status"] == "verified":
            assert verification.get("reviewed_by"), commune["name"]
            assert verification.get("reviewed_on"), commune["name"]


def test_the_file_does_not_pretend_to_be_a_full_registry():
    """
    Three of over a hundred. The metadata has to say so, because the next
    person to read this file will otherwise assume a missing commune is a
    bug rather than the documented state.
    """

    path = (
        Path(__file__).resolve().parent.parent
        / "data" / "canton_valais_communes.json"
    )

    data = json.loads(path.read_text(encoding="utf-8"))

    assert len(known_communes()) < 10
    assert data["_meta"].get("why_it_is_almost_empty")
