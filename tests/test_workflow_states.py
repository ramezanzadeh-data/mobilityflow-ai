
import pytest

from core.workflow.states import (
    WORKFLOW_STATES,
    get_next_state,
    get_state_index,
    normalize_legacy_state,
    validate_transition,
    InvalidTransitionError,
)


def test_states_order_is_fixed():

    assert WORKFLOW_STATES == [
        "DRAFT", "SUBMITTED", "REVIEW", "EMPLOYER",
        "AUTHORITIES", "DECISION", "COMPLETED"
    ]


def test_next_state_linear_progression():

    assert get_next_state("DRAFT") == "SUBMITTED"
    assert get_next_state("REVIEW") == "EMPLOYER"
    assert get_next_state("DECISION") == "COMPLETED"


def test_next_state_of_completed_is_none():

    assert get_next_state("COMPLETED") is None


def test_state_index_matches_position():

    assert get_state_index("DRAFT") == 0
    assert get_state_index("COMPLETED") == 6


def test_normalize_legacy_states_map_correctly():

    assert normalize_legacy_state("INITIAL_REVIEW") == "DRAFT"
    assert normalize_legacy_state("INITIAL") == "DRAFT"
    assert normalize_legacy_state("CASE_COMPLETED") == "COMPLETED"


def test_normalize_already_valid_state_is_unchanged():

    assert normalize_legacy_state("SUBMITTED") == "SUBMITTED"


def test_normalize_unknown_state_defaults_to_draft():

    assert normalize_legacy_state("SOMETHING_RANDOM") == "DRAFT"


def test_validate_transition_linear_is_allowed():

    assert validate_transition("DRAFT", "SUBMITTED") is True


def test_validate_transition_invalid_jump_raises():

    with pytest.raises(InvalidTransitionError):
        validate_transition("DRAFT", "DECISION")


def test_validate_transition_override_allows_any_jump():

    assert validate_transition("DRAFT", "DECISION", allow_any=True) is True


def test_validate_transition_unknown_target_raises_even_with_override():

    with pytest.raises(InvalidTransitionError):
        validate_transition("DRAFT", "NOT_A_REAL_STATE", allow_any=True)
