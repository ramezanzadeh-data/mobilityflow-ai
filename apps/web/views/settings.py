import streamlit as st

from apps.web.components.layout import page_header, section_header
from apps.web.session import forget_session
from db.database import revoke_all_sessions_for_user

from auth.password import verify_password, hash_password
from db.database import get_user, update_user_password
from i18n.translator import t


def show_settings(forced=False):

    page_header(t("settings_header"))

    if forced:
        st.warning(t("must_change_password_notice"))

    # Sessions.
    #
    # The browser session token travels in the URL, because Streamlit
    # cannot set an HttpOnly cookie from Python - see apps/web/session.py.
    # That means a printed page, a screenshot or a copied link carries a
    # working session until it expires, and a user who has just realised
    # that needs a way to close every one at once without hunting.
    #
    # This does not fix the exposure. It makes it recoverable in one
    # click, and it says so plainly rather than leaving the user to
    # discover the property from a PDF.
    section_header(t("sessions_header"))

    st.caption(t("sessions_url_warning"))

    if st.button(t("revoke_all_sessions_button")):

        revoke_all_sessions_for_user(st.session_state["user"]["username"])

        # Including this one. Signing every session out except the one
        # pressing the button would be a control that does not do what it
        # says, and this is the one case where the user's own session is
        # the one they may most want gone.
        forget_session()

        st.session_state.pop("user", None)

        st.rerun()

    section_header(t("change_password_header"))

    with st.form("change_password_form", clear_on_submit=True):

        current_password = st.text_input(t("current_password_label"), type="password")
        new_password = st.text_input(t("new_password_label"), type="password")
        confirm_password = st.text_input(t("confirm_new_password_label"), type="password")

        submitted = st.form_submit_button(t("change_password_button"))

    if not submitted:
        return

    username = st.session_state["user"]["username"]
    user = get_user(username)

    if not user or not verify_password(current_password, user["password"]):
        st.error(t("current_password_incorrect"))
        return

    if len(new_password) < 8:
        st.error(t("password_too_short_error"))
        return

    if new_password != confirm_password:
        st.error(t("password_mismatch_error"))
        return

    if new_password == current_password:
        st.error(t("password_same_as_current_error"))
        return

    update_user_password(username, hash_password(new_password))

    st.session_state["user"]["must_change_password"] = False

    st.success(t("password_changed_success"))
    st.rerun()
