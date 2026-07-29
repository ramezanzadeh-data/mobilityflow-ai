
from datetime import date

from core.tasks.service import list_pending_for_company


_DUE_DATE_INDEX = 4


def get_overdue_tasks(company, as_of: date = None):

    if as_of is None:
        as_of = date.today()

    as_of_iso = as_of.isoformat()

    pending = list_pending_for_company(company)

    return [
        task for task in pending
        if task[_DUE_DATE_INDEX] is not None and task[_DUE_DATE_INDEX] < as_of_iso
    ]
