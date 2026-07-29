"""
Tests for the dashboard KPI and distribution components.

Both replaced Streamlit widgets that failed at this product's real data
volumes rather than at extreme ones:

* ``st.bar_chart`` fed a two-row ``value_counts()`` drew a y-axis from 0.0
  to 2.0, one block filling the plot, and the category name rotated to
  vertical - "VALAIS" reading top to bottom.
* ``st.metric`` printed the literal string "N/A" for a figure that simply
  is not due yet, which reads as a broken number.

The interesting cases here are all small-n: one category, zero categories,
a count of one beside a count of fifty. Those are what a new customer sees
in their first week, which is exactly when the product is being judged.
"""

import sys
import types

import pytest


# These are pure string builders; stub Streamlit so they import without a
# running server. Capture what they would have rendered.
_RENDERED = []


def _install_streamlit_stub():

    stub = types.ModuleType("streamlit")
    stub.markdown = lambda html, **kwargs: _RENDERED.append(html)
    stub.caption = lambda text, **kwargs: _RENDERED.append(text)
    sys.modules.setdefault("streamlit", stub)


_install_streamlit_stub()

from apps.web.components.metrics import distribution, kpi  # noqa: E402


@pytest.fixture(autouse=True)
def clear_rendered():
    _RENDERED.clear()
    yield
    _RENDERED.clear()


def _markup():
    return "".join(_RENDERED)


# ---------------------------------------------------------------- KPI ---

def test_kpi_renders_its_value():

    kpi("Total Cases", 42)

    assert ">42<" in _markup()
    assert "mf-kpi__value--empty" not in _markup()


def test_kpi_without_a_value_shows_a_placeholder_not_the_text_na():
    """
    The regression. "N/A" tells the viewer a number is broken; an em dash
    with a reason tells them it is not due yet.
    """

    kpi("Avg Processing Time", None, "Available once a case reaches Completed")

    markup = _markup()

    assert "N/A" not in markup
    assert "—" in markup
    assert "mf-kpi__value--empty" in markup
    assert "Available once a case reaches Completed" in markup


def test_kpi_escapes_its_inputs():

    kpi("<img src=x onerror=alert(1)>", "<b>5</b>")

    assert "<img" not in _markup()
    assert "<b>5</b>" not in _markup()


# ------------------------------------------------------- distribution ---

def test_distribution_renders_one_row_per_category():

    distribution("Cases by Canton", {"VALAIS": 5, "VAUD": 3}, "No data yet")

    assert _markup().count("mf-dist__row") == 2


def test_single_category_is_readable():
    """
    The exact shape that broke st.bar_chart: one category. It must render
    as a labelled row with its count, not as an axis and a block.
    """

    distribution("Cases by Canton", {"VALAIS": 2}, "No data yet")

    markup = _markup()

    assert "VALAIS" in markup
    assert ">2<" in markup
    assert "width:100%" in markup


def test_empty_distribution_explains_itself():

    distribution("Cases by Permit", {}, "No data yet")

    assert "No data yet" in _markup()
    assert "mf-dist__row" not in _markup()


def test_rows_are_ordered_by_count_descending():

    distribution("Cases by Permit", {"B": 1, "C": 9, "L": 4}, "none")

    markup = _markup()

    assert markup.index("C") < markup.index("L") < markup.index("B")


def test_small_counts_stay_visible_beside_large_ones():
    """
    A count of 1 against 50 is 2% of the track - about a pixel, which
    reads as "zero". A floor keeps the row visibly non-empty while the
    number beside it stays exact.
    """

    distribution("Cases by Permit", {"B": 50, "C": 1}, "none")

    widths = [
        int(chunk.split("%")[0])
        for chunk in _markup().split("width:")[1:]
    ]

    assert max(widths) == 100
    assert min(widths) >= 4


def test_distribution_escapes_category_labels():
    """
    Category labels come from case data, and reach both the row text and
    a title attribute.
    """

    distribution("x", {"<img src=x onerror=alert(1)>": 1}, "none")

    markup = _markup()

    assert "<img" not in markup
    assert "&lt;img" in markup


def test_accepts_a_pandas_value_counts_result():
    """
    The caller passes ``pd.Series(...).value_counts()`` unchanged, so the
    component must accept anything with .items() rather than requiring a
    dict.
    """

    pd = pytest.importorskip("pandas")

    counts = pd.Series(["VALAIS", "VALAIS", "VAUD"]).value_counts()

    distribution("Cases by Canton", counts, "none")

    markup = _markup()

    assert markup.count("mf-dist__row") == 2
    assert ">2<" in markup and ">1<" in markup
