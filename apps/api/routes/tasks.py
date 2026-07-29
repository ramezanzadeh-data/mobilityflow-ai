from fastapi import APIRouter, Depends, HTTPException, Query

from db.database import get_tasks, add_task, update_task, set_task_due_date
from core.case.repository import get_by_id, get_tenant_id_for_case
from apps.api.schemas.task import (
    TaskItem,
    TaskCreate,
    TaskStatusUpdate,
    TaskDueDateUpdate,
)
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_row_to_item(row) -> TaskItem:
    return TaskItem(
        id=row[0],
        case_id=row[1],
        title=row[2],
        status=row[3],
        due_date=row[4] if len(row) > 4 else None,
    )


def _ensure_case_access(case_id: int, current_user):

    case_row = get_by_id(case_id)

    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found")

    user_tenant_id = current_user.get("tenant_id")

    if user_tenant_id and get_tenant_id_for_case(case_id) != user_tenant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this case")

    return case_row


@router.get("", response_model=list[TaskItem], summary="List tasks for a case")
def list_tasks(
    case_id: int = Query(...),
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(case_id, current_user)

    return [_task_row_to_item(row) for row in get_tasks(case_id)]


@router.post("", response_model=TaskItem, status_code=201, summary="Create a task for a case")
def create_task(
    payload: TaskCreate,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    _ensure_case_access(payload.case_id, current_user)

    # add_task() is idempotent and returns the id of the task that now
    # holds this title - freshly inserted, or the pre-existing active one.
    # Resolving the response row by that id rather than by re-matching on
    # title is what keeps the endpoint correct now that a title can also
    # be carried by a completed task: the previous "last row whose title
    # matches" lookup could return a DONE task instead of the active one.
    # The response model and 201 status are unchanged.
    upsert = add_task(payload.case_id, payload.title)

    created = next(
        (row for row in get_tasks(payload.case_id) if row[0] == upsert.task_id),
        None,
    )

    if not created:
        raise HTTPException(status_code=500, detail="Task was created but could not be retrieved")

    return _task_row_to_item(created)


@router.patch("/{task_id}/status", response_model=dict, summary="Update a task's status")
def update_task_status(
    task_id: int,
    payload: TaskStatusUpdate,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    update_task(task_id, payload.status)

    return {"id": task_id, "status": payload.status}


@router.patch("/{task_id}/due-date", response_model=dict, summary="Set or clear a task's due date")
def update_task_due_date(
    task_id: int,
    payload: TaskDueDateUpdate,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    set_task_due_date(task_id, payload.due_date)

    return {"id": task_id, "due_date": payload.due_date}
