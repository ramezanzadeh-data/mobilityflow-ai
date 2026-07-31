"""
Application shell: the frame a user sees on every screen.

The sidebar was three lines of unstyled text above a bare radio list.
Nothing identified the product, nothing indicated which section was
active except the radio dot, and the user's identity block used the same
type size as the navigation, so the eye had no order to follow.

The frame is what makes software feel like a product rather than a form:
it is on screen 100% of the time and it is the only part a user never
stops looking at.
"""

from html import escape

import streamlit as st


PRODUCT_NAME = "MobilityFlow"
PRODUCT_SUFFIX = "AI"


def brand() -> None:
    """
    Product identity at the top of the sidebar.

    A named, styled mark rather than nothing. This is also the slot a
    customer's own logo goes in if white-labelling is ever offered, which
    is why it is a component and not three lines of markup inline.
    """

    st.sidebar.markdown(
        '<div class="mf-brand">'
        f'<span class="mf-brand__mark">{escape(PRODUCT_NAME[0])}</span>'
        f'<span class="mf-brand__name">{escape(PRODUCT_NAME)}'
        f'<span class="mf-brand__suffix">{escape(PRODUCT_SUFFIX)}</span>'
        "</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def user_block(username, company, role, role_label=None) -> None:
    """
    Who is signed in, and to which tenant.

    Company is shown as prominently as the username on purpose: this is a
    multi-tenant product, and "which customer's data am I looking at" is
    a question an operator must never have to guess. Role is shown
    because it determines what the screen will let them do, and an
    unexplained missing button is worse than a visible restriction.

    Every value is escaped - all three are stored, administrator-set
    strings going into raw HTML.
    """

    st.sidebar.markdown(
        '<div class="mf-user">'
        f'<div class="mf-user__avatar">{escape(str(username)[:1].upper())}</div>'
        '<div class="mf-user__text">'
        f'<div class="mf-user__name">{escape(str(username))}</div>'
        f'<div class="mf-user__company">{escape(str(company))}</div>'
        f'<div class="mf-user__role">{escape(str(role_label or role))}</div>'
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def nav_section_label(text) -> None:
    """A quiet heading above a group of navigation entries."""

    st.sidebar.markdown(
        f'<div class="mf-nav__section">{escape(str(text))}</div>',
        unsafe_allow_html=True,
    )


def page_header(title, subtitle=None) -> None:
    """
    The single title of a screen.

    One per page, and the only h1. The app previously mixed
    ``st.title()`` on Settings with ``st.header()`` everywhere else, so
    the page title was an h1 on one screen and an h2 on the others -
    a hierarchy inversion that assistive technology reports faithfully
    and that made the screens feel like different products.

    Args:
        title: The screen's name.
        subtitle: One line of context. Optional, and worth using: a
            title alone tells a new user what the screen is called, not
            what it is for.
    """

    subtitle_html = (
        f'<p class="mf-page__subtitle">{escape(str(subtitle))}</p>'
        if subtitle
        else ""
    )

    st.markdown(
        '<div class="mf-page">'
        f'<h1 class="mf-page__title">{escape(str(title))}</h1>'
        f"{subtitle_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def panel_marker() -> None:
    """
    Mark a bordered container as one this stylesheet styles.

    Emitted as the first thing inside the container, and paired with a
    :has() rule in theme.py. The obvious alternative - styling
    [data-testid="stVerticalBlockBorderWrapper"] directly - was rejected
    because Streamlit emits that wrapper for every container, not only
    the ones created with border=True, so the rule would draw a border
    around things that are not panels. That could not be verified from
    here without a browser, and a selector whose blast radius is unknown
    is not one to ship.

    This is exact instead: the border follows the marker, and the marker
    is only where it is put.
    """

    st.markdown(
        '<span class="mf-panel-marker"></span>',
        unsafe_allow_html=True,
    )


# section_header_with_meta() and section_header_with_identity() stood
# here: a section heading with a counter, and a section heading with the
# case subject, each on one line.
#
# Both lost their last caller. The stage counter moved into
# workflow_stage_row(), which draws the heading, the track and the
# counter as one row because all three describe the same thing; and the
# employee's name became the page title, so no heading carries an
# identity beside it any more.
#
# Deleted rather than kept for later. An exported component with no
# callers still has to be read, reviewed and kept working by everyone who
# touches this file, and its stylesheet rules went with it - see the note
# in components/theme.py. If a heading needs something beside it again,
# workflow_stage_row() is the worked example, including why it has to be
# a single st.markdown call.


def section_header(title, description=None, tight=False) -> None:
    """
    A division within a screen. Always below page_header in the
    hierarchy, never used as a page title.

    Args:
        title: Section name.
        description: What the section is for, when that is not obvious
            from the title alone.
        tight: Reduce the space above. For a section that directly
            follows the page identity, where the standard 32px separates
            a heading from the thing it belongs to rather than from the
            previous section.
    """

    description_html = (
        f'<p class="mf-section__description">{escape(str(description))}</p>'
        if description
        else ""
    )

    # Written out rather than interpolated: the XSS guard rejects any
    # variable inside unsafe_allow_html markup, and the rule is worth
    # more than the repetition costs.
    opening = (
        '<div class="mf-section mf-section--tight">' if tight
        else '<div class="mf-section">'
    )

    st.markdown(
        opening
        + f'<h2 class="mf-section__title">{escape(str(title))}</h2>'
        + description_html
        + "</div>",
        unsafe_allow_html=True,
    )
