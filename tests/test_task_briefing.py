"""
The task briefing is computed, and must stay computed.

The AI button beside each task sent the model one line - the task title -
and nothing else. No case, no documents, no risk. So the only question it
could answer was "what is this kind of task in general", and it answered
with an article about Swiss immigration. The essay was the symptom; the
case never being in the prompt was the cause.

The redesign does not fix the prompt. It removes the model from the path,
because every field a consultant acts on is a fact:

    Required Documents   declared
    Missing Documents    required minus uploaded
    Blocking Conditions  derived
    Can Advance? Reason  derived

"Can Advance? No - Employment Contract not uploaded" is a sentence
someone acts on and a customer is billed against. Generated, it is
occasionally wrong and never auditable. Computed, it is the same every
time and can be explained line by line.

These tests hold that property and the refusals around it. The most
important one is not that a complete case advances - it is that an
incomplete one does not, and that a task the catalogue does not define
produces nothing rather than a plausible description.
"""

import pytest

from core.tasks.briefing import (
    BLOCKED,
    COMPLETE,
    NOT_DEFINED,
    PENDING,
    WAITING_ON_AUTHORITY,
    build_task_briefing,
    definition,
    owners,
    task_key,
)


CASE = {
    "id": 1,
    "employee_name": "Anna Müller",
    "nationality": "NON_EU",
    "canton": "VALAIS",
    "permit": "F",
    "business_mode": "RELOCATION",
    "employer": "Lonza AG",
    "arrival_date": "2026-06-01",
    "contract_start_date": "2026-07-01",
    "permit_expiry_date": None,
    "commune": "Sierre",
}


def document(name, status="UPLOADED", doc_id=1):
    """Shaped like a get_documents() row: SELECT *, [2] type, [3] status."""

    return (doc_id, 1, name, status, "", "", "")


# ------------------------------------------------------------ matching ---

def test_a_workflow_title_finds_its_catalogue_entry():
    """
    The join between build_workflow()'s strings and the catalogue. If
    normalisation drifts, every task reports "not defined" and the
    feature silently empties out.
    """

    assert task_key("Initial case review") == "initial_case_review"
    assert task_key("Commune registration (Valais)") == "commune_registration_valais"


@pytest.mark.parametrize("title", [
    "Initial case review",
    "Collect identity documents",
    "Verify employment contract",
    "Validate visa eligibility",
    "Check immigration quota",
    "Prepare entry authorization",
    "Process EU registration",
    "Prepare permit application",
    "Collect biometric data",
    "Schedule cantonal appointment",
    "Validate existing permit",
    "Employer eligibility verification",
    "Validate permanent residence",
    "Cross-border worker verification",
    "Tax registration",
    "Social insurance registration",
    "Commune registration (Valais)",
    "Cantonal approval",
    "Housing registration",
    "Family relocation support",
    "Employer sponsorship verification",
    "SME compliance review",
    "Close relocation case",
])
def test_every_task_the_workflow_can_emit_is_defined(title):
    """
    Enumerated from core/workflow/engine.py.

    A task the workflow produces but the catalogue does not define shows
    the user nothing. That is the correct behaviour for an unknown task
    and the wrong outcome for a known one, so the full list is pinned
    here - if a branch is added to build_workflow without a catalogue
    entry, this fails rather than the feature quietly going blank.
    """

    assert definition(title) is not None, (
        f"build_workflow() can emit {title!r} and the catalogue has no "
        f"entry for it, so the briefing renders nothing"
    )


# ------------------------------------------------- refusing to invent ---

def test_an_undefined_task_says_so_instead_of_describing_itself():
    """
    The property this whole design exists for.

    A model handed an unknown task title produces a confident
    description; there is nothing in its output that signals it was
    guessing. This returns defined=False and no content at all.
    """

    briefing = build_task_briefing("Some task nobody defined", CASE, [])

    assert briefing["defined"] is False
    assert briefing["status"] == NOT_DEFINED
    assert briefing["purpose"] is None
    assert briefing["required_documents"] == []
    assert briefing["can_advance"] is None
    assert briefing["reason"] is None


