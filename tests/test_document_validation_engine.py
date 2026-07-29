
from unittest.mock import patch

from core.documents.validation import (
    validate_document_against_case,
    check_expiry,
    detect_defects_with_ai,
    suggest_additional_documents_with_ai,
)


def _make_case(name="John Smith", nationality="NON_EU", canton="VALAIS", permit="B", mode="SME"):
    return (1, name, nationality, canton, permit, mode, "Employer")


def test_validate_document_no_mismatch_when_names_match():
    case = _make_case(name="John Smith")
    warnings = validate_document_against_case({"name": "John Smith"}, case)
    assert warnings == []


def test_validate_document_detects_name_mismatch():
    case = _make_case(name="John Smith")
    warnings = validate_document_against_case({"name": "Jane Doe"}, case)
    assert len(warnings) == 1
    assert "mismatch" in warnings[0].lower()


def test_validate_document_no_warning_when_no_name_field_present():
    case = _make_case()
    warnings = validate_document_against_case({}, case)
    assert warnings == []


def test_validate_document_matches_partial_name_overlap():
    case = _make_case(name="John Smith")
    warnings = validate_document_against_case({"name": "Smith John"}, case)
    assert warnings == []


def test_check_expiry_expired():
    status, message = check_expiry({"expiry_date": "2020-01-01"})
    assert status == "expired"
    assert "expired" in message.lower()


def test_check_expiry_valid_future_date():
    status, message = check_expiry({"expiry_date": "2099-01-01"})
    assert status == "valid"


def test_check_expiry_unknown_when_field_missing():
    status, message = check_expiry({})
    assert status == "unknown"


def test_check_expiry_unknown_when_unparseable():
    status, message = check_expiry({"expiry_date": "not-a-real-date"})
    assert status == "unknown"


def test_check_expiry_accepts_alternate_field_name():
    status, _ = check_expiry({"expiration_date": "2099-01-01"})
    assert status == "valid"


def test_detect_defects_flags_empty_text_without_calling_ai():
    issues = detect_defects_with_ai("", "Passport")
    assert len(issues) == 1
    assert "little" in issues[0].lower() or "no text" in issues[0].lower()


@patch("core.documents.validation.ask_ai")
def test_detect_defects_with_ai_parses_json_list(mock_ask_ai):
    mock_ask_ai.return_value = '["Missing signature", "Page 2 appears cut off"]'
    issues = detect_defects_with_ai(
        "Some sufficiently long document text " * 5, "Employment Contract"
    )
    assert issues == ["Missing signature", "Page 2 appears cut off"]


@patch("core.documents.validation.ask_ai")
def test_detect_defects_with_ai_handles_invalid_json_gracefully(mock_ask_ai):
    mock_ask_ai.return_value = "this is not valid json at all"
    issues = detect_defects_with_ai(
        "Some sufficiently long document text " * 5, "Employment Contract"
    )
    assert issues == []


@patch("core.documents.validation.ask_ai")
def test_detect_defects_strips_markdown_fences(mock_ask_ai):
    mock_ask_ai.return_value = '```json\n["Missing date"]\n```'
    issues = detect_defects_with_ai(
        "Some sufficiently long document text " * 5, "CV"
    )
    assert issues == ["Missing date"]


@patch("core.documents.validation.ask_ai")
def test_suggest_additional_documents_parses_json_list(mock_ask_ai):
    mock_ask_ai.return_value = '["Proof of prior Swiss residence"]'
    case = _make_case()
    suggestions = suggest_additional_documents_with_ai(case, [], [])
    assert suggestions == ["Proof of prior Swiss residence"]


@patch("core.documents.validation.ask_ai")
def test_suggest_additional_documents_empty_list_when_nothing_needed(mock_ask_ai):
    mock_ask_ai.return_value = "[]"
    case = _make_case()
    suggestions = suggest_additional_documents_with_ai(case, [], [])
    assert suggestions == []
