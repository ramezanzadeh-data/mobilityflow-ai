
import json

from core.ai.engine import ask_ai
from core.ai.prompts import (
    build_document_classification_prompt,
    build_recommendation_prompt,
)


def _strip_markdown_fences(text: str) -> str:

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()

    return cleaned


def classify_and_summarize_document(raw_text: str) -> dict:

    if not raw_text or not raw_text.strip():
        return {
            "document_type": "Unknown",
            "key_facts": {},
            "summary": "No text was extracted from the document (empty document or OCR failure)."
        }

    prompt = build_document_classification_prompt(raw_text)

    raw_response = ask_ai(prompt)

    try:
        cleaned = _strip_markdown_fences(raw_response)

        parsed = json.loads(cleaned)


        parsed.setdefault("document_type", "Other")
        parsed.setdefault("key_facts", {})
        parsed.setdefault("summary", "")

        return parsed

    except (json.JSONDecodeError, AttributeError, TypeError):

        return {
            "document_type": "Other",
            "key_facts": {},
            "summary": raw_response[:500] if raw_response else ""
        }


def generate_recommendation(case, risk, trace, workflow, doc_analysis):

    prompt = build_recommendation_prompt(case, risk, trace, workflow, doc_analysis)

    return ask_ai(prompt)