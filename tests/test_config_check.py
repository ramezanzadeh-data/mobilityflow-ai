"""
Tests for the startup configuration check.

A .env file carried this line:

    MOBILITYFLOW_SESSION_URL_FALLBACK=2

Two things were wrong with it. The variable had been deleted along with
the feature it controlled, and the value - 2 - was meant for
MOBILITYFLOW_SESSION_IDLE_MINUTES, a different setting entirely. The
process did what every process does with an environment variable it does
not read: nothing, silently.

So the deployment ran with a thirty-minute idle timeout, a .env that
appeared to say two minutes, and an operator who had every reason to
believe the setting was applied. Testing the timeout looked like the
timeout was broken, which sent the investigation at the session code
rather than at the spelling.

That is what makes this worth a check rather than more care. A misspelt
configuration key is not a missing feature - it is a feature that reports
itself as present, and for a security control the distance between "set"
and "believed to be set" is the entire risk.

Three properties are held down here:

  * it notices a variable nothing reads;
  * it names the setting that was probably meant, because "this is wrong"
    and "this is the line to change" are different amounts of help at
    the moment someone is deploying;
  * it never raises, because a check that can take down the application
    it protects is worse than no check at all.
"""

import pytest

from bootstrap.config_check import (
    KNOWN_SETTINGS,
    describe_problems,
    find_config_problems,
)


# --------------------------------------------------------- noticing ---


def test_a_recognised_setting_is_not_a_problem():

    assert find_config_problems({"MOBILITYFLOW_SESSION_IDLE_MINUTES": "2"}) == []


def test_an_empty_environment_is_not_a_problem():
    """Every setting has a default; setting none of them is normal."""

    assert find_config_problems({}) == []


def test_a_setting_nothing_reads_is_reported():

    problems = find_config_problems({"MOBILITYFLOW_SESSION_URL_FALLBACK": "2"})

    assert len(problems) == 1
    assert problems[0].name == "MOBILITYFLOW_SESSION_URL_FALLBACK"


def test_variables_belonging_to_other_things_are_left_alone():
    """
    A real deployment's environment is mostly other people's variables.
    A check that guessed at which of them were meant for this
    application would be noise, and noise is how a check stops being
    read.
    """

    assert find_config_problems({
        "PGHOST": "postgres",
        "PATH": "/usr/bin",
        "AWS_REGION": "eu-central-1",
        "SESSION_IDLE_MINUTES": "2",     # right idea, no prefix, not ours
    }) == []


def test_every_problem_is_reported_not_just_the_first():
    """
    Whoever is deploying should not have to fix one, redeploy, and
    discover the next.
    """

    problems = find_config_problems({
        "MOBILITYFLOW_SESSION_URL_FALLBACK": "2",
        "MOBILITYFLOW_NOT_A_THING": "1",
    })

    assert len(problems) == 2


# ---------------------------------------------------- being helpful ---


def test_a_near_miss_names_the_setting_that_was_meant():
    """
    The difference between a check that stops a deployment and one that
    fixes it.
    """

    problems = find_config_problems({"MOBILITYFLOW_SESSION_IDLE_MINUTE": "2"})

    assert problems[0].suggestion == "MOBILITYFLOW_SESSION_IDLE_MINUTES"
    assert "MOBILITYFLOW_SESSION_IDLE_MINUTES" in str(problems[0])


def test_something_unrelated_is_not_given_a_misleading_suggestion():
    """
    A wrong suggestion is worse than none: it sends someone to change a
    setting that was never the problem.
    """

    problems = find_config_problems({"MOBILITYFLOW_ZZZZZZZZZZZZ": "1"})

    assert problems[0].suggestion is None


def test_the_message_lists_the_settings_that_do_exist():
    """
    The list is short enough to print and is the answer to the question
    the reader now has.
    """

    message = describe_problems(
        find_config_problems({"MOBILITYFLOW_SESSION_URL_FALLBACK": "2"})
    )

    assert "MOBILITYFLOW_SESSION_URL_FALLBACK" in message

    for name in KNOWN_SETTINGS:
        assert name in message


def test_no_message_when_there_is_nothing_to_say():

    assert describe_problems([]) == ""


