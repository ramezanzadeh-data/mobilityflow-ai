"""
Card and field-grid layout components.

These exist to replace ``st.columns(n)`` for read-only summary data.
Streamlit columns are fixed fractions of the container: eight columns are
always one eighth of the width each, whatever the viewport. At laptop
width that is roughly 90px, which is narrower than a single word like
"Nationality" - so the browser wrapped values one character per line and
the Case Overview rendered as a wall of vertical text.

A CSS grid with ``minmax()`` states a minimum width per field instead of a
fixed count, so the row reflows to however many columns genuinely fit.
Same data, no breakpoint bookkeeping, and it cannot collapse.
"""

from html import escape

import streamlit as st


EMPTY_PLACEHOLDER = "—"


def field_html(label, value, value_html=None) -> str:
    """
    Markup for one label/value pair.

    Args:
        label: Field caption.
        value: Field value. Escaped, because this is case data: employee
            names, employer names and free-text notes are user-supplied
            and would otherwise be an HTML injection point on a page that
            other tenants' staff also view.
        value_html: Pre-rendered markup to show instead of ``value`` -
            for a badge, say. The caller is then responsible for escaping
            anything user-supplied inside it (see badges.badge_html,
            which escapes).
    """

    if value_html is not None:
        rendered_value = value_html

    elif value is None or str(value).strip() == "":
        rendered_value = (
            f'<span class="mf-field__value--empty">{EMPTY_PLACEHOLDER}</span>'
        )

    else:
        rendered_value = escape(str(value))

    return (
        '<div class="mf-field">'
        f'<div class="mf-field__label">{escape(str(label))}</div>'
        f'<div class="mf-field__value">{rendered_value}</div>'
        "</div>"
    )


def obligation_row_html(
    title,
    due_text,
    urgency_badge_html,
    detail,
    provenance_html,
) -> str:
    """
    Markup for one statutory obligation.

    Provenance sits on the same line as the deadline, not behind a link.
    An immigration deadline the customer cannot trace is one they cannot
    defend to an auditor, and an unverified rule shown without that mark
    would be the product presenting guesswork as law.
    """

    return (
        '<div class="mf-obligation">'
        '<div class="mf-obligation__head">'
        f'<span class="mf-obligation__title">{escape(str(title))}</span>'
        f"{urgency_badge_html}"
        "</div>"
        f'<div class="mf-obligation__due">{escape(str(due_text))}</div>'
        f'<div class="mf-obligation__detail">{escape(str(detail))}</div>'
        f'<div class="mf-obligation__provenance">{provenance_html}</div>'
        "</div>"
    )


def obligation_row(title, due_text, urgency_badge_html, detail,
                   provenance_html) -> None:

    st.markdown(
        obligation_row_html(
            title, due_text, urgency_badge_html, detail, provenance_html
        ),
        unsafe_allow_html=True,
    )


def empty_state(title, body, steps=None) -> None:
    """
    Render the screen a customer sees before they have any data.

    This is the first thing every new account looks at, and it was one
    line of ``st.info`` followed by ``return`` - a dead end that neither
    explained the product nor offered a way forward. First impressions in
    a sales demo happen here too, on a freshly seeded tenant.

    An empty state has three jobs: say what this screen will show, say
    why it is blank, and give the next action. The caller renders the
    action itself, because a button belongs to the page that knows what
    it should do.

    Args:
        title: What this screen is for.
        body: Why it is empty, in plain language.
        steps: Optional ordered list of what to do first.
    """

    steps_html = ""

    if steps:
        items = "".join(
            f"<li>{escape(str(step))}</li>" for step in steps
        )
        steps_html = f'<ol class="mf-empty__steps">{items}</ol>'

    st.markdown(
        '<div class="mf-empty">'
        f'<div class="mf-empty__title">{escape(str(title))}</div>'
        f'<p class="mf-empty__body">{escape(str(body))}</p>'
        f"{steps_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def record_row_html(items) -> str:
    """
    Markup for one record summarised as a horizontal row of attributes.

    Used for the dashboard case list. The previous hand-written version
    combined ``white-space: nowrap`` with seven fixed ``margin-right:35px``
    spacers, which pinned the row to a fixed pixel width no matter how wide
    the viewport was. Anything past that width was simply cut off - which
    is why the risk badge rendered as "🔺 H".

    Here the row is a flex container that wraps, and spacing comes from
    ``gap`` rather than per-item margins, so items reflow instead of
    overflowing.

    Args:
        items: Sequence of ``(text,)``/``(text, html)`` entries. When
            ``html`` is given it is inserted verbatim - the caller escapes
            it (badges.badge_html does). Plain text is escaped here.
    """

    cells = []

    for item in items:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            text, html = item
        else:
            text, html = item, None

        rendered = html if html is not None else escape(str(text))

        cells.append(f'<span class="mf-record-row__item">{rendered}</span>')

    return f'<div class="mf-record-row">{"".join(cells)}</div>'


def record_row(items) -> None:
    """Render one record summary row."""

    st.markdown(record_row_html(items), unsafe_allow_html=True)


def field_grid(fields, compact=False) -> None:
    """
    Render label/value pairs as a responsive grid.

    Args:
        fields: Sequence of ``(label, value)`` pairs, or
            ``(label, value, value_html)`` triples where the third item is
            pre-rendered markup such as a badge.
        compact: Narrower cells, so a short row of summary facts stays on
            one line instead of reflowing onto two. Use only with a small
            number of fields - the floor is 120px per cell, and below that
            values start wrapping again, which is the failure this
            component exists to prevent.

    Emitted as a single ``st.markdown`` call rather than one per field:
    Streamlit wraps every element in its own flex container, so per-field
    calls would reintroduce the layout nesting this component exists to
    avoid.
    """

    cells = []

    for field in fields:
        if len(field) == 3:
            label, value, value_html = field
        else:
            (label, value), value_html = field, None

        cells.append(field_html(label, value, value_html))

    # The two class strings are written out rather than interpolated
    # from a variable. tests/test_ui_html_escaping.py rejects any value
    # placed into unsafe_allow_html markup unless it comes from a known
    # escaping helper - and it cannot tell a literal this file controls
    # from case data. Widening that rule to admit "variables I promise
    # are safe" is how the exemption eventually covers something that is
    # not, so the literal is repeated instead.
    if compact:
        st.markdown(
            '<div class="mf-field-grid mf-field-grid--compact">'
            + "".join(cells)
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="mf-field-grid">' + "".join(cells) + "</div>",
            unsafe_allow_html=True,
        )
