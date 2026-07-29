"""
Bookkeeping helpers shared by every dispatch route (read-only,
tool-execution, unimplemented-action, and the orchestrator itself).

Kept deliberately tiny and dependency-free (only core.ai.memory) so
every other submodule in this package can depend on it without risk
of a circular import.
"""

from core.ai import memory as conversation_memory


def record_step(steps_log: list, on_step, step: dict) -> None:
    steps_log.append(step)

    if on_step:
        on_step(step)


def finish(case_id: int, user_goal: str, answer: str, steps_log: list, context: dict) -> dict:
    conversation_memory.append_turn(case_id, user_goal, answer)
    return {"answer": answer, "steps": steps_log, "context": context}
