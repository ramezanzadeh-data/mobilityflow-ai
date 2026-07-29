# Must run before any application module is imported: db.database,
# auth.jwt and auth.encryption all read configuration at import time.
# Without it, a Streamlit process started directly on a developer machine
# (rather than through Docker Compose) silently falls back to
# db.database._build_pool()'s localhost defaults - see
# bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

import streamlit as st  # noqa: E402  (deliberate - see above)

from apps.web.login import language_selector, require_login  # noqa: E402
from db.schema_check import (  # noqa: E402
    describe_problems,
    find_schema_problems,
)
from apps.web.components.theme import inject_theme  # noqa: E402
from apps.web.components.layout import (  # noqa: E402
    brand,
    nav_section_label,
    user_block,
)
from i18n.translator import t

# apps/web/views/, not apps/web/pages/. Streamlit auto-registers every
# module in a `pages/` directory beside the main script as a navigable
# page, which is how the sidebar ended up with two navigations: this
# app's deliberate four-entry "Go to" radio, plus a generated list of
# all eight modules - including `documents`, `reports` and `tasks`,
# which are imported helpers, not standalone pages. Those generated
# entries also render outside app.py, so they skip require_login() and
# show a blank screen. Renaming the directory removes the auto-detection
# at its source; nothing else about these modules changed.
from apps.web.views.dashboard import show_dashboard
from apps.web.views.create_case import show_create_case
from apps.web.views.case_detail import show_case_detail
from apps.web.views.settings import show_settings


st.set_page_config(page_title="MobilityFlow AI", layout="wide")

# One stylesheet for the whole app. The two rules that used to live inline
# here now sit alongside every other rule in components/theme.py, so there
# is a single place to change a colour or a spacing step.
inject_theme()

# Before the login form, so a stale database is reported to whoever is
# deploying rather than to whoever happens to submit the first form that
# touches a missing column. That is how this check came to exist: a user
# filled in the case form and was shown a psycopg2 UndefinedColumn error
# with the table name and the SQL in it.
_schema_problems = find_schema_problems()

if _schema_problems:

    st.error(t("schema_outdated_title"))

    # The remediation is shown in full rather than summarised. Whoever
    # sees this needs to act on it, and looking up the command elsewhere
    # is friction at exactly the wrong moment.
    st.code(describe_problems(_schema_problems), language="text")

    st.stop()

require_login()

user = st.session_state["user"]


# The .sidebar-user / .sidebar-title rules that used to be declared here
# are gone: they were the last inline stylesheet in the app, and the
# markup they styled is now components/layout.py, which draws on the
# shared tokens in components/theme.py like everything else.
brand()

# Escaping happens inside user_block(): username, company and role are
# stored, administrator-settable strings going into raw HTML. A company
# named `<img src=x onerror=...>` would otherwise execute in the browser
# of every user of that tenant.
user_block(
    username=user["username"],
    company=user["company"],
    role=user["role"],
)


if user.get("must_change_password"):
    show_settings(forced=True)
    st.stop()


pages = [
    "Dashboard",
    "Create Case",
    "Case Detail",
    "Settings"
]

page_labels = {
    "Create Case": t("create_edit_header"),
    "Dashboard": t("dashboard_header"),
    "Case Detail": t("case_detail_header"),
    "Settings": t("settings_header"),
}


if "page" not in st.session_state:
    st.session_state["page"] = "Dashboard"


# Above the navigation, not below it: this changes the labels of
# everything underneath, so a reader meets the control before the text it
# governs. Repeated from the login screen because a user who changes
# their mind must not have to sign out to switch language.
with st.sidebar:
    language_selector(key="sidebar_language")

st.sidebar.divider()

nav_section_label(t("nav_go_to_label"))

# Still st.radio, restyled rather than replaced: the widget keeps
# ownership of the selection, so keyboard navigation and state handling
# are unchanged. label_visibility hides its own label because
# nav_section_label above is now the heading - two headings for one list
# was part of what made the sidebar look unfinished.
page = st.sidebar.radio(
    t("nav_go_to_label"),
    pages,
    index=pages.index(
        st.session_state["page"]
    ),
    format_func=lambda p: page_labels[p],
    label_visibility="collapsed",
)

st.session_state["page"] = page


if page == "Create Case":
    show_create_case()

elif page == "Case Detail":
    show_case_detail()

elif page == "Settings":
    show_settings()

elif page == "Dashboard":
    show_dashboard()
