
from core.rules.rules import get_scenario_note


SCENARIO_JOB_CHANGE = "JOB_CHANGE"
SCENARIO_PERMIT_RENEWAL = "PERMIT_RENEWAL"
SCENARIO_FAMILY_TRANSFER = "FAMILY_TRANSFER"
SCENARIO_CANTON_CHANGE = "CANTON_CHANGE"
SCENARIO_CONTRACT_TERMINATION = "CONTRACT_TERMINATION"

SCENARIO_LABELS = {
    SCENARIO_JOB_CHANGE: "Job Change (new employer)",
    SCENARIO_PERMIT_RENEWAL: "Permit Renewal",
    SCENARIO_FAMILY_TRANSFER: "Family Transfer (reunification)",
    SCENARIO_CANTON_CHANGE: "Canton Change (relocation within Switzerland)",
    SCENARIO_CONTRACT_TERMINATION: "Contract Termination",
}


def _job_change_steps(case):

    nationality = case[2]

    steps = [
        "Verify new employment contract",
        "Confirm new employer eligibility",
    ]

    if nationality == "NON_EU":
        steps.append("Submit permit re-approval request (employer change)")

    steps.append("Update case employer record")

    return steps


def _job_change_documents(case):
    return ["New Employment Contract", "Employer Confirmation Letter"]


def _permit_renewal_steps(case):

    permit = case[4]

    steps = [
        "Collect updated employment proof",
        "Verify permit expiry date",
        "Submit renewal application",
    ]

    if permit == "L":
        steps.append("Confirm fixed-term contract is still active")

    return steps


def _permit_renewal_documents(case):
    return ["Updated Employment Contract", "Current Permit Copy"]


def _family_transfer_steps(case):

    return [
        "Verify family reunification eligibility",
        "Collect family member identity documents",
        "Check housing size/income requirements",
        "Submit family visa/permit applications",
    ]


def _family_transfer_documents(case):
    return ["Family Member Passports", "Marriage/Birth Certificates", "Proof of Housing"]


def _canton_change_steps(case):

    return [
        "De-register from current commune",
        "Register at new canton's migration authority",
        "Register at new commune (Contrôle des habitants)",
        "Transfer permit records to new canton",
    ]


def _canton_change_documents(case):
    return ["Proof of New Address", "De-registration Confirmation"]


def _contract_termination_steps(case):

    nationality = case[2]

    steps = [
        "Confirm contract end date",
        "Notify cantonal authority of termination",
    ]

    if nationality == "NON_EU":
        steps.append("Review permit grace period for new employment search")

    steps.append("Prepare unemployment registration if applicable")

    return steps


def _contract_termination_documents(case):
    return ["Termination Letter", "Final Payslip"]


_SCENARIO_HANDLERS = {
    SCENARIO_JOB_CHANGE: (_job_change_steps, _job_change_documents),
    SCENARIO_PERMIT_RENEWAL: (_permit_renewal_steps, _permit_renewal_documents),
    SCENARIO_FAMILY_TRANSFER: (_family_transfer_steps, _family_transfer_documents),
    SCENARIO_CANTON_CHANGE: (_canton_change_steps, _canton_change_documents),
    SCENARIO_CONTRACT_TERMINATION: (
        _contract_termination_steps, _contract_termination_documents
    ),
}


def apply_scenario(scenario_code, case):

    if scenario_code not in _SCENARIO_HANDLERS:
        raise ValueError(f"Unknown scenario: {scenario_code}")

    steps_fn, documents_fn = _SCENARIO_HANDLERS[scenario_code]

    canton = case[3]

    return {
        "steps": steps_fn(case),
        "documents": documents_fn(case),
        "canton_note": get_scenario_note(canton, scenario_code),
    }
