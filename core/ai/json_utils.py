"""
Small utility for pulling a single JSON object out of LLM free text.

Local models often wrap JSON in prose or markdown code fences even when
told to return "only JSON". This scans for the first balanced {...} block
instead of relying on a single greedy regex, so nested objects/arrays in
the payload (e.g. lists inside the JSON) don't break extraction.
"""

import json
from typing import Optional


def extract_json_object(text: str) -> Optional[dict]:
    """
    Return the first balanced top-level JSON object found in `text`,
    parsed into a dict, or None if no valid JSON object is found.
    """

    if not text:
        return None

    start = text.find("{")

    while start != -1:
        depth = 0
        in_string = False
        escape = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1

                if depth == 0:
                    candidate = text[start:index + 1]

                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

        start = text.find("{", start + 1)

    return None
