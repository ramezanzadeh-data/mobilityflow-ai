"""
Structured payloads exchanged between the LLM and the Response Formatter.

The LLM never writes the final user-facing sentence directly.

Flow:

    LLM
     |
     v
Structured Payload
     |
     v
Response Formatter
     |
     v
User Response

The formatter is the only component responsible for generating the
final response shown to the user.

For ANALYZE, STATUS, and CHECK_BLOCKERS intents the LLM only fills
validated JSON schemas.

For ACTION intents (CREATE_TASK, ADVANCE_WORKFLOW, APPROVE_CASE,
DOCUMENT_ACTION) payloads are generated from real tool execution
results, never from LLM text.
"""

from typing import List

from pydantic import BaseModel, Field


class AnalysisPayload(BaseModel):
    """
    General case analysis result.

    Used for:
        Intent.ANALYZE

    Contains:
        - blockers
        - missing documents
        - risk factors
        - workflow issues
        - remediation steps

    recommended_next_steps are only corrective actions.
    They must never contain workflow transitions.
    """

    blockers: List[str] = Field(default_factory=list)

    missing_documents: List[str] = Field(
        default_factory=list
    )

    risk_factors: List[str] = Field(
        default_factory=list
    )

    workflow_issues: List[str] = Field(
        default_factory=list
    )

    recommended_next_steps: List[str] = Field(
        default_factory=list
    )


class BlockersPayload(BaseModel):
    """
    Dedicated blocker analysis result.

    Used for:

        Intent.CHECK_BLOCKERS

    This is intentionally smaller than AnalysisPayload.

    Enterprise systems benefit from narrow schemas because:
        - validation is stricter
        - formatter logic is simpler
        - API contracts are clearer
    """

    blockers: List[str] = Field(
        default_factory=list
    )

    missing_documents: List[str] = Field(
        default_factory=list
    )


class StatusPayload(BaseModel):
    """
    Current case status snapshot.

    Used for:

        Intent.STATUS

    Contains only confirmed state information.

    No:
        - risk analysis
        - recommendations
        - compliance interpretation
    """

    case_status: str

    workflow_state: str

    blocking_items: List[str] = Field(
        default_factory=list
    )


class ActionPayload(BaseModel):
    """
    Result of an executed operational action.

    Used for:

        Intent.ACTION

    This payload is created from the actual tool execution result.

    The LLM cannot create or modify this payload.
    """

    tool_name: str

    arguments: dict

    result: str

    success: bool = True