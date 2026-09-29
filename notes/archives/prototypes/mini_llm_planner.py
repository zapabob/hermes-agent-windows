#!/usr/bin/env python3
"""
mini_llm_planner.py

A minimal planning client that implements a two-stage "generate → critique → revise" loop.
Designed to be a simple toy/example that you can later wire to a real LLM.

Usage:
    python mini_llm_planner.py "Your task or goal here"

The script will:
1. Generate an initial plan.
2. Critique it.
3. If the critique is non-trivial, revise the plan.
4. Print the final plan.

All LLM interactions are currently stubs — replace the MiniLLM class methods
with real API calls as needed.
"""

import sys
import textwrap
from typing import List, Optional


# ---------------------------------------------------------------------------
# Stub LLM interface
# ---------------------------------------------------------------------------

class MiniLLM:
    """Placeholder for a real LLM client. Replace methods with actual calls."""

    def generate_plan(self, task: str) -> str:
        """Return a draft plan for the given task."""
        # TODO: replace with real LLM call, e.g. OpenAI, Anthropic, local model, etc.
        return textwrap.dedent(f"""
            Draft plan for: {task}

            1. Understand the requirements.
            2. Break the task into subtasks.
            3. Execute each subtask in order.
            4. Review the overall result.
        """).strip()

    def critique_plan(self, plan: str) -> str:
        """Return a critique of the provided plan."""
        # TODO: replace with real LLM call.
        return textwrap.dedent(f"""
            Critique of the plan:

            - The plan is too generic.
            - Add concrete success criteria.
            - Consider possible failure modes.
        """).strip()

    def revise_plan(self, plan: str, critique: str) -> str:
        """Revise the plan based on the critique."""
        # TODO: replace with real LLM call.
        return textwrap.dedent(f"""
            Revised plan based on critique:

            {plan}

            Updates:
            - Added success criteria.
            - Listed potential failure modes and mitigations.
        """).strip()


# ---------------------------------------------------------------------------
# Planning loop
# ---------------------------------------------------------------------------

def run_planning_loop(llm: MiniLLM, task: str, max_iterations: int = 2) -> str:
    """
    Execute a generate → critique → revise loop.

    Args:
        llm: LLM client with generate_plan, critique_plan, revise_plan.
        task: The task or goal to plan for.
        max_iterations: How many times to revise based on critique.

    Returns:
        The final plan string.
    """
    plan = llm.generate_plan(task)
    print("=" * 60)
    print("INITIAL PLAN")
    print("=" * 60)
    print(plan)
    print()

    for i in range(1, max_iterations + 1):
        critique = llm.critique_plan(plan)
        print("=" * 60)
        print(f"CRITIQUE (iteration {i})")
        print("=" * 60)
        print(critique)
        print()

        # Simple heuristic: if critique looks empty or trivial, stop.
        if not critique.strip() or critique.strip().lower() in ("ok", "good", "no issues"):
            print("Critique indicates no changes needed. Stopping.")
            break

        plan = llm.revise_plan(plan, critique)
        print("=" * 60)
        print(f"REVISED PLAN (iteration {i})")
        print("=" * 60)
        print(plan)
        print()

    return plan


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python mini_llm_planner.py <task>")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    llm = MiniLLM()
    final_plan = run_planning_loop(llm, task)
    print("=" * 60)
    print("FINAL PLAN")
    print("=" * 60)
    print(final_plan)


if __name__ == "__main__":
    main()
