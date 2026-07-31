import streamlit as st

from apps.web.session import (
    emit_pending_browser_updates,
    forget_session,
    keep_session_alive,
    remember_session,
    restore_session,
)
from auth.service import authenticate_user
from db.database import set_current_tenant, get_or_create_tenant
from i18n.translator import (
    LANGUAGE_NAMES,
    get_lang,
    set_language,
    supported_languages,
    t,
)


def language_selector(key="login_language"):
    """
    Choose the interface language.

    Placed on the login screen because that is the first thing anyone
    sees, and because a French-speaking user in Valais should not have to
    read an English form in order to find the setting that would have
    made it French.

    The choice is stored in the session before the fields below are
    rendered, so it applies immediately rather than on the next
    interaction - a selector whose effect lags by one click reads as
    broken.
    """

    current = get_lang()

    # Computed per render, not imported once: the pseudo language appears
    # only while MOBILITYFLOW_PSEUDO_LOCALE is set, so a customer build
    # never offers it.
    languages = supported_languages()

    # A selector with one option is a control that cannot do anything.
    # It reads as an unfinished feature rather than a deliberate scope,
    # and every user who clicks it learns the interface has choices that
    # are not choices.
    #
    # The product currently ships English only - see SHIPPED_LANGUAGES in
    # i18n/translator.py. Adding a language back there makes this appear
    # again with no change here.
    if len(languages) < 2:
        return current

    chosen = st.radio(
        t("language_label"),
        languages,
        index=languages.index(current) if current in languages else 0,
        format_func=lambda code: LANGUAGE_NAMES.get(code, code),
        horizontal=True,
        key=key,
    )

    if chosen != current:
        set_language(chosen)
        st.rerun()

    return chosen


def login():

    # Before the labels below are read, so switching language redraws
    # this screen in the new one straight away.
    language_selector()

    st.title(t("login_title"))

    st.caption(t("login_hint"))

    username = st.text_input(t("username_label"))
    password = st.text_input(t("password_label"), type="password")

    if st.button(t("login_button")):

        user = authenticate_user(
            username,
            password
        )

        if user:

            tenant_id = get_or_create_tenant(user["company"])

            st.session_state["user"] = {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "company": user["company"],
                "tenant_id": tenant_id,
                "must_change_password": bool(user.get("must_change_password")),
            }

            # So a page refresh does not undo the thing that just
            # happened. Best-effort by design: if the session row cannot
            # be written, the login still stands - see remember_session().
            remember_session(st.session_state["user"])

            st.success(t("login_success"))
            st.rerun()

        else:

            st.error(t("login_invalid"))


def require_login():

    # First, and on both branches below.
    #
    # Signing in and signing out each need one HTTP request that
    # Streamlit cannot make - setting and deleting the session cookie -
    # and each ends in st.rerun(), which throws away whatever the
    # interrupted run had queued. So the request is made here, on the run
    # after the one that asked for it, whether that run ends up showing
    # the application or the login form.
    emit_pending_browser_updates()

    # A refresh gives Streamlit a brand-new session with an empty
    # session_state, so the in-memory user is gone through no fault of
    # the person at the keyboard. Before concluding they are signed out,
    # ask the durable store - see apps/web/session.py for why the answer
    # lives in Postgres and what the session cookie does and does not
    # carry.
    if "user" not in st.session_state:

        restored = restore_session()

        if restored:
            st.session_state["user"] = restored

    if "user" not in st.session_state:
        login()
        st.stop()

    # Past this line somebody is signed in and doing something, which is
    # the definition of not idle. Recorded on every rerun so that a
    # session ends when the person leaves rather than a fixed time after
    # they arrived - the write itself is throttled to once a minute
    # inside keep_session_alive().
    keep_session_alive()

    # Streamlit reruns this script on every interaction, potentially on a
    # different worker thread each time - re-pin the DB-level tenant
    # context every rerun so Postgres RLS stays correctly scoped for
    # whichever thread is executing this particular run.
    set_current_tenant(st.session_state["user"].get("tenant_id"))


def logout():
    """
    End the session everywhere it is recorded.

    Both halves are required. Dropping the in-memory user without
    revoking the stored session would leave the cookie - and, while the
    fallback exists, the URL in the browser's history - still working;
    revoking without clearing session_state would leave this tab signed
    in. Either one alone makes Log out a button that does not do what it
    says.

    forget_session() revokes server-side and does not rely on the browser
    for any of it, so a blocked request or a tab closed mid-logout cannot
    leave a live session behind.
    """

    forget_session()

    st.session_state.pop("user", None)
