"""
Drafting the correspondence a case generates.

Every function here produces something that leaves the building - an
email to a commune, a letter to the cantonal migration office, a
checklist handed to the employee. So each one resolves the case's
correspondence language and passes it to the prompt.

That language is not the language of the person clicking the button. It
is a property of the case, because the authority the letter is addressed
to does not change when a different colleague opens it, and in Valais the
two routinely differ - see core/correspondence.py.

Before this, the prompts were English and the model answered in English
whatever the user had selected. Choosing French translated the buttons
around an English letter to a French-speaking commune.
"""

import logging

from core.ai.engine import ask_ai
from core.ai.prompts import (
    build_email_prompt,
    build_checklist_prompt,
    build_letter_prompt,
)
from core.communication.language_check import looks_like_the_wrong_language
from core.correspondence import resolve_correspondence_language
from db.database import (
    CASE_INDEX_CORRESPONDENCE_LANGUAGE,
)


logger = logging.getLogger(__name__)


def _checked(text, language, what):
    """
    Return the draft, having noted whether it came back in the right
    language.

    The instruction in the prompt is a request, and a small local model
    sometimes declines: a prompt dense with "Switzerland", "canton
    VALAIS" and "Contrôle des habitants" pulls it towards German however
    plainly English was asked for. That happened - the interface was
    English and Generate Email returned German.

    The draft is returned either way. It is not silently retranslated:
    text a user is about to send to an authority should not be quietly
    rewritten by the component that just got it wrong. The page shows the
    warning and the user decides.
    """

    if looks_like_the_wrong_language(text, language):
        logger.warning(
            "Generated %s does not appear to be in %s, which was requested. "
            "The local model has ignored the language instruction.",
            what,
            language,
        )

    return text


def draft_is_in_the_wrong_language(text, case):
    """
    Whether a draft should be shown to the user with a warning.

    Exposed for the page: the generators return plain strings and several
    callers store them, so widening the return type would touch every one
    of them for a flag most do not use.
    """

    return looks_like_the_wrong_language(text, _case_language(case))


def _case_language(case):
    """
    The language this case's correspondence must be written in.

    Reads the stored value positionally through the named constant, and
    tolerates a short row: several callers pass a case tuple from a query
    that predates migration 0006, and a missing value means "not chosen",
    which resolve_correspondence_language already handles by falling back
    to the canton default.
    """

    stored = (
        case[CASE_INDEX_CORRESPONDENCE_LANGUAGE]
        if case is not None and len(case) > CASE_INDEX_CORRESPONDENCE_LANGUAGE
        else None
    )

    canton = case[3] if case is not None and len(case) > 3 else None

    return resolve_correspondence_language(stored, canton)


def fill_email_template(template_text, case, step=None):
    """
    Substitute case fields into a template the customer wrote.

    No language handling: the template is already in whatever language
    its author chose, and rewriting it would be editing their words.
    """

    placeholders = {
        "employee_name": case[1],
        "nationality": case[2],
        "canton": case[3],
        "permit": case[4],
        "business_mode": case[5],
        "employer": case[6],
        "step": step or "",
    }

    try:
        return template_text.format(**placeholders)
    except (KeyError, IndexError):
        return template_text


def generate_email(case, step, tone="formal"):

    employee_name = case[1]
    canton = case[3]

    language = _case_language(case)

    prompt = build_email_prompt(
        employee_name, canton, step, tone, language=language
    )

    return _checked(ask_ai(prompt), language, "email")


def generate_checklist(case, workflow):

    employee_name = case[1]

    language = _case_language(case)

    prompt = build_checklist_prompt(
        employee_name, workflow, language=language
    )

    return _checked(ask_ai(prompt), language, "checklist")


def generate_letter(case, risk, trace, workflow):

    employee_name = case[1]
    nationality = case[2]
    canton = case[3]
    permit = case[4]
    employer = case[6]

    language = _case_language(case)

    prompt = build_letter_prompt(
        employee_name, nationality, canton, permit, employer, risk, trace,
        workflow, language=language,
    )

    return _checked(ask_ai(prompt), language, "letter")
