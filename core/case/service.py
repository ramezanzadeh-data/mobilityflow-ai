from db.database import (
    add_case,
    get_cases_by_company,
    load_case as db_load_case,
    update_task,
    update_document,
    delete_case,
    add_task,
    add_document
)


def create_case(
    employee_name,
    nationality,
    canton,
    permit,
    business_mode,
    employer,
    company,
    risk_level,
    ai_summary,
    assigned_to="admin",
    # Keyword-only, mirroring db.database.add_case: existing callers pass
    # everything up to assigned_to positionally, so these cannot shift an
    # argument into the wrong slot. None means "not recorded" - the
    # obligation engine reports that honestly rather than inferring a
    # legal date from something else.
    *,
    arrival_date=None,
    contract_start_date=None,
    permit_expiry_date=None
):

    return add_case(
        employee_name,
        nationality,
        canton,
        permit,
        business_mode,
        employer,
        company,
        risk_level,
        ai_summary,
        assigned_to,
        arrival_date=arrival_date,
        contract_start_date=contract_start_date,
        permit_expiry_date=permit_expiry_date
    )


def add_case_service(
    employee_name,
    nationality,
    canton,
    permit,
    business_mode,
    employer,
    company,
    risk_level,
    ai_summary,
    assigned_to="admin"
):

    return create_case(
        employee_name,
        nationality,
        canton,
        permit,
        business_mode,
        employer,
        company,
        risk_level,
        ai_summary,
        assigned_to
    )


def load_case(case_id):

    return db_load_case(case_id)


def list_cases(company):

    return get_cases_by_company(company)


def list_company_cases(company):

    return get_cases_by_company(company)


def delete_case_service(case_id):

    return delete_case(case_id)


def attach_workflow_and_documents(case_id, workflow, docs):

    for step in workflow:
        add_task(case_id, step)

    for doc in docs:
        add_document(case_id, doc)


def update_case_service(case_id, data):

    from db.database import update_case

    if not data:
        return

    update_case(
        case_id,
        **data
    )