"""
Prompt construction for the local LLM.

Correspondence prompts take a language
--------------------------------------
Everything the product drafts on a customer's behalf - emails to a
commune, letters to the cantonal migration office, checklists a
specialist prints - used to be written in English regardless of what the
user had selected, because the prompts themselves are English and the
model answers in the language it is addressed in. Choosing French
translated the buttons around a French-speaking commune's English letter.

So the correspondence builders now take an explicit language and instruct
the model in it. The language comes from the case, not from the session:
see core/correspondence.py for why Valais makes that distinction
unavoidable.

Analytical prompts deliberately do not
--------------------------------------
Document classification, defect detection and the recommendation prompt
return data - a JSON document type, a list of defects, a short internal
note. Their output is consumed by code or read by the specialist who
already has a translated interface around it, and asking the model to
produce structured output in a language it was not instructed in is how
schema-conforming replies stop conforming. They stay in English.

The line is: if it goes to an authority, it takes a language; if it comes
back into the product, it does not.
"""


# Written to the model in the language's own name. "Antwort auf Deutsch"
# is followed more reliably than "answer in de", and the endonym is
# unambiguous where an ISO code is not.
_LANGUAGE_INSTRUCTIONS = {
    "de": "Deutsch (German)",
    "fr": "Français (French)",
    "it": "Italiano (Italian)",
    "en": "English",
}

DEFAULT_CORRESPONDENCE_LANGUAGE = "en"


def _language_name(language):
    """
    The model-facing name for a language code.

    Falls back to English rather than passing an unknown code through. A
    prompt saying "write this in xx" produces confident output in
    something, and nobody reviewing the draft would know what went wrong.
    """

    return _LANGUAGE_INSTRUCTIONS.get(
        (language or "").lower(),
        _LANGUAGE_INSTRUCTIONS[DEFAULT_CORRESPONDENCE_LANGUAGE],
    )


def _language_rule(language):
    """
    The instruction block appended to every correspondence prompt.

    Stated twice - once as the language, once as a prohibition on
    English - because a model given English instructions and asked for
    French routinely produces a French body with an English subject line
    or an English sign-off, and a half-translated letter to an authority
    reads worse than an English one.
    """

    name = _language_name(language)

    return f"""
LANGUAGE:
- Write the ENTIRE output in {name}.
- This includes the subject line, the salutation, the body and the
  closing. Do not leave any part in English.
- Use the administrative register a Swiss authority would expect in
  {name}, not a literal translation of English phrasing.
"""


AGENT_SYSTEM_PROMPT = """You are an AI case manager assistant for a Swiss relocation \
/ immigration company. You have tools to read REAL data about a specific case \
(risk score, missing documents, workflow steps, timeline) and to create a \
follow-up task when needed.

Rules:
- Always use the tools to check real data before answering - never guess or \
invent facts about a case.
- Only call create_task_for_case when you are confident a new, specific \
action item is genuinely needed and not already covered.
- You cannot change the case's official workflow stage yourself - only \
recommend it via recommend_workflow_advance. A human always makes that final call.
- Once you have enough information, give ONE concise, operational final answer \
(max 6 sentences) - do not just repeat the raw tool outputs back verbatim.
"""


def build_email_prompt(
    employee_name, canton, step, tone="formal",
    language=DEFAULT_CORRESPONDENCE_LANGUAGE,
):
    """
    An email a specialist will send to a Swiss authority.

    ``language`` is the case's correspondence language, not the user's
    interface language - see core/correspondence.py.
    """

    return f"""
You are an administrative assistant in Switzerland.

Write a {tone} email for the following task:

Task: {step}
Employee name: {employee_name}
Canton: {canton}

Rules:
- {tone} tone
- concise
- Swiss administrative style
- include a subject line at the top, in the output language, on its own
  first line
{_language_rule(language)}"""


def build_checklist_prompt(
    employee_name, workflow, language=DEFAULT_CORRESPONDENCE_LANGUAGE,
):
    """
    A printable checklist.

    Takes a language because it is printed and handed to people - often
    the employee themselves, who is the one person in the process least
    likely to read English.
    """

    steps_text = "\n".join(f"- {s}" for s in workflow)

    return f"""
You are a Swiss relocation operations assistant.

Create a clean, printable CHECKLIST for the case of {employee_name}
based on these workflow steps:

{steps_text}

Format:
- Add a title
- Use checkbox-style lines like "[ ] Step description"
- Group steps logically if it makes sense (Identity, Permit, Canton, Final)
- Keep it concise, no extra commentary
- The steps above are given in English; translate them into the output
  language rather than copying them
{_language_rule(language)}"""


