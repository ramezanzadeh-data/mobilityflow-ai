"""
A refresh must land on the page the user was reading.

Signing in survives a refresh now. The page did not: st.session_state
["page"] lives in the same server memory the login used to, so a refresh
discarded it and defaulted back to Dashboard. Case Detail lost more than
the page - `selected_case` sits in the same place, so the case being read
was forgotten too, and the user was returned to a list to find it again.

Most of what follows is about the URL being untrusted input. It is
user-editable by definition, and the two things read from it - a page
name and a case id - are read defensively for different reasons:

  * the page name, because pages.index() raises on a value that is not
    in the list, and a mistyped URL should not be an error screen;
  * the case id, because it is a database key. The URL is not the
    authorisation boundary here - `cases` is under FORCE ROW LEVEL
    SECURITY with the tenant pinned per request, so another tenant's case
    returns nothing and the page says not found. That is asserted in the
    RLS tests, not here; what is asserted here is that this module never
    pretends otherwise.
"""

import pytest

from apps.web.state import navigation


PAGES = ["Dashboard", "Create Case", "Case Detail", "Settings"]


class FakeStreamlit:
    """session_state and query_params are both plain mappings here."""

    def __init__(self, query_params=None, session_state=None):
        self.query_params = dict(query_params or {})
        self.session_state = dict(session_state or {})


@pytest.fixture
def st(monkeypatch):

    fake = FakeStreamlit()
    monkeypatch.setattr(navigation, "st", fake)
    return fake


# ------------------------------------------------------ the reported bug ---

def test_a_refresh_returns_to_the_page_that_was_open(st):
    """
    The defect, directly. A refresh gives a new Streamlit session with an
    empty session_state; the URL is the only thing that crosses it.
    """

    st.query_params = {"page": "Settings"}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["page"] == "Settings", (
        "the page was not restored, so every refresh sends the user back "
        "to Dashboard from wherever they were reading"
    )


def test_a_refresh_on_a_case_keeps_the_case(st):
    """
    Case Detail without selected_case renders "please select a case", so
    restoring the page alone would still cost the user the record.
    """

    st.query_params = {"page": "Case Detail", "case": "42"}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["page"] == "Case Detail"
    assert st.session_state["selected_case"] == 42


def test_the_case_id_is_an_integer_not_the_string_from_the_url(st):
    """
    load_case() and every RLS-scoped query take an id. A string that
    happens to look like one compares differently in Python and would
    make `selected_case` disagree with itself between paths.
    """

    st.query_params = {"case": "42"}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["selected_case"] == 42
    assert isinstance(st.session_state["selected_case"], int)


# -------------------------------------------------- the URL is untrusted ---

def test_an_unknown_page_falls_back_instead_of_raising(st):
    """
    app.py does pages.index(st.session_state["page"]), which raises
    ValueError on anything not in the list. URLs get truncated, edited
    and pasted badly; none of that should produce a stack trace.
    """

    st.query_params = {"page": "AdminPanel"}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["page"] == "Dashboard"


@pytest.mark.parametrize("value", ["", "abc", "1; DROP TABLE cases", "1.5", "--"])
def test_a_case_id_that_is_not_a_number_is_ignored(st, value):
    """
    Ignored rather than reported. The page's answer to no case is "pick a
    case", which is the right answer to a nonsense case too - and an
    error message here would tell whoever typed it that the parameter is
    read at all.
    """

    st.query_params = {"case": value}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert "selected_case" not in st.session_state


def test_this_module_does_not_treat_the_url_as_permission():
    """
    A structural check, because the failure mode is an absence.

    Restoring a case id from the URL is only safe because the database
    refuses cases from other tenants. If this module ever grew its own
    access check, that check would become the thing people trust, and it
    would be the weaker of the two.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "state" / "navigation.py"
    ).read_text(encoding="utf-8")

    # Parsed, not searched. The docstring discusses load_case and row
    # level security at length - explaining why the check is elsewhere is
    # the point of it - so a substring search would match the explanation
    # and report the opposite of what is true.
    tree = ast.parse(source)

    imported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)

    assert imported <= {"streamlit"}, (
        f"navigation.py imports {sorted(imported - {'streamlit'})}. Reading "
        f"a case id from the URL is safe because the database refuses "
        f"other tenants' rows; an access check here would become the "
        f"thing people trust, and it would be the weaker of the two."
    )


# ------------------------------------------------ live state wins ---

def test_a_page_already_chosen_this_session_is_not_overwritten(st):
    """
    The URL is the fallback for a session that has just started, not a
    second source of truth. If it could overwrite a live choice, clicking
    a page in the sidebar would be undone by the previous URL on the
    same run.
    """

    st.session_state = {"page": "Case Detail"}
    st.query_params = {"page": "Settings"}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["page"] == "Case Detail"


def test_a_case_already_open_is_not_replaced_by_the_url(st):

    st.session_state = {"selected_case": 9}
    st.query_params = {"case": "42"}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["selected_case"] == 9


# ------------------------------------------------------------- writing ---

def test_the_url_is_updated_to_match_the_screen(st):

    st.session_state = {"page": "Settings", "selected_case": 7}

    navigation.remember_navigation()

    assert st.query_params["page"] == "Settings"
    assert st.query_params["case"] == "7"


def test_leaving_a_case_removes_it_from_the_url(st):
    """
    A stale case parameter is a claim about what the screen is showing
    that is no longer true - and the next refresh would act on it.
    """

    st.session_state = {"page": "Dashboard", "selected_case": 7}
    navigation.remember_navigation()

    assert "case" in st.query_params

    st.session_state = {"page": "Dashboard"}
    navigation.remember_navigation()

    assert "case" not in st.query_params


def test_a_full_round_trip_survives_the_session_being_discarded(st):
    """
    What a refresh actually is: the URL persists, session_state does not.
    """

    st.session_state = {"page": "Case Detail", "selected_case": 42}

    navigation.remember_navigation()

    st.session_state = {}

    navigation.restore_navigation(PAGES, default="Dashboard")

    assert st.session_state["page"] == "Case Detail"
    assert st.session_state["selected_case"] == 42


# --------------------------------------------------------- the call site ---

def test_app_py_restores_before_it_indexes_the_page_list():
    """
    A static check on ordering. restore_navigation() has to run before
    pages.index(st.session_state["page"]) - the other way round, the
    default is already in place and the URL is never consulted.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "web" / "app.py"
    ).read_text(encoding="utf-8")

    assert "restore_navigation" in source, (
        "app.py never restores the page from the URL, so every refresh "
        "lands on the default"
    )

    assert source.index("restore_navigation(") < source.index("pages.index(")


def test_app_py_writes_the_url_after_reading_the_navigation_control():
    """
    Written after the radio, so the URL reflects the choice made on this
    run rather than the one before it.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "apps" / "web" / "app.py"
    ).read_text(encoding="utf-8")

    assert source.index("remember_navigation()") > source.index("st.sidebar.radio")
