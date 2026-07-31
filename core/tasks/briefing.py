"""
Operational briefing for a single workflow task on a single case.

What this replaces
------------------
The AI button beside each task sent the model this, and only this::

    Explain this Swiss relocation task:
    {task title}
    Give a short operational explanation.

One line of text. No case, no nationality, no permit, no documents, no
risk. So the model answered the only question it had been asked - "what
is this kind of task?" - and produced a general article about Swiss
immigration. Reported as the AI writing essays instead of helping; the
essay was the symptom, and the missing case was the cause.

Why this is computed rather than generated
------------------------------------------
The fields a professional acts on are facts, not prose:

    Required Documents      declared in the catalogue
    Missing Documents       required minus uploaded
    Blocking Conditions     derived from the two above
    Compliance Checks       read from the case row
    Can Advance? / Reason   derived

Not one of them needs a language model, and putting a model in front of
them would make every one of them occasionally wrong. "Can Advance? No -
Employment Contract missing" is a sentence a consultant acts on and a
customer is billed against. It has to be reproducible, auditable, and the
same on Tuesday as it was on Monday.

There is a second reason, which is commercial rather than technical: this
works when the model does not. The local model has already been observed
timing out and answering in the wrong language. A briefing that degrades
to nothing when Ollama is slow is a feature a customer cannot rely on,
and a feature a customer cannot rely on is not one they will renew for.

What this deliberately does not report
--------------------------------------
Estimated duration. No Swiss authority publishes per-step durations, so
any number here would be invented, and a consultant would repeat it to a
client as a commitment. Target durations are a per-customer SLA and
belong in tenant settings.

Everything below returns structured data. Rendering is the page's job -
see apps/web/views/case_detail.py.
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


CATALOGUE_FILE = "valais_task_catalogue.json"

_DATA_DIRECTORY = Path(__file__).resolve().parent.parent.parent / "data"

_cache = {}


# Status vocabulary. Fixed strings rather than free text so the page can
# style them and tests can assert on them.
COMPLETE = "COMPLETE"
PENDING = "PENDING"
BLOCKED = "BLOCKED"
WAITING_ON_AUTHORITY = "WAITING_ON_AUTHORITY"
NOT_DEFINED = "NOT_DEFINED"


def clear_cache():
    _cache.clear()


def _catalogue():

    if "catalogue" not in _cache:

        path = _DATA_DIRECTORY / CATALOGUE_FILE

        try:
            _cache["catalogue"] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("the task catalogue could not be read")
            # An empty catalogue makes every task report "not defined",
            # which is the honest degradation: the product says it does
            # not know rather than describing tasks it cannot see.
            _cache["catalogue"] = {"tasks": {}}

    return _cache["catalogue"]


def task_key(title):
    """
    The catalogue key for a task title.

    Titles are matched, not stored, because `tasks.title` is the
    uniqueness key inherited from migration 0001 and changing it would
    break every existing row. Normalising here keeps the catalogue joined
    to the workflow without a migration; a `task_key` column is the right
    long-term shape and is recorded as such in the module docstring of
    core/workflow/engine.py.
    """

    if not title:
        return None

    normalised = re.sub(r"[^a-z0-9]+", "_", str(title).strip().lower())

    return normalised.strip("_") or None


def definition(title):
    """The catalogue entry for a task title, or None if it has none."""

    key = task_key(title)

    if not key:
        return None

    return _catalogue().get("tasks", {}).get(key)


def owners():
    """The fixed set of owner roles."""

    return tuple(_catalogue().get("_meta", {}).get("owners", ()))


def _uploaded_document_names(documents):
    """
    Names of documents actually held, lowercased.

    A document counts only when its status says so. A row that exists
    with status MISSING is a checklist entry, not evidence, and treating
    it as evidence is how a case with nothing uploaded would report
    itself complete.
    """

    names = []

    for document in documents or []:

        # get_documents() uses SELECT *: [2] is doc_type, [3] is status.
        # Guarded by tests/test_case_row_indices.py.
        try:
            name, status = document[2], document[3]
        except (IndexError, TypeError):
            continue

        if str(status).upper() == "UPLOADED":
            names.append(str(name).lower())

    return names


def _document_is_held(required, uploaded_names):

    needle = required.lower()

    return any(needle in held or held in needle for held in uploaded_names)


def _field_value(case_fields, name):

    value = (case_fields or {}).get(name)

    if value is None:
        return None

    text = str(value).strip()

    return text or None


def build_task_briefing(title, case_fields, documents, task_status=None,
                        risk_score=None):
    """
    Everything known about one task on one case.

    Args:
        title: The workflow task title as stored on the task row.
        case_fields: Mapping of case column name to value. Built by the
            caller from load_case() so this module never indexes a case
            tuple - that positional pattern has already produced one
            silent defect in this codebase.
        documents: Rows from get_documents() for the case.
        task_status: The stored status of the task row, if any.
        risk_score: The case risk score, if computed.

    Returns a dict. Every factual field is derived here; nothing in it
    comes from a language model.
    """

    entry = definition(title)

    if entry is None:
        # An honest refusal. The workflow can emit a task the catalogue
        # does not define - a new branch in build_workflow, or a canton
        # outside the supported scope - and describing it anyway is
        # exactly the invention this design exists to prevent.
        return {
            "title": title,
            "defined": False,
            "status": NOT_DEFINED,
            "purpose": None,
            "owner": None,
            "required_documents": [],
            "missing_documents": [],
            "missing_case_fields": [],
            "blocking_conditions": [],
            "compliance_checks": [],
            "can_advance": None,
            "reason": None,
            "next_action": None,
            "risk_score": risk_score,
        }

    uploaded_names = _uploaded_document_names(documents)

    required_documents = list(entry.get("required_documents") or [])

    missing_documents = [
        name for name in required_documents
        if not _document_is_held(name, uploaded_names)
    ]

    required_fields = list(entry.get("requires_case_fields") or [])

    missing_fields = [
        name for name in required_fields
        if _field_value(case_fields, name) is None
    ]

    # Compliance checks: one line per thing that was supposed to be
    # recorded, each either satisfied or not. Presented as checks rather
    # than as a score because a professional needs to know which one
    # failed, and a percentage cannot say.
    compliance_checks = [
        {
            "label": name,
            "satisfied": _field_value(case_fields, name) is not None,
            "value": _field_value(case_fields, name),
        }
        for name in required_fields
    ]

    compliance_checks.extend(
        {
            "label": name,
            "satisfied": name not in missing_documents,
            "value": None,
        }
        for name in required_documents
    )

    blocking_conditions = []

    for name in missing_documents:
        blocking_conditions.append(f"{name} not uploaded")

    for name in missing_fields:
        blocking_conditions.append(f"{name} not recorded on the case")

    waiting_on_authority = bool(entry.get("blocked_by_authority"))

    if waiting_on_authority:
        status = WAITING_ON_AUTHORITY
    elif blocking_conditions:
        status = BLOCKED
    elif str(task_status or "").upper() in ("DONE", "COMPLETE", "COMPLETED"):
        status = COMPLETE
    else:
        status = PENDING

    # Waiting on an authority is not the same as being blocked, and
    # collapsing the two would tell a user to chase something nobody on
    # their side can move.
    if waiting_on_authority:
        can_advance = False
        reason = "Waiting on the cantonal authority. No action on your side advances this."
        next_action = None

    elif blocking_conditions:
        can_advance = False
        reason = blocking_conditions[0]
        next_action = (
            f"Upload {missing_documents[0]}." if missing_documents
            else f"Record {missing_fields[0]} on the case."
        )

    else:
        can_advance = True
        reason = "Every declared requirement for this task is satisfied."
        next_action = None

    return {
        "title": entry.get("title") or title,
        "defined": True,
        "status": status,
        "purpose": entry.get("purpose"),
        "owner": entry.get("owner"),
        "supported_by": entry.get("supported_by"),
        "note": entry.get("note"),
        "required_documents": required_documents,
        "missing_documents": missing_documents,
        "missing_case_fields": missing_fields,
        "blocking_conditions": blocking_conditions,
        "compliance_checks": compliance_checks,
        "can_advance": can_advance,
        "reason": reason,
        "next_action": next_action,
        "risk_score": risk_score,
    }
