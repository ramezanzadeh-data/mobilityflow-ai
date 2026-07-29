from core.ai.engine import ask_ai
from core.ai.prompts import (
    build_email_prompt,
    build_checklist_prompt,
    build_letter_prompt,
)


def fill_email_template(template_text, case, step=None):

    placeholders = {
        "employee_name": case[1],
        "nationality": case[2],
        "canton": case[3],
        "permit": case[4],
        "business_mode": case[5],
        "employer": case[6],
        "step": step or "",
    }

    try:
        return template_text.format(**placeholders)
    except (KeyError, IndexError):
        return template_text


def generate_email(case, step, tone="formal"):

    employee_name = case[1]
    canton = case[3]

    prompt = build_email_prompt(employee_name, canton, step, tone)

    return ask_ai(prompt)


def generate_checklist(case, workflow):

    employee_name = case[1]

    prompt = build_checklist_prompt(employee_name, workflow)

    return ask_ai(prompt)


def generate_letter(case, risk, trace, workflow):

    employee_name = case[1]
    nationality = case[2]
    canton = case[3]
    permit = case[4]
    employer = case[6]

    prompt = build_letter_prompt(
        employee_name, nationality, canton, permit, employer, risk, trace, workflow
    )

    return ask_ai(prompt)