# ------------------------------------------------------ never raises ---


@pytest.mark.parametrize("environ", [
    {"MOBILITYFLOW_": ""},
    {"MOBILITYFLOW_X": ""},
    {"MOBILITYFLOW_ÅÄÖ": "1"},
])
def test_odd_input_is_reported_rather_than_raised(environ):
    """
    This runs before the application does. Whatever is in the
    environment, the worst it may do is refuse the start with a message -
    never fail inside the check itself, which would produce a traceback
    about difflib instead of about configuration.
    """

    problems = find_config_problems(environ)

    assert describe_problems(problems)


# --------------------------------------------- the list is the check ---
#
# KNOWN_SETTINGS is not documentation, it is the check itself, so it is
# worth exactly as much as its agreement with the code. Both directions
# are asserted, because each one fails differently and neither failure
# announces itself:
#
#   * an entry with nothing behind it accepts a variable that does
#     nothing - the original defect, wearing the check as a disguise;
#   * a setting missing an entry makes the application refuse to start
#     the first time anybody sets it.


def _configuration_names(source):
    """
    MOBILITYFLOW_* names this file actually uses, ignoring what it says.

    Parsed rather than searched, for a reason this repository has already
    paid for once - conftest.py records it: a substring search over file
    text matched the name of a module inside a *comment*, and prose
    disabled tests. The same thing happened here on the first run, on
    this line in apps/web/app.py:

        # came to exist: MOBILITYFLOW_SESSION_URL_FALLBACK=2 in a .env

    which is an explanation of the defect, not a use of the variable.

    Comments do not survive parsing at all. Docstrings do - they are
    string constants - so they are excluded explicitly, on the same
    grounds: a module explaining a setting is not a module reading one.
    What remains is string literals in executable positions, which is
    where os.environ.get("MOBILITYFLOW_...") puts the name.
    """

    import ast
    import re

    tree = ast.parse(source)

    documentation = set()

    for node in ast.walk(tree):

        body = getattr(node, "body", None)

        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            documentation.add(id(body[0].value))

    names = set()

    for node in ast.walk(tree):

        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue

        if id(node) in documentation:
            continue

        names |= set(re.findall(r"MOBILITYFLOW_[A-Z0-9_]+", node.value))

    return names


def _settings_referenced_by_the_application():
    """
    Every MOBILITYFLOW_* name the application code uses, as a set.

    Two things are excluded, both deliberately.

    config_check.py is where the registry lives, so including it would
    make every entry prove itself.

    tests/ is full of names that are wrong on purpose - the subject here
    is misspelt settings, and the fixtures above are the misspellings.
    Scanning them would report test data as production defects, which is
    the fastest way to teach someone to ignore this test.

    conftest.py is at the repository root rather than in tests/, so
    MOBILITYFLOW_TEST_DATABASE is still seen.
    """

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    found = set()

    for path in root.rglob("*.py"):

        parts = path.parts

        if "__pycache__" in parts or "tests" in parts:
            continue

        if path.name == "config_check.py":
            continue

        found |= _configuration_names(path.read_text(encoding="utf-8"))

    return found


def test_every_known_setting_is_actually_read_somewhere():
    """
    An entry left behind after a setting is deleted is the original
    defect in a new place: the check would accept a variable that nothing
    reads. That is not hypothetical - MOBILITYFLOW_SESSION_URL_FALLBACK
    outlived the feature it controlled, which is why this module exists.
    """

    referenced = _settings_referenced_by_the_application()

    for name in KNOWN_SETTINGS:
        assert name in referenced, (
            f"{name} is registered as a setting but nothing reads it; "
            f"the check would accept a variable that does nothing"
        )


def test_every_setting_the_code_reads_is_registered():
    """
    The other direction, and the one that bites a developer rather than
    an operator: add a setting, forget the registry, and the application
    refuses to start the first time anybody sets it.
    """

    unregistered = _settings_referenced_by_the_application() - set(KNOWN_SETTINGS)

    assert not unregistered, (
        f"read by the code and missing from KNOWN_SETTINGS: "
        f"{sorted(unregistered)} - setting one of these would make the "
        f"application refuse to start"
    )
