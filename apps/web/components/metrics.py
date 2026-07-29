"""
KPI and distribution components for the dashboard.

Both exist because Streamlit's stock widgets degrade badly at the data
volumes this product actually has.

``st.bar_chart`` was drawing "Cases by Canton" from a two-row Series: it
produced a y-axis labelled 0.0 to 2.0, a single blue block occupying the
full plot area, and the category name rotated ninety degrees so "VALAIS"
read vertically. A bar chart needs enough categories for the *comparison*
to be the message; below roughly five it is a table wearing a costume, and
an unreadable one.

``st.metric`` has no notion of "not computable yet", so a KPI with nothing
to measure printed the literal string "N/A" - which tells the viewer a
number is broken rather than that it is not due yet.
"""

from html import escape

import streamlit as st


EMPTY_VALUE = "—"


def distribution(title, counts, empty_message) -> None:
    """
    Render a labelled distribution as proportional bars.

    Readable at one category and at twenty, which is the property the bar
    chart lacked. Labels sit horizontally beside their bar, so they cannot
    rotate; counts are shown as numbers, so the reader never has to
    estimate a value from a bar's height.

    Args:
        title: Section caption.
        counts: Mapping of label to count, or any object exposing
            ``.items()`` - a pandas ``value_counts()`` result works
            unchanged, so callers need not restructure their data.
        empty_message: Shown when there is nothing to display, instead of
            an empty frame.
    """

    items = [(str(label), int(value)) for label, value in counts.items()]

    st.caption(title)

    if not items:
        st.caption(empty_message)
        return

    largest = max(value for _, value in items)

    rows_html = []

    for label, value in sorted(items, key=lambda pair: -pair[1]):

        # Relative to the largest category, so the widest bar always fills
        # the row and small differences stay visible. A minimum keeps a
        # count of 1 from rendering as an invisible sliver.
        width = max(4, round(value / largest * 100)) if largest else 0

        rows_html.append(
            '<div class="mf-dist__row">'
            f'<div class="mf-dist__label" title="{escape(label)}">'
            f"{escape(label)}</div>"
            '<div class="mf-dist__track">'
            f'<div class="mf-dist__bar" style="width:{width}%"></div>'
            "</div>"
            f'<div class="mf-dist__value">{value}</div>'
            "</div>"
        )

    st.markdown(
        f'<div class="mf-dist">{"".join(rows_html)}</div>',
        unsafe_allow_html=True,
    )


def kpi(label, value, help_text=None) -> None:
    """
    Render one KPI.

    Args:
        label: Metric name.
        value: Formatted value, or None when it cannot be computed yet.
            None renders an em dash plus the explanation in ``help_text``,
            rather than the string "N/A" - an unmeasurable metric is a
            normal state for a young account, not a fault, and should not
            look like one.
        help_text: Why the value is missing, or what it means.
    """

    is_empty = value is None

    st.markdown(
        '<div class="mf-kpi">'
        f'<div class="mf-kpi__label">{escape(str(label))}</div>'
        f'<div class="mf-kpi__value'
        f'{" mf-kpi__value--empty" if is_empty else ""}">'
        f"{EMPTY_VALUE if is_empty else escape(str(value))}</div>"
        + (
            f'<div class="mf-kpi__note">{escape(str(help_text))}</div>'
            if help_text
            else ""
        )
        + "</div>",
        unsafe_allow_html=True,
    )
