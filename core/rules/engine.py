
from core.workflow.engine import build_workflow


def build_workflow_from_rules(case):

    nationality = case[2]
    canton = case[3]
    permit = case[4]
    business_mode = case[5]

    return build_workflow(
        nationality=nationality,
        permit=permit,
        canton=canton,
        mode=business_mode
    )
