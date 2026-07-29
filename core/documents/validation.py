
import json
from datetime import datetime, date

from core.ai.engine import ask_ai
from core.ai.prompts import (
    build_defect_detection_prompt,
    build_additional_documents_prompt,
)


def validate_document_against_case(key_facts, case):

    warnings = []

    employee_name = (case[1] or "").strip().lower()

    name_candidates = [
        key_facts.get("name"),
        key_facts.get("full_name"),
        key_facts.get("employee_name"),
    ]

    for candidate in name_candidates:

        if not candidate:
            continue

        candidate_clean = candidate.strip().lower()

        case_tokens = set(employee_name.split())
        candidate_tokens = set(candidate_clean.split())

        if case_tokens and candidate_tokens and not (case_tokens & candidate_tokens):
            warnings.append(
                f"Name mismatch: document shows '{candidate}' but the case "
                f"employee is '{case[1]}'."
            )

        break

    return warnings


def _try_parse_date(date_str):

    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%B %d, %Y",
        "%d %B %Y"
    ]

    for fmt in formats:

        try:
            return datetime.strptime(date_str.strip(), fmt).date()

        except (ValueError, AttributeError):
            continue

    return None


def check_expiry(key_facts):

    expiry_str = (
        key_facts.get("expiry_date")
        or key_facts.get("expiration_date")
    )

    if not expiry_str:
        return "unknown", "No expiry date detected in this document."


    parsed = _try_parse_date(expiry_str)


    if not parsed:

        return (
            "unknown",
            f"Found an expiry-like field ('{expiry_str}') but could not "
            f"parse it as a date."
        )


    days_left = (parsed - date.today()).days


    if days_left < 0:

        return (
            "expired",
            f"This document expired {-days_left} day(s) ago ({expiry_str})."
        )


    if days_left <= 90:

        return (
            "expiring_soon",
            f"This document expires in {days_left} day(s) ({expiry_str}) - "
            f"renewal may be needed soon."
        )


    return (
        "valid",
        f"This document is valid until {expiry_str} "
        f"({days_left} days remaining)."
    )


def _parse_json_list(raw_response):

    try:

        cleaned = raw_response.strip()


        if cleaned.startswith("```"):

            cleaned = (
                cleaned
                .strip("`")
                .replace("json", "", 1)
                .strip()
            )


        parsed = json.loads(cleaned)


        if isinstance(parsed, list):

            return [
                str(item)
                for item in parsed
            ]


        return []


    except (json.JSONDecodeError, AttributeError, TypeError):

        return []


def detect_defects_with_ai(raw_text, document_type):

    if not raw_text or len(raw_text.strip()) < 20:

        return [
            "Very little or no text was extracted - the scan may be blank, "
            "illegible, or OCR failed. Manual review recommended."
        ]


    prompt = build_defect_detection_prompt(raw_text, document_type)

    raw_response = ask_ai(prompt)

    return _parse_json_list(raw_response)


def suggest_additional_documents_with_ai(
    case,
    existing_documents,
    missing_documents_rule_based
):

    existing_names = (
        ", ".join(d[2] for d in existing_documents)
        or "None"
    )

    rule_based_missing = (
        ", ".join(missing_documents_rule_based)
        or "None"
    )


    prompt = build_additional_documents_prompt(case, existing_names, rule_based_missing)

    raw_response = ask_ai(prompt)

    return _parse_json_list(raw_response)