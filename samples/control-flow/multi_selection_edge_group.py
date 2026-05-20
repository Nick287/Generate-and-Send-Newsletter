# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executors for local demo.

"""Step 06b — Multi-Selection Edge Group sample."""

import asyncio
import os
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowEvent,
    WorkflowViz,
    handler,
)
from pydantic import BaseModel
from typing_extensions import Never

"""
Sample: Multi-Selection Edge Group for email triage and response.

The workflow stores an email,
classifies it as NotSpam, Spam, or Uncertain, and then routes to one or more branches.
Non-spam emails are drafted into replies, long ones are also summarized, spam is blocked, and uncertain cases are
flagged. Each path ends with simulated database persistence. The workflow completes when it becomes idle.

Purpose:
Demonstrate how to use a multi-selection edge group to fan out from one executor to multiple possible targets.
Show how to:
- Implement a selection function that chooses one or more downstream branches based on analysis.
- Share workflow state across branches so different executors can read the same email content.
- Validate agent outputs with Pydantic models for robust structured data exchange.
- Merge results from multiple branches (e.g., a summary) back into a typed state.
- Apply conditional persistence logic (short vs long emails).

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- Familiarity with WorkflowBuilder, executors, edges, and events.
- Understanding of multi-selection edge groups and how their selection function maps to target ids.
- Experience with workflow state for persisting and reusing objects.
"""


EMAIL_STATE_PREFIX = "email:"
CURRENT_EMAIL_ID_KEY = "current_email_id"
LONG_EMAIL_THRESHOLD = 100


class AnalysisResultAgent(BaseModel):
    spam_decision: Literal["NotSpam", "Spam", "Uncertain"]
    reason: str


class EmailResponse(BaseModel):
    response: str


class EmailSummaryModel(BaseModel):
    summary: str


@dataclass
class Email:
    email_id: str
    email_content: str


@dataclass
class AnalysisResult:
    spam_decision: str
    reason: str
    email_length: int
    email_summary: str
    email_id: str


class DatabaseEvent(WorkflowEvent): ...


SPAM_KEYWORDS = ["winner", "prize", "click here", "free", "act now", "urgent offer"]
UNCERTAIN_KEYWORDS = ["unsubscribe", "promotion", "limited time"]


class StoreEmail(Executor):
    """Stores email in workflow state and forwards the text."""

    @handler
    async def run(self, email_text: str, ctx: WorkflowContext[str]) -> None:
        new_email = Email(email_id=str(uuid4()), email_content=email_text)
        ctx.set_state(f"{EMAIL_STATE_PREFIX}{new_email.email_id}", new_email)
        ctx.set_state(CURRENT_EMAIL_ID_KEY, new_email.email_id)
        await ctx.send_message(email_text)


class AnalyzeEmail(Executor):
    """Stub spam classifier — keyword-based, no LLM."""

    @handler
    async def run(self, email_text: str, ctx: WorkflowContext[AnalysisResult]) -> None:
        email_id: str = ctx.get_state(CURRENT_EMAIL_ID_KEY)
        lower = email_text.lower()
        if any(kw in lower for kw in SPAM_KEYWORDS):
            decision, reason = "Spam", "Contains spam keywords"
        elif any(kw in lower for kw in UNCERTAIN_KEYWORDS):
            decision, reason = "Uncertain", "Contains promotional language"
        else:
            decision, reason = "NotSpam", "Looks like a legitimate email"
        await ctx.send_message(
            AnalysisResult(
                spam_decision=decision,
                reason=reason,
                email_length=len(email_text),
                email_summary="",
                email_id=email_id,
            )
        )


class DraftReply(Executor):
    """Stub email assistant — drafts a simple reply."""

    @handler
    async def run(self, analysis: AnalysisResult, ctx: WorkflowContext[Never, str]) -> None:
        email: Email = ctx.get_state(f"{EMAIL_STATE_PREFIX}{analysis.email_id}")
        reply = f"Thank you for your email. I have reviewed the content and will follow up shortly.\n(re: {email.email_content[:60]}...)"
        await ctx.yield_output(f"Email sent: {reply}")


class SummarizeEmail(Executor):
    """Stub summarizer — returns first N chars as summary."""

    @handler
    async def run(self, analysis: AnalysisResult, ctx: WorkflowContext[AnalysisResult]) -> None:
        email: Email = ctx.get_state(f"{EMAIL_STATE_PREFIX}{analysis.email_id}")
        summary = email.email_content[:80].replace("\n", " ") + "..."
        await ctx.send_message(
            AnalysisResult(
                spam_decision="NotSpam",
                reason="",
                email_length=len(email.email_content),
                email_summary=summary,
                email_id=analysis.email_id,
            )
        )


