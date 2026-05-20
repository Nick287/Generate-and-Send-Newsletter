# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executors for local demo.

import asyncio
import os
from typing import Any

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    handler,
)
from pydantic import BaseModel
from typing_extensions import Never

"""
Sample: Conditional routing with structured outputs

What this sample is:
- A minimal decision workflow that classifies an inbound email as spam or not spam, then routes to the
appropriate handler.

Purpose:
- Show how to attach boolean edge conditions that inspect an AgentExecutorResponse.
- Demonstrate using Pydantic models as response_format so the agent returns JSON we can validate and parse.
- Illustrate how to transform one agent's structured result into a new AgentExecutorRequest for a downstream agent.

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- You understand the basics of WorkflowBuilder, executors, and events in this framework.
- You know the concept of edge conditions and how they gate routes using a predicate function.
- Azure OpenAI access is configured for FoundryChatClient. You should be logged in with Azure CLI (AzureCliCredential)
and have the Foundry V2 Project environment variables set as documented in the getting started chat client README.
- The sample email resource file exists at workflow/resources/email.txt.

High level flow:
1) spam_detection_agent reads an email and returns DetectionResult.
2) If not spam, we transform the detection output into a user message for email_assistant_agent, then finish by
yielding the drafted reply as workflow output.
3) If spam, we short circuit to a spam handler that yields a spam notice as workflow output.

Output:
- The final workflow output is printed to stdout, either with a drafted reply or a spam notice.

Notes:
- Conditions read the agent response text and validate it into DetectionResult for robust routing.
- Executors are small and single purpose to keep control flow easy to follow.
- The workflow completes when it becomes idle, not via explicit completion events.
"""


class DetectionResult(BaseModel):
    """Represents the result of spam detection."""

    # is_spam drives the routing decision taken by edge conditions
    is_spam: bool
    # Human readable rationale from the detector
    reason: str
    # The agent must include the original email so downstream agents can operate without reloading content
    email_content: str


class EmailResponse(BaseModel):
    """Represents the response from the email assistant."""

    # The drafted reply that a user could copy or send
    response: str


def get_condition(expected_result: bool):
    """Create a condition callable that routes based on DetectionResult.is_spam."""

    def condition(message: Any) -> bool:
        if not isinstance(message, DetectionResult):
            return True
        return message.is_spam == expected_result

    return condition


class SpamDetector(Executor):
    """Stub spam detector — classifies email locally without calling an LLM."""

    SPAM_KEYWORDS = ["winner", "prize", "click here", "free", "act now", "urgent offer"]

    @handler
    async def detect(self, email_text: str, ctx: WorkflowContext[DetectionResult]) -> None:
        lower = email_text.lower()
        is_spam = any(kw in lower for kw in self.SPAM_KEYWORDS)
        reason = "Contains spam keywords" if is_spam else "Looks like a legitimate email"
        result = DetectionResult(is_spam=is_spam, reason=reason, email_content=email_text)
        await ctx.send_message(result)


class EmailAssistant(Executor):
    """Stub email assistant — drafts a simple reply without calling an LLM."""

    @handler
    async def draft_reply(self, detection: DetectionResult, ctx: WorkflowContext[Never, str]) -> None:
        reply = (
            f"Thank you for your email. I have reviewed the content and will follow up shortly.\n\n"
            f"Original subject extracted from:\n{detection.email_content[:80]}..."
        )
        await ctx.yield_output(f"Email sent:\n{reply}")


class SpamHandler(Executor):
    """Handles emails classified as spam."""

    @handler
    async def handle(self, detection: DetectionResult, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(f"Email marked as spam: {detection.reason}")


# ── Sample emails ────────────────────────────────────────────────
LEGIT_EMAIL = """\
Subject: Team Meeting Follow-up - Action Items

Hi Sarah,

I wanted to follow up on our team meeting this morning and share the action items we discussed:

1. Update the project timeline by Friday
2. Schedule client presentation for next week
3. Review the budget allocation for Q4

Best regards,
Alex Johnson
"""

SPAM_EMAIL = """\
Subject: You are the WINNER of a FREE prize!

Click here to claim your reward! Act now — this urgent offer expires today!
"""


async def main() -> None:
    """Build and run the conditional-routing workflow (no Foundry dependency)."""

    spam_detector = SpamDetector(id="spam_detector")
    email_assistant = EmailAssistant(id="email_assistant")
    spam_handler = SpamHandler(id="spam_handler")

    workflow = (
        WorkflowBuilder(start_executor=spam_detector)
        # Not-spam path: detector → email assistant
        .add_edge(spam_detector, email_assistant, condition=get_condition(False))
        # Spam path: detector → spam handler
        .add_edge(spam_detector, spam_handler, condition=get_condition(True))
        .build()
    )

    # Visualize
    viz = WorkflowViz(workflow)
    print("Mermaid:\n=======")
    print(viz.to_mermaid())
    print("=======")
    print("\nDiGraph:\n=======")
    print(viz.to_digraph(include_internal_executors=True))
    print("=======")

    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "edge_condition_workflow.svg"))
    print(f"\nSVG exported to: {svg_file}")

    # Run with a legitimate email
    print("\n--- Legitimate email ---")
    events = await workflow.run(LEGIT_EMAIL)
    for out in events.get_outputs():
        print(f"Workflow output: {out}")

    # Run with a spam email
    print("\n--- Spam email ---")
    events = await workflow.run(SPAM_EMAIL)
    for out in events.get_outputs():
        print(f"Workflow output: {out}")


if __name__ == "__main__":
    asyncio.run(main())
