import streamlit as st

from apps.web.components.layout import page_header, section_header

from auth.password import verify_password, hash_password
from db.database import get_user, update_user_password
from i18n.translator import t


def show_settings(forced=False):

    page_header(t("settings_header"))

    if forced:
        st.warning(t("must_change_password_notice"))

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
