"""
Intent Router.

Classifies user requests before any LLM/tool execution. This module is
the single gate that decides whether a request is read-only reasoning
(ANALYZE / STATUS / CHECK_BLOCKERS) or an operational action that must
go through the ACTION route (core.ai.tool_policy + core.ai.agent's
deterministic/tool-calling handlers).

ENTERPRISE GUARANTEE
---------------------
Every request that names an operational verb (assign, delete, approve,
reject, close, archive, update, edit, submit, advance, and their
direct synonyms) is classified into one of the operational intents
below - NEVER into ANALYZE or STATUS. This is enforced in two layers:

  1. Specific keyword/phrase tables (one per operational intent) match
     the common, explicit phrasings first, so each verb gets its own
     precisely-typed intent (and therefore its own RBAC permission -
     see core.ai.tool_policy).
  2. A generic trailing safety net (`_LEADING_ACTION_VERB_RE`) catches
     any remaining leading-imperative phrasing of one of these verbs
     that the specific tables did not match, and routes it to
     Intent.GENERIC_ACTION rather than letting it fall through to
     ANALYZE/STATUS. GENERIC_ACTION is still fully operational: it is
     RBAC-gated and, because no tool is implemented for it yet, is
     answered exclusively by the Action Policy layer (see
     core.ai.tool_policy.resolve_tool_for_intent and
     core.ai.agent.unimplemented.run_unimplemented_action) - never by the
     analytical/LLM-reasoning path.

This is a keyword/pattern-based classifier, not a full NLU model. It
cannot make a mathematically absolute guarantee against every possible
adversarial phrasing of natural language, but every verb explicitly
named in the product requirement is covered by an anchored, word-
boundary-safe match, both as a specific phrase and as a leading verb,
so realistic operational phrasing cannot silently fall through to a
read-only route.

Supported intents:

- ANALYZE
    Explanation, recommendation, risk analysis. Read-only.

- STATUS
    Case status and workflow queries. Read-only.

- CHECK_BLOCKERS
    Find missing documents and blockers. Read-only.

- CREATE_TASK
    Create follow-up tasks. Operational (tool-calling).

- ASSIGN_TASK
    Assign/reassign a task or case to a person. Operational (no tool
    implemented yet - see core.ai.tool_policy).

- ADVANCE_WORKFLOW / SUBMIT
    Move case to next workflow stage. Operational (deterministic).

- APPROVE_CASE
    Approve a relocation case. Operational (deterministic).

- REJECT_CASE
    Reject a relocation case. Operational (no tool implemented yet).

- DELETE_CASE
    Delete a relocation case. Operational (no tool implemented yet).

- CLOSE_CASE
    Close a relocation case. Operational (no tool implemented yet).

- ARCHIVE_CASE
    Archive a relocation case. Operational (no tool implemented yet).

- DOCUMENT_ACTION
    Upload/update/replace document actions. Operational (tool-calling).

- GENERIC_ACTION
    Any other operational verb (edit/update/etc.) recognized by the
    safety-net pattern but not covered by a more specific intent above.
    Operational (no tool implemented yet).

- ACTION
    Not returned by classify_intent. Internal marker used only by
    core.ai.schemas / core.ai.response_formatter to select the
    ActionPayload/_format_action pairing shared by every operational
    intent once it has produced (or been denied) a real tool result.
"""

import re
from enum import Enum


class Intent(str, Enum):

    ANALYZE = "analyze"

    STATUS = "status"

    CHECK_BLOCKERS = "check_blockers"

    CREATE_TASK = "create_task"

    ASSIGN_TASK = "assign_task"

    ADVANCE_WORKFLOW = "advance_workflow"

    APPROVE_CASE = "approve_case"

    REJECT_CASE = "reject_case"

    DELETE_CASE = "delete_case"

    CLOSE_CASE = "close_case"

    ARCHIVE_CASE = "archive_case"

    DOCUMENT_ACTION = "document_action"

    GENERIC_ACTION = "generic_action"

    # Internal formatter/payload marker only - never returned by
    # classify_intent(). See core.ai.schemas.ActionPayload and
    # core.ai.response_formatter._format_action.
    ACTION = "action"


