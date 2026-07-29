
WORKFLOW_STATES = [
    "DRAFT",
    "SUBMITTED",
    "REVIEW",
    "EMPLOYER",
    "AUTHORITIES",
    "DECISION",
    "COMPLETED",
]


_NEXT_STATE = {
    state: WORKFLOW_STATES[i + 1]
    for i, state in enumerate(WORKFLOW_STATES[:-1])
}


_LEGACY_STATE_MAP = {
    "INITIAL": "DRAFT",
    "INITIAL_REVIEW": "DRAFT",
    "DOCUMENT_COLLECTION": "SUBMITTED",
    "PERMIT_APPLICATION": "REVIEW",
    "COMMUNE_REGISTRATION": "AUTHORITIES",
    "AUTHORITY_REVIEW": "AUTHORITIES",
    "CASE_COMPLETED": "COMPLETED",
}


class InvalidTransitionError(Exception):
    pass


def is_valid_state(state):
    return state in WORKFLOW_STATES


def normalize_legacy_state(state):

    if is_valid_state(state):
        return state

    return _LEGACY_STATE_MAP.get(state, "DRAFT")


def get_state_index(state):

    if state not in WORKFLOW_STATES:
        return 0

    return WORKFLOW_STATES.index(state)


def get_next_state(current_state):

    return _NEXT_STATE.get(current_state)


def validate_transition(current_state, target_state, allow_any=False):

    if not is_valid_state(target_state):
        raise InvalidTransitionError(f"Unknown workflow state: {target_state}")

    if allow_any:
        return True

    if target_state == get_next_state(current_state):
        return True

    raise InvalidTransitionError(
        f"Cannot move from {current_state} to {target_state} in the "
        f"normal linear flow. Use the manual override if this is intentional."
    )
