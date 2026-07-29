
from dataclasses import dataclass
from typing import Optional


@dataclass
class Case:
    id: int
    employee_name: str
    nationality: str
    canton: str
    permit: str
    business_mode: str
    employer: str
    status: str
    workflow_state: str
    risk_level: Optional[int]
    ai_summary: Optional[str]
    company: str
    assigned_to: str
    created_at: str
    case_history: Optional[str] = None
    audit_log: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Case":

        return cls(
            id=row[0],
            employee_name=row[1],
            nationality=row[2],
            canton=row[3],
            permit=row[4],
            business_mode=row[5],
            employer=row[6],
            status=row[7],
            workflow_state=row[8],
            risk_level=row[9],
            ai_summary=row[10],
            company=row[11],
            assigned_to=row[12],
            created_at=row[13],
            case_history=row[14] if len(row) > 14 else None,
            audit_log=row[15] if len(row) > 15 else None,
        )

    def to_row(self) -> tuple:

        return (
            self.id, self.employee_name, self.nationality, self.canton,
            self.permit, self.business_mode, self.employer, self.status,
            self.workflow_state, self.risk_level, self.ai_summary,
            self.company, self.assigned_to, self.created_at,
            self.case_history, self.audit_log,
        )
