# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executors for local demo.

import asyncio
import os
import sys
from typing import Any, Literal

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    handler,
)
from pydantic import BaseModel, Field
from typing_extensions import Never


class EmailTestRequest(BaseModel):
    """Input configuration shown as a form in DevUI."""

    email_type: Literal["legitimate", "spam", "threat"] = Field(
        description="Select which sample email to classify",
        default="legitimate",
    )

class DetectionResult(BaseModel):
    """Represents the result of spam detection."""

    # is_spam drives the routing decision taken by edge conditions
    is_spam: bool
    # is_threat indicates a high-severity spam (phishing / malware) that needs an alert
    is_threat: bool = False
    # Human readable rationale from the detector
    reason: str
    # The agent must include the original email so downstream agents can operate without reloading content
    email_content: str


class EmailResponse(BaseModel):
    """Represents the response from the email assistant."""

    # The drafted reply that a user could copy or send
    response: str


def is_spam_condition(message: Any) -> bool:
    """Route to spam handler when is_spam is True."""
    if not isinstance(message, DetectionResult):
        return True
    return message.is_spam


def is_not_spam_condition(message: Any) -> bool:
    """Route to email assistant when is_spam is False."""
    if not isinstance(message, DetectionResult):
        return True
    return not message.is_spam


def is_threat_condition(message: Any) -> bool:
    """Route to threat alert only when both is_spam and is_threat are True."""
    if not isinstance(message, DetectionResult):
        return True
    return message.is_spam and message.is_threat


class SpamDetector(Executor):
    """Stub spam detector — classifies email locally without calling an LLM."""

    SPAM_KEYWORDS = ["winner", "prize", "click here", "free", "act now", "urgent offer"]
    THREAT_KEYWORDS = ["password", "verify your account", "bank", "ssn", "credential", "login immediately"]

    @handler
    async def detect(self, request: EmailTestRequest, ctx: WorkflowContext[DetectionResult]) -> None:
        emails = {"legitimate": LEGIT_EMAIL, "spam": SPAM_EMAIL, "threat": THREAT_EMAIL}
        email_text = emails[request.email_type]
        await asyncio.sleep(1.5)  # Simulate detection processing
        lower = email_text.lower()
        is_spam = any(kw in lower for kw in self.SPAM_KEYWORDS)
        is_threat = is_spam and any(kw in lower for kw in self.THREAT_KEYWORDS)
        if is_threat:
            reason = "Spam with threat indicators (possible phishing/malware)"
        elif is_spam:
            reason = "Contains spam keywords"
        else:
            reason = "Looks like a legitimate email"
        result = DetectionResult(is_spam=is_spam, is_threat=is_threat, reason=reason, email_content=email_text)
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


class ThreatAlertHandler(Executor):
    """Sends a threat alert when spam is detected — runs in parallel with SpamHandler."""

    @handler
    async def alert(self, detection: DetectionResult, ctx: WorkflowContext[Never, str]) -> None:
        await asyncio.sleep(0.5)  # Simulate alert dispatch
        await ctx.yield_output(
            f"⚠ THREAT ALERT: Potential phishing/malware detected!\n"
            f"  Reason : {detection.reason}\n"
            f"  Preview: {detection.email_content[:60]}..."
        )


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

THREAT_EMAIL = """\
Subject: URGENT — Verify your account or lose access!

Click here to verify your account immediately. We need your password and bank
details to confirm your identity. Act now — your credential will expire today!
"""


async def main() -> None:
    """Build and run the conditional-routing workflow (no Foundry dependency)."""

    spam_detector = SpamDetector(id="spam_detector")
    email_assistant = EmailAssistant(id="email_assistant")
    spam_handler = SpamHandler(id="spam_handler")
    threat_alert = ThreatAlertHandler(id="threat_alert")

    workflow = (
        WorkflowBuilder(start_executor=spam_detector)
        # Not-spam path: detector → email assistant
        .add_edge(spam_detector, email_assistant, condition=is_not_spam_condition)
        # Spam path: detector → spam handler  (fires for ALL spam)
        .add_edge(spam_detector, spam_handler, condition=is_spam_condition)
        # Threat path: detector → threat alert (fires only for spam + threat)
        .add_edge(spam_detector, threat_alert, condition=is_threat_condition)
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
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "01_edge_condition_workflow.svg"))
    print(f"\nSVG exported to: {svg_file}\n")

    # Let user choose which email to test
    print("=" * 60)
    print("Email Classification Workflow - Choose a test case:")
    print("=" * 60)
    print("1. Legitimate email          → email_assistant")
    print("2. Spam email                → spam_handler only")
    print("3. Spam + threat email       → spam_handler + threat_alert")
    print("4. All of the above")
    print()

    try:
        choice = input("Enter your choice (1-4, default=4): ").strip() or "4"
    except EOFError:
        choice = "4"

    test_cases = [
        ("1", "legitimate", "Legitimate email",     LEGIT_EMAIL),
        ("2", "spam",       "Spam email",           SPAM_EMAIL),
        ("3", "threat",     "Spam + threat email",  THREAT_EMAIL),
    ]

    for key, email_type, label, sample in test_cases:
        if choice == key or choice == "4":
            print("\n" + "=" * 60)
            print(f"Testing: {label}")
            print("=" * 60)
            print(f"Email subject: {sample.split(chr(10))[0]}\n")
            events = await workflow.run(EmailTestRequest(email_type=email_type))
            for out in events.get_outputs():
                print(f"\n{out}")


def devui():
    """Launch the workflow in DevUI — select email type from a dropdown."""
    from agent_framework.devui import serve

    spam_detector = SpamDetector(id="spam_detector")
    email_assistant = EmailAssistant(id="email_assistant")
    spam_handler = SpamHandler(id="spam_handler")
    threat_alert = ThreatAlertHandler(id="threat_alert")

    workflow = (
        WorkflowBuilder(start_executor=spam_detector)
        .add_edge(spam_detector, email_assistant, condition=is_not_spam_condition)
        .add_edge(spam_detector, spam_handler, condition=is_spam_condition)
        .add_edge(spam_detector, threat_alert, condition=is_threat_condition)
        .build()
    )

    print("=" * 60)
    print("  Email Classification Workflow — DevUI")
    print("  http://localhost:8090")
    print("=" * 60)

    serve(entities=[workflow], port=8090, auto_open=True)


if __name__ == "__main__":
    if "--devui" in sys.argv:
        devui()
    else:
        asyncio.run(main())
