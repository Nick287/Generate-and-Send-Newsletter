# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executors for local demo.

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from agent_framework import (
    Case,
    Default,
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    handler,
)
from pydantic import BaseModel, Field
from typing_extensions import Never

"""
Sample: Switch-Case Edge Group with an explicit Uncertain branch.

The workflow stores a single email in workflow state, asks a spam detection agent for a three way decision,
then routes with a switch-case group: NotSpam to the drafting assistant, Spam to a spam handler, and
Default to an Uncertain handler.

Purpose:
Demonstrate deterministic one of N routing with switch-case edges. Show how to:
- Persist input once in workflow state, then pass around a small typed pointer that carries the email id.
- Validate agent JSON with Pydantic models for robust parsing.
- Keep executor responsibilities narrow. Transform model output to a typed DetectionResult, then route based
on that type.
- Use ctx.yield_output() to provide workflow results - the workflow completes when idle with no pending work.

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- Familiarity with WorkflowBuilder, executors, edges, and events.
- Understanding of switch-case edge groups and how Case and Default are evaluated in order.
- Working Azure OpenAI configuration for FoundryChatClient, with Azure CLI login and required environment variables.
- Access to workflow/resources/ambiguous_email.txt, or accept the inline fallback string.
"""


EMAIL_STATE_PREFIX = "email:"
CURRENT_EMAIL_ID_KEY = "current_email_id"


class DetectionResultAgent(BaseModel):
    """Structured output returned by the spam detection agent."""

    # The agent classifies the email and provides a rationale.
    spam_decision: Literal["NotSpam", "Spam", "Uncertain"]
    reason: str


class EmailResponse(BaseModel):
    """Structured output returned by the email assistant agent."""

    # The drafted professional reply.
    response: str


@dataclass
class DetectionResult:
    # Internal typed payload used for routing and downstream handling.
    spam_decision: str
    reason: str
    email_id: str


@dataclass
class Email:
    # In memory record of the email content stored in workflow state.
    email_id: str
    email_content: str


def get_case(expected_decision: str):
    """Factory that returns a predicate matching a specific spam_decision value."""

    def condition(message: Any) -> bool:
        return isinstance(message, DetectionResult) and message.spam_decision == expected_decision

    return condition


SPAM_KEYWORDS = ["winner", "prize", "click here", "free", "act now", "urgent offer"]
UNCERTAIN_KEYWORDS = ["no pressure", "might be interested", "limited time", "expires soon"]


class EmailTestRequest(BaseModel):
    """Input configuration shown as a form in DevUI."""

    email_type: Literal["legitimate", "spam", "ambiguous"] = Field(
        description="Select which sample email to classify",
        default="legitimate",
    )


class StoreEmail(Executor):
    """Resolves EmailTestRequest to email text, stores in state, and forwards."""

    @handler
    async def run(self, request: EmailTestRequest, ctx: WorkflowContext[str]) -> None:
        email_map = {
            "legitimate": LEGIT_EMAIL,
            "spam": SPAM_EMAIL,
            "ambiguous": AMBIGUOUS_EMAIL,
        }
        email_text = email_map[request.email_type]
        new_email = Email(email_id=str(uuid4()), email_content=email_text)
        ctx.set_state(f"{EMAIL_STATE_PREFIX}{new_email.email_id}", new_email)
        ctx.set_state(CURRENT_EMAIL_ID_KEY, new_email.email_id)
        await ctx.send_message(email_text)


class DetectSpam(Executor):
    """Stub spam detector — keyword-based classification."""

    @handler
    async def run(self, email_text: str, ctx: WorkflowContext[DetectionResult]) -> None:
        await asyncio.sleep(1.5)  # Simulate detection processing
        email_id: str = ctx.get_state(CURRENT_EMAIL_ID_KEY)
        lower = email_text.lower()
        if any(kw in lower for kw in SPAM_KEYWORDS):
            decision, reason = "Spam", "Contains spam keywords"
        elif any(kw in lower for kw in UNCERTAIN_KEYWORDS):
            decision, reason = "Uncertain", "Ambiguous promotional language"
        else:
            decision, reason = "NotSpam", "Looks like a legitimate email"
        await ctx.send_message(DetectionResult(spam_decision=decision, reason=reason, email_id=email_id))


