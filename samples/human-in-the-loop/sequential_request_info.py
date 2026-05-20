# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executors with terminal HITL.

"""
Sample: Sequential Workflow with Human-in-the-Loop Review

This sample demonstrates a sequential document workflow where:
1. A drafter creates an initial draft on a given topic.
2. An editor reviews it and pauses for human feedback (HITL).
3. A finalizer polishes the edited content into a final version.

The editor stage pauses and asks the user for feedback via the terminal,
simulating the original request_info / approval mechanism.
"""

import asyncio
import json
import os

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    handler,
)
from typing_extensions import Never


# ── Stub Executors ──────────────────────────────────────────


class DrafterExecutor(Executor):
    """Creates a brief draft on the given topic."""

    @handler
    async def draft(self, topic: str, ctx: WorkflowContext[str]) -> None:
        print(f"\n📝 [Drafter] Received topic: {topic}")
        draft_text = (
            f"Artificial intelligence (AI) refers to the simulation of human intelligence "
            f"by computer systems. These systems can learn from data, recognise patterns, "
            f"and make decisions with minimal human intervention. AI is transforming "
            f"industries from healthcare to finance."
        )
        print(f"📝 [Drafter] Draft:\n   {draft_text}")
        await ctx.send_message(draft_text)


class EditorExecutor(Executor):
    """Reviews the draft and asks the human for feedback before proceeding."""

    @handler
    async def edit(self, draft: str, ctx: WorkflowContext[str]) -> None:
        print(f"\n✏️  [Editor] Received draft ({len(draft)} chars)")

        # ── Human-in-the-Loop: pause for feedback ──
        print("\n" + "─" * 50)
        print("🔒 HUMAN REVIEW REQUESTED")
        print("─" * 50)
        print(f"   Draft: {draft[:200]}...")
        print("─" * 50)
        feedback = await asyncio.to_thread(
            input, "   Your feedback (or press Enter to approve as-is): "
        )

        if feedback.strip():
            print(f"  ✏️  Incorporating feedback: {feedback}")
            edited = f"{draft}\n\n[Editor note — incorporating feedback: {feedback}]"
        else:
            print("  ✅ Approved as-is")
            edited = f"{draft}\n\n[Editor note: reviewed and approved, no changes needed.]"

        print(f"\n✏️  [Editor] Edited version ready ({len(edited)} chars)")
        await ctx.send_message(edited)


class FinalizerExecutor(Executor):
    """Polishes the edited content into a final version."""

    @handler
    async def finalize(self, edited: str, ctx: WorkflowContext[Never, str]) -> None:
        print("\n🎯 [Finalizer] Polishing final version...")
        final = (
            f"── FINAL DOCUMENT ──\n\n"
            f"{edited}\n\n"
            f"── END ──"
        )
        await ctx.yield_output(final)


# ── Main ────────────────────────────────────────────────────


async def main() -> None:
    drafter = DrafterExecutor(id="drafter")
    editor = EditorExecutor(id="editor")
    finalizer = FinalizerExecutor(id="finalizer")

    workflow = (
        WorkflowBuilder(start_executor=drafter)
        .add_edge(drafter, editor)
        .add_edge(editor, finalizer)
        .build()
    )

    # Visualization
    viz = WorkflowViz(workflow)
    print("Mermaid:\n=======")
    print(viz.to_mermaid())
    print("=======\n")
    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "sequential_request_info_workflow.svg"))
    print(f"SVG exported to: {svg_file}\n")

    # Run
    topic = "Write a brief introduction to artificial intelligence."
    print("=" * 60)
    print(f"Topic: {topic}")
    print("=" * 60)

    async for event in workflow.run(topic, stream=True):
        if event.type == "output":
            print("\n" + "=" * 60)
            print("WORKFLOW COMPLETE")
            print("=" * 60)
            print(event.data)


if __name__ == "__main__":
    asyncio.run(main())