class HandleSpam(Executor):
    @handler
    async def run(self, analysis: AnalysisResult, ctx: WorkflowContext[Never, str]) -> None:
        await ctx.yield_output(f"Email marked as spam: {analysis.reason}")


class HandleUncertain(Executor):
    @handler
    async def run(self, analysis: AnalysisResult, ctx: WorkflowContext[Never, str]) -> None:
        email: Email | None = ctx.get_state(f"{EMAIL_STATE_PREFIX}{analysis.email_id}")
        await ctx.yield_output(
            f"Email marked as uncertain: {analysis.reason}. Email content: {getattr(email, 'email_content', '')}"
        )


class DatabaseAccess(Executor):
    @handler
    async def run(self, analysis: AnalysisResult, ctx: WorkflowContext[Never, str]) -> None:
        await asyncio.sleep(0.05)
        await ctx.add_event(DatabaseEvent(type="database_event", data=f"Email {analysis.email_id} saved to database."))  # type: ignore


# ── Sample emails ────────────────────────────────────────────────
LEGIT_EMAIL_SHORT = "Hello team, here are the updates for this week. All good."

LEGIT_EMAIL_LONG = """\
Subject: Team Meeting Follow-up - Action Items

Hi Sarah,

I wanted to follow up on our team meeting this morning and share the action items we discussed:

1. Update the project timeline by Friday
2. Schedule client presentation for next week
3. Review the budget allocation for Q4

Please let me know if you have any questions or if I missed anything from our discussion.

Best regards,
Alex Johnson
Project Manager
Tech Solutions Inc.
"""

SPAM_EMAIL = """\
Subject: You are the WINNER of a FREE prize!

Click here to claim your reward! Act now — this urgent offer expires today!
"""

UNCERTAIN_EMAIL = """\
Subject: Limited Time Promotion

Dear customer, check out our latest promotion. Unsubscribe if not interested.
"""


async def main() -> None:
    """Build and run the multi-selection edge group workflow (no Foundry dependency)."""

    store_email = StoreEmail(id="store_email")
    analyze_email = AnalyzeEmail(id="analyze_email")
    draft_reply = DraftReply(id="draft_reply")
    summarize_email = SummarizeEmail(id="summarize_email")
    handle_spam = HandleSpam(id="handle_spam")
    handle_uncertain = HandleUncertain(id="handle_uncertain")
    database_access = DatabaseAccess(id="database_access")

    def select_targets(analysis: AnalysisResult, target_ids: list[str]) -> list[str]:
        # Order: [handle_spam, draft_reply, summarize_email, handle_uncertain]
        handle_spam_id, draft_reply_id, summarize_email_id, handle_uncertain_id = target_ids
        if analysis.spam_decision == "Spam":
            return [handle_spam_id]
        if analysis.spam_decision == "NotSpam":
            targets = [draft_reply_id]
            if analysis.email_length > LONG_EMAIL_THRESHOLD:
                targets.append(summarize_email_id)
            return targets
        return [handle_uncertain_id]

    workflow = (
        WorkflowBuilder(start_executor=store_email)
        .add_edge(store_email, analyze_email)
        .add_multi_selection_edge_group(
            analyze_email,
            [handle_spam, draft_reply, summarize_email, handle_uncertain],
            selection_func=select_targets,
        )
        # Save to DB if short (no summary path)
        .add_edge(analyze_email, database_access, condition=lambda r: r.email_length <= LONG_EMAIL_THRESHOLD)
        # Save to DB with summary when long
        .add_edge(summarize_email, database_access)
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
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "multi_selection_workflow.svg"))
    print(f"\nSVG exported to: {svg_file}")

    # ── Run with different email types ────────────────────────────
    for label, email_text in [
        ("Legitimate (short)", LEGIT_EMAIL_SHORT),
        ("Legitimate (long)", LEGIT_EMAIL_LONG),
        ("Spam", SPAM_EMAIL),
        ("Uncertain", UNCERTAIN_EMAIL),
    ]:
        print(f"\n--- {label} ---")
        async for event in workflow.run(email_text, stream=True):
            if isinstance(event, DatabaseEvent):
                print(f"  {event}")
            elif event.type == "output":
                print(f"  Workflow output: {event.data}")


if __name__ == "__main__":
    asyncio.run(main())
