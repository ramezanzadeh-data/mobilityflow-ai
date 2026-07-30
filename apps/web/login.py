import streamlit as st

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

            st.success(t("login_success"))
            st.rerun()

        else:

            st.error(t("login_invalid"))


def require_login():

    if "user" not in st.session_state:
        login()
        st.stop()

    # Streamlit reruns this script on every interaction, potentially on a
    # different worker thread each time - re-pin the DB-level tenant
    # context every rerun so Postgres RLS stays correctly scoped for
    # whichever thread is executing this particular run.
    set_current_tenant(st.session_state["user"].get("tenant_id"))