def build_letter_prompt(
    employee_name, nationality, canton, permit, employer, risk, trace,
    workflow, language=DEFAULT_CORRESPONDENCE_LANGUAGE,
):
    """
    A formal letter to a cantonal migration office.

    The highest-stakes output the product generates: it is signed by the
    employer and filed with an authority. A letter in the wrong language
    is not a translation problem, it is a submission that gets returned.
    """

    return f"""
You are drafting a FORMAL OFFICIAL LETTER on behalf of an employer, to
be submitted to Swiss cantonal authorities, supporting a relocation /
permit case.

CASE DETAILS:
- Employee: {employee_name}
- Nationality: {nationality}
- Canton: {canton}
- Permit requested: {permit}
- Employer: {employer}
- Risk assessment: {risk} / 100
- Risk breakdown: {trace['breakdown']}
- Process steps already identified: {workflow}

Write a formal, professional letter in Swiss administrative style,
addressed generically to the cantonal migration office, requesting
support/processing of this case. Include a placeholder date and a
signature line. Do not invent specific facts not given above.

The case details above are given in English; render them in the output
language rather than quoting them.
{_language_rule(language)}"""


def build_document_classification_prompt(raw_text):

    return f"""
You are a Swiss immigration document classification assistant.

Below is text extracted from an uploaded document
(via OCR or native PDF text extraction).

Analyze it and respond with ONLY valid JSON.
Do not include markdown fences or additional explanations.

Return exactly this schema:

{{
  "document_type": one of [
      "Passport",
      "Employment Contract",
      "CV",
      "Visa",
      "Entry Visa",
      "Permit Application",
      "Commune Registration",
      "Residence Registration",
      "Other"
  ],

  "key_facts": {{
      "any_relevant_field_you_find": "value"
  }},

  "summary": "a 2-3 sentence factual summary of the document content"
}}

DOCUMENT TEXT:

\"\"\"
{raw_text[:6000]}
\"\"\"
"""


def build_recommendation_prompt(case, risk, trace, workflow, doc_analysis):

    return f"""
You are a senior Swiss relocation case manager.

CASE:
- Nationality: {case[2]}
- Canton: {case[3]}
- Permit: {case[4]}
- Business Mode: {case[5]}

RISK:
{trace['total']} / 100

RISK BREAKDOWN:
{trace['breakdown']}

WORKFLOW:
{workflow}

DOCUMENT ANALYSIS:

- Missing documents:
{doc_analysis.get('missing_documents')}

- Risk factors found in documents:
{doc_analysis.get('risk_factors')}

- Compliance score:
{doc_analysis.get('compliance_score')}


TASK:

Give ONE clear, prioritized recommendation for what the case manager
should do RIGHT NOW.

Be specific and operational.

Maximum length: 5 sentences.

Do not simply repeat the provided data.
Synthesize the information into a practical decision.
"""


def build_defect_detection_prompt(raw_text, document_type):

    return f"""
You are a document quality control assistant for Swiss immigration case files.

Below is text extracted from a document classified as: {document_type}

TEXT:
\"\"\"
{raw_text[:4000]}
\"\"\"

TASK:
List any signs of a DEFECTIVE or INCOMPLETE document (e.g., missing
signature line, missing date, truncated/cut-off text suggesting a missing
page, inconsistent or garbled text suggesting poor scan quality).

Respond with ONLY a JSON array of short strings (max 5 items).

If you see no issues, respond with an empty array: []

No markdown fences, no preamble.
"""


def build_additional_documents_prompt(case, existing_names, rule_based_missing):

    return f"""
You are a Swiss immigration document checklist assistant.

CASE:
- Nationality: {case[2]}
- Canton: {case[3]}
- Permit: {case[4]}
- Business Mode: {case[5]}

Documents already on file:
{existing_names}

Documents already flagged as missing by the standard rule checklist:
{rule_based_missing}

TASK:

Suggest up to 3 ADDITIONAL documents that might realistically be needed
for this specific case profile, beyond the standard checklist above.

Only suggest something genuinely specific to this profile.
Do not repeat the standard list.

If nothing additional seems needed, respond with an empty list.

Respond with ONLY a JSON array of strings (max 3 items).

No markdown fences, no preamble.

Example:
["Proof of prior Swiss residence"]
"""""
