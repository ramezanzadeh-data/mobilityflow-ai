
from db.database import (
    load_case,
    get_cases_by_company,
    get_cases_by_company_paginated,
    count_cases_by_company,
    get_cases_by_tenant,
    add_case,
    update_case,
    delete_case,
    get_case_events,
    log_case_event,
    get_case_company,
    get_case_tenant_id,
)


def get_by_id(case_id):
    return load_case(case_id)


def list_by_company(company):
    return get_cases_by_company(company)


def list_by_company_paginated(company, page_size, offset):
    return get_cases_by_company_paginated(company, page_size, offset)


def count_by_company(company):
    return count_cases_by_company(company)


def create(**fields):
    return add_case(**fields)


def update(case_id, **fields):
    return update_case(case_id, **fields)


def delete(case_id):
    return delete_case(case_id)


def get_timeline(case_id):
    return get_case_events(case_id)


def log_event(case_id, event_type, description):
    return log_case_event(case_id, event_type, description)


def get_company_for_case(case_id):
    return get_case_company(case_id)


def get_tenant_id_for_case(case_id):
    return get_case_tenant_id(case_id)


def list_by_tenant(tenant_id):
    return get_cases_by_tenant(tenant_id)
