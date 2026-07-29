
from db.database import (
    add_task,
    get_tasks,
    delete_tasks_for_case,
    set_task_due_date,
    update_task,
    get_pending_tasks_for_company,
)


def create_task(case_id, title):
    return add_task(case_id, title)


def list_tasks_for_case(case_id):
    return get_tasks(case_id)


def delete_all_for_case(case_id):
    return delete_tasks_for_case(case_id)


def set_due_date(task_id, due_date):
    return set_task_due_date(task_id, due_date)


def set_status(task_id, status):
    return update_task(task_id, status)


def list_pending_for_company(company):
    return get_pending_tasks_for_company(company)