class DraftReply(Executor):
    """Stub email assistant — drafts a simple reply."""

    @handler
    async def run(self, detection: DetectionResult, ctx: WorkflowContext[Never, str]) -> None:
        email: Email = ctx.get_state(f"{EMAIL_STATE_PREFIX}{detection.email_id}")
        reply = f"Thank you for your email. I will follow up shortly.\n(re: {email.email_content[:60]}...)"
        await ctx.yield_output(f"Email sent: {reply}")


class HandleSpam(Executor):
    @handler
    async def run(self, detection: DetectionResult, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(f"Email marked as spam: {detection.reason}")


class HandleUncertain(Executor):
    @handler
    async def run(self, detection: DetectionResult, ctx: WorkflowContext[Never, str]) -> None:
        email: Email | None = ctx.get_state(f"{EMAIL_STATE_PREFIX}{detection.email_id}")
        await ctx.yield_output(
            f"Email marked as uncertain: {detection.reason}. Email content: {getattr(email, 'email_content', '')}"
        )


# ── Sample emails ────────────────────────────────────────────────
LEGIT_EMAIL = """\
Hi Sarah, here are the action items from our team meeting. Please review by Friday.
"""

SPAM_EMAIL = """\
You are the WINNER of a FREE prize! Click here to claim your reward! Act now!
"""

AMBIGUOUS_EMAIL = """\
Hey there, I noticed you might be interested in our latest offer—no pressure, but it expires soon.
Let me know if you'd like more details.
"""


async def main():
    """Main function to run the workflow."""
    store_email = StoreEmail(id="store_email")
    detect_spam = DetectSpam(id="detect_spam")
    draft_reply = DraftReply(id="draft_reply")
    handle_spam = HandleSpam(id="handle_spam")
    handle_uncertain = HandleUncertain(id="handle_uncertain")

    workflow = (
        WorkflowBuilder(start_executor=store_email)
        .add_edge(store_email, detect_spam)
        .add_switch_case_edge_group(
            detect_spam,
            [
                Case(condition=get_case("NotSpam"), target=draft_reply),
                Case(condition=get_case("Spam"), target=handle_spam),
                Default(target=handle_uncertain),
            ],
        )
        .build()
    )

    # ── Visualization ─────────────────────────────────────────────
    viz = WorkflowViz(workflow)
    print("Mermaid:\n=======")
    print(viz.to_mermaid())
    print("=======")
    print("\nDiGraph:\n=======")
    print(viz.to_digraph(include_internal_executors=True))
    print("=======")

    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "03_switch_case_workflow.svg"))
    print(f"\nSVG exported to: {svg_file}")

    # ── Run with different email types ────────────────────────────
    for label, email_type in [
        ("Legitimate", "legitimate"),
        ("Spam", "spam"),
        ("Ambiguous (Default/Uncertain)", "ambiguous"),
    ]:
        print(f"\n--- {label} ---")
        events = await workflow.run(EmailTestRequest(email_type=email_type))
        for output in events.get_outputs():
            print(f"  Workflow output: {output}")


def devui():
    """Launch the workflow in DevUI — select email type from a dropdown."""
    from agent_framework.devui import serve

    store_email = StoreEmail(id="store_email")
    detect_spam = DetectSpam(id="detect_spam")
    draft_reply = DraftReply(id="draft_reply")
    handle_spam = HandleSpam(id="handle_spam")
    handle_uncertain = HandleUncertain(id="handle_uncertain")

    workflow = (
        WorkflowBuilder(start_executor=store_email)
        .add_edge(store_email, detect_spam)
        .add_switch_case_edge_group(
            detect_spam,
            [
                Case(condition=get_case("NotSpam"), target=draft_reply),
                Case(condition=get_case("Spam"), target=handle_spam),
                Default(target=handle_uncertain),
            ],
        )
        .build()
    )

    print("=" * 60)
    print("  Switch-Case Email Classification — DevUI")
    print("  http://localhost:8090")
    print("=" * 60)

    serve(entities=[workflow], port=8090, auto_open=True)


if __name__ == "__main__":
    if "--devui" in sys.argv:
        devui()
    else:
        asyncio.run(main())
