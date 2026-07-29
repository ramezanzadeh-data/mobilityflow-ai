"""
Manual diagnostic: run one goal through the AI agent end to end and print
the answer plus the executed steps.

This is a developer tool, not a test. It performs live database and LLM
I/O, so it must not live under tests/ - pytest imports every
tests/test_*.py at collection time, and a module that does real I/O at
import can abort collection of the entire suite when the infrastructure
is unreachable. The automated coverage for the agent pipeline lives in
tests/test_agent_pipeline.py, tests/test_tool_policy_rbac.py and
tests/test_run_agent_auth_gate.py, all of which stub the LLM.

Replaces the former tests/test_agent.py (read-only route) and
tests/test_action_agent.py (operational route); both are covered by the
--role option, since the only difference between them was whether an
authenticated caller was supplied.

Usage:

    # Read-only route - no caller identity required.
    python -m scripts.diagnose_agent "Analyze this relocation case."

    # Operational route - MANAGER holds both ai:use and tasks:edit.
    python -m scripts.diagnose_agent \
        "Create a task to collect the missing Commune Registration Form." \
        --role MANAGER
"""

import argparse
import sys

# Must run before any module that reads configuration at import time -
# see bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

from core.ai.agent import run_agent  # noqa: E402  (deliberate - see above)


DEFAULT_GOAL = "Analyze this relocation case."
DEFAULT_CASE_ID = 1


def _parse_args(argv=None):

    parser = argparse.ArgumentParser(
        description="Run one goal through the AI agent and print the result.",
    )

    parser.add_argument(
        "goal",
        nargs="?",
        default=DEFAULT_GOAL,
        help=f"Goal to send to the agent (default: {DEFAULT_GOAL!r})",
    )

    parser.add_argument(
        "--case-id",
        type=int,
        default=DEFAULT_CASE_ID,
        help=f"Case id the goal applies to (default: {DEFAULT_CASE_ID})",
    )

    parser.add_argument(
        "--role",
        default=None,
        choices=["ADMIN", "MANAGER", "STAFF", "VIEWER"],
        help="Role of the simulated caller. Omit to call anonymously, "
             "which is the correct way to exercise the read-only route "
             "and to confirm that operational intents are denied.",
    )

    return parser.parse_args(argv)


def main(argv=None) -> int:

    args = _parse_args(argv)

    # None (rather than an empty dict) is deliberate: run_agent treats a
    # missing caller as unauthenticated and denies every operational
    # intent, which is exactly what an anonymous run should demonstrate.
    current_user = {"role": args.role} if args.role else None

    result = run_agent(
        user_goal=args.goal,
        case_id=args.case_id,
        current_user=current_user,
    )

    print("ANSWER:")
    print(result["answer"])

    print("\nSTEPS:")
    for step in result.get("steps", []):
        print(f"  - {step}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
