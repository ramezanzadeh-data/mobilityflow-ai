"""
Keeping the current page across a browser refresh.

Signing in now survives a refresh - see apps/web/session.py - but the
page did not. ``st.session_state["page"]`` is in the same server memory
the login used to live in, so a refresh discarded it and defaulted back
to Dashboard. Someone reading a case, pressing F5, and being returned to
a list is being made to navigate back to where they already were.

Case Detail lost more than the page: ``selected_case`` lives in the same
place, so the case being read was forgotten too.

Both go in the URL, which is the right place for them for a reason beyond
refresh: a page and a record are what a URL is *for*. Putting them there
also makes a case linkable, so a consultant can send a colleague the case
rather than instructions for finding it.

The URL is not an authorisation boundary
----------------------------------------
Anyone can type ``?case=999``. Nothing here treats the URL as permission,
and nothing here needs to: `cases` is under FORCE ROW LEVEL SECURITY with
the tenant pinned per request, so ``load_case`` on another tenant's case
returns nothing and the page reports it as not found. The database
refuses it, not this module.

The page name is validated against the known list all the same. Not for
security - an unknown page cannot leak anything - but because
``pages.index(...)`` raises ValueError on a value that is not there, and
a typo in a URL should not be an error screen.
"""

import streamlit as st

PAGE_PARAM = "page"
CASE_PARAM = "case"


def restore_navigation(pages, default):
    """
    Seed session_state from the URL on a fresh Streamlit session.

    Only when the key is absent. A value already in session_state was put
    there by something the user did in this session and always wins - the
    URL is the fallback for a session that has just started, not a second
    source of truth competing with the live one.
    """

    if "page" not in st.session_state:

        requested = st.query_params.get(PAGE_PARAM)

        # An unrecognised page falls back rather than raising. URLs get
        # truncated, edited and pasted badly, and none of that should
        # produce a stack trace.
        st.session_state["page"] = (
            requested if requested in pages else default
        )

    if "selected_case" not in st.session_state:

        requested = st.query_params.get(CASE_PARAM)

        if requested is not None:
            try:
                st.session_state["selected_case"] = int(requested)
            except (TypeError, ValueError):
                # Not a case id. Ignored rather than reported: the page
                # will simply ask the user to pick a case, which is the
                # same thing it does for no case at all.
                pass


def remember_navigation():
    """
    Write the current page and case back to the URL.

    Called on every run, after the navigation control has been read, so
    the address bar always describes what is on screen. Cheap, and it
    means the URL is a consequence of the state rather than something
    kept in step by hand.
    """

    page = st.session_state.get("page")

    if page and st.query_params.get(PAGE_PARAM) != page:
        st.query_params[PAGE_PARAM] = page

    case_id = st.session_state.get("selected_case")

    if case_id:
        if st.query_params.get(CASE_PARAM) != str(case_id):
            st.query_params[CASE_PARAM] = str(case_id)

    elif CASE_PARAM in st.query_params:
        # No case selected any more, so the parameter would be a stale
        # claim about what the screen is showing.
        del st.query_params[CASE_PARAM]
