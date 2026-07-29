from pydantic import BaseModel


class CaseSummary(BaseModel):
    id: int
    employee_name: str
    nationality: str
    canton: str
    permit: str
    business_mode: str
    status: str
    workflow_state: str
    risk_score: int


class CaseDetail(CaseSummary):
    employer: str
    company: str
    assigned_to: str
    created_at: str
    ai_summary: str | None = None


class PaginatedCases(BaseModel):
    items: list[CaseSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class TimelineEvent(BaseModel):
    id: int
    event_type: str
    description: str
    created_at: str