def test_no_task_claims_a_duration():
    """
    No Swiss authority publishes per-step durations. A number here would
    be invented, and a consultant would repeat it to a client as a
    commitment - the same trap as the renewal windows, where three Valais
    communes published three different answers to a question the product
    was answering from one hardcoded offset.
    """

    briefing = build_task_briefing("Initial case review", CASE, [])

    assert "duration" not in briefing
    assert "estimated_duration" not in briefing


# ---------------------------------------------------- can this advance ---

def test_a_missing_document_blocks_the_task_and_names_itself():

    briefing = build_task_briefing(
        "Verify employment contract", CASE, documents=[]
    )

    assert briefing["can_advance"] is False
    assert briefing["status"] == BLOCKED
    assert "Employment Contract" in briefing["missing_documents"]
    assert "Employment Contract" in briefing["reason"]
    assert briefing["next_action"] == "Upload Employment Contract."


def test_a_satisfied_task_can_advance():

    briefing = build_task_briefing(
        "Verify employment contract",
        CASE,
        documents=[document("Employment Contract")],
    )

    assert briefing["can_advance"] is True
    assert briefing["missing_documents"] == []
    assert briefing["blocking_conditions"] == []


def test_a_document_that_is_only_a_checklist_row_does_not_count():
    """
    A row with status MISSING is a checklist entry, not evidence.
    Counting it would let a case with nothing uploaded report itself
    complete - and the whole product rests on that distinction.
    """

    briefing = build_task_briefing(
        "Verify employment contract",
        CASE,
        documents=[document("Employment Contract", status="MISSING")],
    )

    assert briefing["can_advance"] is False
    assert "Employment Contract" in briefing["missing_documents"]


def test_a_missing_case_field_blocks_the_task_too():
    """
    Not only documents. "Commune registration" cannot proceed without a
    recorded commune, because the deadline is not derivable from the
    canton - three Valais communes publish three different windows.
    """

    without_commune = dict(CASE, commune=None)

    briefing = build_task_briefing(
        "Commune registration (Valais)",
        without_commune,
        documents=[document("Passport Copy"),
                   document("Commune Registration Form", doc_id=2)],
    )

    assert briefing["can_advance"] is False
    assert "commune" in briefing["missing_case_fields"]
    assert briefing["next_action"] == "Record commune on the case."


def test_waiting_on_an_authority_is_not_the_same_as_blocked():
    """
    Collapsing the two would tell a consultant to chase something nobody
    on their side can move, which is worse than saying nothing: it
    manufactures work and erodes trust in every other recommendation.
    """

    briefing = build_task_briefing("Cantonal approval", CASE, documents=[])

    assert briefing["status"] == WAITING_ON_AUTHORITY
    assert briefing["can_advance"] is False
    assert briefing["next_action"] is None
    assert "authority" in briefing["reason"].lower()


def test_a_finished_task_reports_complete():

    briefing = build_task_briefing(
        "Verify employment contract",
        CASE,
        documents=[document("Employment Contract")],
        task_status="DONE",
    )

    assert briefing["status"] == COMPLETE


def test_an_unfinished_but_unblocked_task_is_pending():

    briefing = build_task_briefing(
        "Verify employment contract",
        CASE,
        documents=[document("Employment Contract")],
        task_status="OPEN",
    )

    assert briefing["status"] == PENDING


# -------------------------------------------------------------- owners ---

def test_every_task_names_an_owner_from_the_fixed_set():
    """
    A fixed set rather than free text, so tasks can later be routed to a
    real user by role. Free-text owners cannot be routed and cannot be
    counted.
    """

    import json
    from pathlib import Path

    catalogue = json.loads(
        (
            Path(__file__).resolve().parent.parent
            / "data" / "valais_task_catalogue.json"
        ).read_text(encoding="utf-8")
    )

    allowed = set(owners())

    assert allowed, "the owner vocabulary is empty"

    for key, entry in catalogue["tasks"].items():

        assert entry.get("owner") in allowed, (
            f"{key} has owner {entry.get('owner')!r}, which is not one of "
            f"{sorted(allowed)}"
        )


