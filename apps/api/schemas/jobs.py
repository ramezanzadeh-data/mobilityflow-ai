from typing import Any

from pydantic import BaseModel


class JobEnqueued(BaseModel):
    task_id: str
    status_url: str


class JobStatus(BaseModel):
    task_id: str
    state: str
    result: Any | None = None