# ==========================================================
# Matching helpers
# ==========================================================
#
# Word-boundary-safe matching. Plain substring matching (the previous
# implementation) has a real correctness bug: "close" as a substring
# would match inside "disclose", "update" would not accidentally match
# other words but the risk is general and grows with every new short
# keyword added below, so every keyword/phrase in this module is
# matched with \b...\b regardless of length.

def _has_phrase(goal: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", goal) is not None


def _matches_any(goal: str, phrases) -> bool:
    return any(_has_phrase(goal, phrase) for phrase in phrases)


_APPROVE_KEYWORDS = (
    "approve",
    "approval",
    "approve case",
    "approve this case",
    "approve relocation",
    "approve relocation case",
    "accept case",
    "accept this case",
    "confirm approval",
    "final approval",
)


_REJECT_KEYWORDS = (
    "reject",
    "rejection",
    "reject case",
    "reject this case",
    "deny",
    "deny case",
    "deny this case",
    "decline",
    "decline case",
    "decline this case",
    "turn down",
    "disapprove",
)


_DELETE_KEYWORDS = (
    "delete",
    "delete case",
    "delete this case",
    "erase case",
    "erase this case",
    "remove case",
    "remove this case",
    "permanently delete",
)


_CLOSE_KEYWORDS = (
    "close case",
    "close this case",
    "mark as closed",
    "mark case as closed",
    "close the case",
    "close out",
)


_ARCHIVE_KEYWORDS = (
    "archive",
    "archive case",
    "archive this case",
    "move to archive",
    "send to archive",
)


_ADVANCE_KEYWORDS = (
    "advance",
    "submit",
    "move forward",
    "next stage",
    "next step",
    "advance workflow",
    "transition",
    "change workflow",
)


_ASSIGN_KEYWORDS = (
    "assign",
    "assign to",
    "assign this case",
    "assign this task",
    "assign case to",
    "assign task to",
    "reassign",
    "hand off",
    "hand over",
)


_TASK_KEYWORDS = (
    "create task",
    "add task",
    "make task",
    "follow up",
    "follow-up",
    "reminder",
    "create a task",
    "create follow-up task",
    "task for",
)


_DOCUMENT_ACTION_VERBS = (
    "upload",
    "update",
    "edit",
    "modify",
    "replace",
    "remove",
    "receive",
)


def _is_document_action(goal: str) -> bool:
    """
    True when the request names a document-mutation verb together with
    the word "document"/"documents" anywhere in the sentence - not
    only as a rigid adjacent two-word phrase. Fixed adjacency (the
    original "upload document" style phrase table) misses realistic
    phrasing such as "upload the missing document", where the verb and
    the noun are not next to each other; without this fix, that
    request would instead match the unrelated CHECK_BLOCKERS phrase
    "missing document" and be silently downgraded to a read-only
    intent even though it plainly asks for a document to be uploaded.
    """

    if not re.search(r"\bdocuments?\b", goal):
        return False

    return any(
        re.search(rf"\b{re.escape(verb)}\b", goal)
        for verb in _DOCUMENT_ACTION_VERBS
    )


# NOTE: there is deliberately no anywhere-in-sentence keyword table for
# bare "update"/"edit"/"modify" here. Unlike "approve", "delete", or
# "archive", these words are just as commonly a noun in a read-only
# request ("give me an update on this case") as an imperative verb
# ("update the case details") - an anywhere-match table would
# misclassify the former as operational. Genuine imperative usage is
# instead caught by the anchored `_LEADING_ACTION_VERB_RE` safety net
# below, which only fires when the request actually starts with the
# verb (optionally after "please"/"kindly"/"can you"/"could you").


_BLOCKER_KEYWORDS = (
    "blocker",
    "blocked",
    "blocking",
    "what is missing",
)


def _is_missing_documents_query(goal: str) -> bool:
    """
    True when the request asks about missing documents, regardless of
    word order. The original fixed phrases ("missing document(s)")
    only matched when "missing" came immediately before "document(s)"
    - a request like "What documents are missing?" (the noun before
    the adjective) has exactly the same meaning but does not match a
    rigid adjacent phrase, and was silently falling through to
    ANALYZE. Same fix pattern as _is_document_action above: check for
    both words anywhere in the sentence instead of requiring adjacency.
    """

    return bool(
        re.search(r"\bmissing\b", goal) and re.search(r"\bdocuments?\b", goal)
    )


_STATUS_KEYWORDS = (
    "status",
    "current state",
    "workflow state",
    "where is",
    "where are we",
    "state of",
)


# ==========================================================
# Safety net: guarantees no operational verb silently falls through to
# ANALYZE/STATUS just because it wasn't phrased like one of the exact
# entries above (e.g. "Please delete case 12 now." or "Edit the permit
# type."). Anchored to the start of the (optionally "please"/"kindly"
# prefixed) request, since operational commands are characteristically
# imperative - this keeps the net from firing on analytical phrasing
# like "give me an update on this case", which does not start with the
# verb itself.
# ==========================================================

_LEADING_ACTION_VERB_RE = re.compile(
    r"^(please\s+|kindly\s+|can you\s+|could you\s+)?"
    r"(assign|reassign|delete|erase|remove|approve|accept|reject|deny|"
    r"decline|close|archive|update|edit|modify|submit|advance|revoke|"
    r"cancel|terminate|finalize|confirm)\b"
)


def classify_intent(user_goal: str) -> Intent:
    """
    Classify a raw user request into an Intent.

    Ordering is deliberate: more specific operational phrasings are
    checked before more generic ones (e.g. DOCUMENT_ACTION's "update
    document" is checked before the generic "update" fallback), and
    every operational check runs before the read-only CHECK_BLOCKERS /
    STATUS checks. ANALYZE is the last-resort default, reached only
    when nothing - including the trailing safety net - matched an
    operational or other read-only pattern.
    """

    goal = (user_goal or "").lower().strip()

    if not goal:
        return Intent.ANALYZE

    # ---- Operational intents (highest priority, most specific first) ----

    if _matches_any(goal, _APPROVE_KEYWORDS):
        return Intent.APPROVE_CASE

    if _matches_any(goal, _REJECT_KEYWORDS):
        return Intent.REJECT_CASE

    if _matches_any(goal, _DELETE_KEYWORDS):
        return Intent.DELETE_CASE

    if _matches_any(goal, _CLOSE_KEYWORDS):
        return Intent.CLOSE_CASE

    if _matches_any(goal, _ARCHIVE_KEYWORDS):
        return Intent.ARCHIVE_CASE

    if _matches_any(goal, _ADVANCE_KEYWORDS):
        return Intent.ADVANCE_WORKFLOW

    if _matches_any(goal, _ASSIGN_KEYWORDS):
        return Intent.ASSIGN_TASK

    if _matches_any(goal, _TASK_KEYWORDS):
        return Intent.CREATE_TASK

    if _is_document_action(goal):
        return Intent.DOCUMENT_ACTION

    # ---- Read-only intents ----

    if _matches_any(goal, _BLOCKER_KEYWORDS) or _is_missing_documents_query(goal):
        return Intent.CHECK_BLOCKERS

    if _matches_any(goal, _STATUS_KEYWORDS):
        return Intent.STATUS

    # ---- Safety net: catch any remaining operational imperative that ----
    # none of the specific tables above matched, so it is NEVER
    # misclassified as ANALYZE/STATUS.
    if _LEADING_ACTION_VERB_RE.match(goal):
        return Intent.GENERIC_ACTION

    return Intent.ANALYZE


# Every intent that represents an operational action and therefore
# must never be reachable without going through the RBAC gate in
# core.ai.tool_policy.check_operational_permission. Kept here (next to
# the classifier that produces these values) as the canonical list;
# core.ai.tool_policy imports it rather than re-declaring its own copy,
# so the two modules cannot drift out of sync.
OPERATIONAL_INTENTS = frozenset(
    {
        Intent.CREATE_TASK,
        Intent.ASSIGN_TASK,
        Intent.ADVANCE_WORKFLOW,
        Intent.APPROVE_CASE,
        Intent.REJECT_CASE,
        Intent.DELETE_CASE,
        Intent.CLOSE_CASE,
        Intent.ARCHIVE_CASE,
        Intent.DOCUMENT_ACTION,
        Intent.GENERIC_ACTION,
    }
)
