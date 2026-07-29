"""
AI Agent orchestration package.

This package replaces what used to be a single large core/ai/agent.py
module. The only public symbol is run_agent (core.ai.agent.orchestrator)
- every existing import of `from core.ai.agent import run_agent` or
`from core.ai import agent; agent.run_agent(...)` continues to work
unchanged.

Internal layout, one concern per module:

  config.py          Shared constants (the Ollama model name).
  prompts.py          System prompts and LLM message construction.
  shared.py           Step/response bookkeeping used by every route.
  audit.py            Enterprise Audit Trail integration.
  tool_execution.py   ACTION route: CREATE_TASK / DOCUMENT_ACTION
                       (native tool-calling, executed exactly once).
  read_only.py         STATUS / CHECK_BLOCKERS (fully deterministic)
                       and ANALYZE (LLM consulted only for
                       recommended_next_steps).
  unimplemented.py     Operational intents that are recognized and
                       RBAC-gated but have no backing tool yet.
  orchestrator.py      run_agent itself: builds context, classifies
                       intent, runs the RBAC gate, and dispatches to
                       the modules above.

The LLM is never trusted to write the final user-facing sentence, is
never the source of an authoritative fact it could instead look up,
and is never trusted to describe an action beyond what a tool actually
confirmed - see orchestrator.py for the full pipeline description.
"""

from core.ai.agent.orchestrator import run_agent

__all__ = ["run_agent"]
