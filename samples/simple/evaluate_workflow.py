# Copyright (c) Microsoft. All rights reserved.

"""Evaluate a multi-agent workflow with per-agent breakdown.

Demonstrates workflow evaluation:
1. Build a simple two-agent workflow
2. Run evaluate_workflow() which runs the workflow and evaluates each agent
3. Inspect per-agent results in sub_results

Usage:
    python samples/evaluate_workflow.py
"""

import asyncio
from collections.abc import Sequence
from typing import Any, Mapping

from agent_framework import (
    Agent,
    BaseChatClient,
    ChatResponse,
    Content,
    LocalEvaluator,
    Message,
    WorkflowBuilder,
    evaluate_workflow,
    evaluator,
    keyword_check,
)


class MockChatClient(BaseChatClient):
    """A fake chat client that returns canned responses based on instructions."""

    async def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool,
        options: Mapping[str, Any], **kwargs: Any,
    ) -> ChatResponse:
        # Extract the system instruction to decide which agent is calling
        system_text = ""
        user_text = ""
        for m in messages:
            if m.role in ("system", "developer"):
                system_text += (m.text or "")
            elif m.role == "user":
                user_text += (m.text or "")

        if "plan" in system_text.lower():
            reply = (
                "Here is your weekend trip plan for Paris:\n"
                "- Day 1: Visit the Eiffel Tower and Louvre Museum\n"
                "- Day 2: Explore Montmartre and Seine River cruise\n"
                "- Hotel: Book a hotel near Champs-Élysées"
            )
        elif "execute" in system_text.lower():
            reply = (
                "Trip booked successfully:\n"
                "- Flight: Confirmed round-trip tickets\n"
                "- Hotel: Champs-Élysées Grand, 2 nights\n"
                "- Eiffel Tower tickets: Reserved for Day 1\n"
                "- Seine cruise: Booked for Day 2 evening"
            )
        else:
            reply = f"Processed: {user_text[:100]}"

        return ChatResponse(
            messages=Message(role="assistant", contents=[Content("text", text=reply)]),
        )


@evaluator
def is_nonempty(response: str) -> bool:
    """Check the agent produced a non-trivial response."""
    return len(response.strip()) > 5


async def main() -> None:
    # Build a simple planner -> executor workflow using a mock client
    client = MockChatClient()
    planner = Agent(client=client, name="planner", instructions="You plan trips. Output a bullet-point plan.")
    executor_agent = Agent(
        client=client, name="executor", instructions="You execute travel plans. Book the items listed."
    )

    workflow = WorkflowBuilder(start_executor=planner).add_edge(planner, executor_agent).build()

    # Evaluate with per-agent breakdown
    local = LocalEvaluator(is_nonempty, keyword_check("plan", "trip"))

    results = await evaluate_workflow(
        workflow=workflow,
        queries=["Plan a weekend trip to Paris"],
        evaluators=local,
    )

    for r in results:
        print(f"{r.provider}: {r.passed}/{r.total} passed (overall)")
        for agent_name, sub in r.sub_results.items():
            error = f" (error: {sub.error})" if sub.error else ""
            print(f"  {agent_name}: {sub.passed}/{sub.total} {error}")


if __name__ == "__main__":
    asyncio.run(main())