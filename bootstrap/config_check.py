"""
Startup check that every MOBILITYFLOW_* setting is one the code reads.

Why this exists
---------------
``MOBILITYFLOW_SESSION_URL_FALLBACK=2`` sat at the top of a .env file.
Two things were wrong with it - the variable had been deleted with the
feature it controlled, and the value was meant for a different setting
entirely - and the process did exactly what every process does with an
environment variable it does not read: nothing at all.

The result was worse than a crash. The deployment had an idle timeout
that was never configured, a .env that said otherwise, and an operator
who had reasonably concluded the setting was applied. Testing it appeared
to show the timeout not working, which sent the investigation at the
timeout rather than at the spelling.

That is the shape of the problem: a misspelt configuration key is not a
missing feature, it is a feature that reports itself as present. For a
security control - session lifetime, idle timeout, cookie flags - the gap
between "set" and "believed to be set" is the whole risk.

Deliberately a refusal, not a warning
-------------------------------------
A warning in a container log is read by nobody. The same reasoning as
db/schema_check.py, which refuses to run against a database the code has
outgrown: the point at which this is cheap to fix is startup, and the
point at which it is expensive is a customer asking why a session
outlived its documented timeout.

Refusing on a *stale* variable - one left behind by a removed feature,
which is the case that produced this module - is intentional too. Its
presence is a false statement about the deployment, and deleting a line
is a smaller cost than leaving one behind that lies.

Only MOBILITYFLOW_* is checked. The environment of any real deployment is
full of variables belonging to other things, and a check that guesses at
which of them were meant for this application would be noise.
"""

import difflib
import os
from dataclasses import dataclass


# Every MOBILITYFLOW_* variable the code reads, with what it is for.
#
# This list is the check. A setting added without an entry here makes the
# application refuse to start with that setting present - which is the
# right way round: the failure lands on whoever added it, at the moment
# they add it, rather than on an operator months later.
KNOWN_SETTINGS = {
    "MOBILITYFLOW_BROWSER_SESSION_HOURS":
        "how long one browser login may last at most (auth/browser_session.py)",
    "MOBILITYFLOW_SESSION_IDLE_MINUTES":
        "how long a session survives unused (auth/browser_session.py)",
    "MOBILITYFLOW_SESSION_COOKIE_SECURE":
        "auto | true | false - whether the session cookie is marked Secure",
    "MOBILITYFLOW_API_BASE_PATH":
        "where the API answers as the browser sees it, default /api",
    "MOBILITYFLOW_PSEUDO_LOCALE":
        "show the pseudo-language for translation testing (i18n/translator.py)",
    "MOBILITYFLOW_TEST_DATABASE":
        "name of the database the test suite uses (conftest.py)",
    "MOBILITYFLOW_VERIFY_BASE_URL":
        "target for scripts/verify_session_cookie.py",
}


@dataclass(frozen=True)
class ConfigProblem:

    name: str               # the variable as it was actually set
    suggestion: str | None  # the known setting it was probably meant to be

    def __str__(self):

        if self.suggestion:
            return f"{self.name}  - did you mean {self.suggestion}?"

        return f"{self.name}  - not a setting this version reads"


def find_config_problems(environ=None):
    """
    Every MOBILITYFLOW_* variable set in the environment and read by
    nothing.

    Returns a list of ConfigProblem; empty means the configuration is
    understood. Never raises - deciding what to do about a problem is the
    caller's, and a check that can take down the application it protects
    for a reason of its own is worse than no check.
    """

    environ = os.environ if environ is None else environ

    problems = []

    for name in sorted(environ):

        if not name.startswith("MOBILITYFLOW_"):
            continue

        if name in KNOWN_SETTINGS:
            continue

        # A near miss is by far the likeliest cause, and naming the
        # intended setting turns "this is wrong" into "this is the line
        # to change". cutoff is loose on purpose: the names here are long
        # and share a prefix, so a genuine typo still scores well below a
        # strict threshold.
        close = difflib.get_close_matches(name, KNOWN_SETTINGS, n=1, cutoff=0.6)

        problems.append(ConfigProblem(name, close[0] if close else None))

    return problems


def describe_problems(problems):
    """
    A message for whoever is deploying, written for thirty seconds of
    attention.
    """

    if not problems:
        return ""

    lines = [
        "The environment sets MOBILITYFLOW_* variables this version does "
        "not read.",
        "",
        "Nothing is applying them, so any behaviour they describe is not "
        "configured:",
        "",
    ]

    lines += [f"  - {problem}" for problem in problems]

    lines += [
        "",
        "Fix the spelling in your .env, or remove the line if it belongs "
        "to a setting that no longer exists.",
        "",
        "Settings this version reads:",
        "",
    ]

    lines += [
        f"  {name}\n      {purpose}"
        for name, purpose in sorted(KNOWN_SETTINGS.items())
    ]

    return "\n".join(lines)
