
import io

import pandas as pd

from core.rules.risk import calculate_risk_from_rules
from core.workflow.states import normalize_legacy_state
from i18n.labels import (
    canton_label,
    nationality_label,
    permit_label,
    mode_label,
    workflow_state_label
)


def export_cases_to_excel(cases, lang="en"):

    rows = []

    for case in cases:

        risk_score, _ = calculate_risk_from_rules(case)

        rows.append({
            "Employee": case[1],
            "Nationality (code)": case[2],
            "Nationality": nationality_label(case[2], lang),
            "Canton (code)": case[3],
            "Canton": canton_label(case[3], lang),
            "Permit (code)": case[4],
            "Permit": permit_label(case[4], lang),
            "Business Mode (code)": case[5],
            "Business Mode": mode_label(case[5], lang),
            "Employer": case[6],
            "Status": case[7],
            "Workflow Stage": workflow_state_label(
                normalize_legacy_state(case[8]), lang
            ),
            "Risk Score": risk_score,
            "Created At": case[13],
        })

    df = pd.DataFrame(rows)

    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Cases")

    buffer.seek(0)

    return buffer.getvalue()
