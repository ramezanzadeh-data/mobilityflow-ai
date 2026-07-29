"""
System prompts and LLM message construction.

These are the compliance rules and schema instructions given to the
model, plus the small helpers that assemble a message list from them.
Nothing here calls the LLM or executes anything - this module only
builds the input to core.ai.ollama_client.chat.
"""

from core.ai import memory as conversation_memory


# ==========================
# Shared compliance rules (apply to every intent)
# ==========================

BASE_SYSTEM_PROMPT = (
    "You are a Swiss Relocation AI Case Manager.\n\n"
    "Your responsibility is to analyze and assist relocation cases "
    "using only the verified case context provided by the system.\n\n"
    "STRICT RULES:\n"
    "1. Never query the database directly.\n"
    "2. Never invent information or assume missing data - use only the "
    "verified case context.\n"
    "3. Never modify workflow state directly. The Workflow Engine "
    "controls all transitions.\n"
    "4. Never bypass compliance rules or validation checks.\n"
    "5. Critical decisions require human approval.\n"
    "6. Do not infer legal or regulatory requirements beyond the "
    "provided case context.\n"
)

ACTION_SYSTEM_PROMPT = BASE_SYSTEM_PROMPT + (
    "\n7. Only call a tool when the user explicitly requests an "
    "operational action.\n"
    "8. Call at most one tool for this request.\n"
    "9. After a tool result is returned, do not add analysis, "
    "blockers, recommendations, or workflow discussion - the system "
    "will summarize the confirmed result on its own.\n"
)

# Schema instruction for the one remaining LLM-mediated reasoning
# intent. STATUS and CHECK_BLOCKERS used to have entries here too, but
# they are now fully deterministic (see core.ai.agent.read_only) and
# never call the LLM at all, so a schema prompt for them would be dead
# weight - and worse, a misleading artifact suggesting the model still
# produces their content.
ANALYZE_SCHEMA_INSTRUCTION = (
    "Return ONLY a JSON object with exactly this shape, nothing else:\n"
    "{\n"
    '  "recommended_next_steps": [string, ...]\n'
    "}\n"
    "List ONLY concrete, corrective remediation actions that directly "
    "address a blocker, missing document, or risk factor already "
    "present in the verified case context (e.g. \"Obtain the missing "
    "Commune Registration Form\"). Every step must be traceable to "
    "something already listed in the verified case context - never "
    "invent a document, requirement, or issue that is not there. "
    "NEVER suggest a future workflow state, and NEVER suggest "
    "advancing or transitioning the workflow itself; that decision "
    "belongs only to a human via the Workflow Engine. If the verified "
    "case context lists no blockers, missing documents, or risk "
    "factors, return an empty list - there is nothing to remediate."
)


def build_user_message(context_json: str, user_goal: str) -> dict:
    return {
        "role": "user",
        "content": (
            "VERIFIED CASE CONTEXT:\n"
            f"{context_json}\n\n"
            "USER REQUEST:\n"
            f"{user_goal}"
        ),
    }


def build_messages(system_prompt: str, case_id: int, context_json: str, user_goal: str) -> list:
    messages = [{"role": "system", "content": system_prompt}]

    history = conversation_memory.get_history(case_id)
    if history:
        messages.extend(history)

    messages.append(build_user_message(context_json, user_goal))

    return messages