def test_every_task_states_a_purpose():

    import json
    from pathlib import Path

    catalogue = json.loads(
        (
            Path(__file__).resolve().parent.parent
            / "data" / "valais_task_catalogue.json"
        ).read_text(encoding="utf-8")
    )

    for key, entry in catalogue["tasks"].items():
        assert (entry.get("purpose") or "").strip(), f"{key} has no purpose"


def test_required_documents_are_only_ones_the_product_can_check():
    """
    A requirement the product cannot verify is worse than an absent one,
    because it renders identically to a verified one. core/documents/
    analyzer.py decides which names exist; the catalogue may only name
    those.
    """

    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    catalogue = json.loads(
        (root / "data" / "valais_task_catalogue.json").read_text(encoding="utf-8")
    )

    tracked = set(catalogue["_meta"]["tracked_documents"])

    analyzer = (root / "core" / "documents" / "analyzer.py").read_text(
        encoding="utf-8"
    )

    for name in tracked:
        assert name in analyzer, (
            f"{name!r} is declared tracked but analyzer.py never mentions "
            f"it, so nothing ever satisfies it"
        )

    for key, entry in catalogue["tasks"].items():
        for name in entry.get("required_documents") or []:
            assert name in tracked, (
                f"{key} requires {name!r}, which the product does not "
                f"track - it would show as permanently missing"
            )


# ------------------------------------------- the model is not in the path ---

def test_the_briefing_module_does_not_call_a_language_model():
    """
    The architectural property, asserted rather than trusted.

    Every field here is a fact a consultant acts on. Routing any of them
    through a model makes them occasionally wrong and never auditable,
    and it makes the feature stop working whenever the local model is
    slow - which has already happened in this product.
    """

    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "core" / "tasks" / "briefing.py"
    ).read_text(encoding="utf-8")

    tree = ast.parse(source)

    imported = set()

    for node in ast.walk(tree):

        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    offenders = {name for name in imported if "ai" in name.split(".")}

    assert not offenders, (
        f"briefing.py imports {sorted(offenders)} - the facts it produces "
        f"must not pass through a language model"
    )


def test_the_page_no_longer_asks_a_model_to_explain_a_task():
    """
    The original defect, at the call site. The prompt was
    "Explain this Swiss relocation task: {title}" with no case attached.
    """

    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "apps" / "web" / "views" / "case_detail.py"
    ).read_text(encoding="utf-8")

    assert "Explain this Swiss relocation task" not in source, (
        "the task button still asks the model to explain a task title "
        "with no case attached, which is what produced general articles"
    )

    assert "build_task_briefing" in source


# ------------------------------------------------------ the analyzer bug ---

def test_an_uploaded_commune_form_stops_being_reported_missing():
    """
    Every other requirement in analyze_documents() is guarded by
    `if not any(...)`. The Valais one was not: it appended
    unconditionally, so Commune Registration Form was missing on every
    Valais case forever, including straight after the user uploaded it.

    The product is Valais-only, so this was every case in it - one
    requirement that could never be discharged, a compliance score that
    could not reach 100, and any "are all documents present" gate
    answering no permanently.
    """

    from core.documents.analyzer import analyze_documents

    case = (1, "Anna", "NON_EU", "VALAIS", "F", "RELOCATION")

    documents = [
        document("Passport Copy"),
        document("Employment Contract", doc_id=2),
        document("CV", doc_id=3),
        document("Entry Visa Documentation", doc_id=4),
        document("Commune Registration Form", doc_id=5),
    ]

    result = analyze_documents(case, documents)

    assert "Commune Registration Form" not in result["missing_documents"], (
        "the uploaded commune registration form is still reported missing"
    )


def test_an_absent_commune_form_is_still_reported_missing():
    """
    The other half. Fixing the false positive must not remove the check.
    """

    from core.documents.analyzer import analyze_documents

    case = (1, "Anna", "NON_EU", "VALAIS", "F", "RELOCATION")

    result = analyze_documents(case, [document("Passport Copy")])

    assert "Commune Registration Form" in result["missing_documents"]
