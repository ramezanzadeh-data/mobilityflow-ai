
from core.workflow.states import WORKFLOW_STATES as _STATES
from i18n.labels import WORKFLOW_STATE_LABELS as _LABELS

WORKFLOW_STATES = {
    state: _LABELS["en"][state]
    for state in _STATES
}
