from pydantic import BaseModel


class TaskItem(BaseModel):
    id: int
    case_id: int
    title: str
    status: str
    due_date: str | None = None


class TaskCreate(BaseModel):
    case_id: int
    title: str


class TaskStatusUpdate(BaseModel):
    status: str


class TaskDueDateUpdate(BaseModel):
    due_date: str | None = None
