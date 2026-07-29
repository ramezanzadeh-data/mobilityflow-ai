"""
Inline status badges.

Deliberately dumb renderers: a badge is told which level to show and never
decides it. Risk thresholds, permit rules and workflow states are backend
concerns and stay where they already are - a component that re-derived
them would be a second, silently diverging copy of a business rule.
"""

from html import escape

import streamlit as st


# Semantic level -> CSS modifier defined in components/theme.py.
_LEVEL_CLASSES = {
    "danger": "mf-badge--danger",
    "warning": "mf-badge--warning",
    "success": "mf-badge--success",
    "info": "mf-badge--info",
    "neutral": "mf-badge--neutral",
}

DEFAULT_LEVEL = "neutral"


def badge_html(text, level=DEFAULT_LEVEL, score=None) -> str:
    """
    Return the markup for one badge.

    Separated from the rendering call so a badge can be embedded inside a
    larger block of HTML (a table cell, a card) rather than only emitted
    as a standalone element.

    Args:
        text: Visible label. Escaped - it may carry case data.
        level: One of _LEVEL_CLASSES. An unknown level degrades to
            neutral rather than raising: a styling mismatch must never
            take down a page that is showing someone's case file.
        score: Optional numeric shown in a separated compartment.
    """

    css_class = _LEVEL_CLASSES.get(level, _LEVEL_CLASSES[DEFAULT_LEVEL])

    score_html = ""

    if score is not None:
        score_html = (
            f'<span class="mf-badge__score">{escape(str(score))}</span>'
        )

    return (
        f'<span class="mf-badge {css_class}">'
        f"{escape(str(text))}{score_html}"
        f"</span>"
    )


def badge(text, level=DEFAULT_LEVEL, score=None) -> None:
    """Render a single badge into the current Streamlit container."""

    st.markdown(badge_html(text, level, score), unsafe_allow_html=True)


def risk_badge(level, text, score) -> None:
    """
    Render the case risk indicator.

    Replaces ``st.error(f"{label} ({risk})")``. Streamlit's alert widgets
    are full-width blocks, so inside a narrow column the label wrapped one
    character per line and produced a vertical strip reading "H I G H".
    A badge is inline-flex with ``white-space: nowrap``, so it sizes to
    its own content and cannot wrap at all.

    The caller passes the level; this function never compares the score
    against a threshold. See the module docstring.
    """

    badge(text=text, level=level, score=score)
