# Copyright (c) Microsoft. All rights reserved.

"""
Sample: Simple checkpoint workflow with DevUI support.

A word-by-word sentence builder with checkpointing:
  1) StartNode   — split input sentence into words
  2) BuilderNode — process one word at a time (self-loop), checkpoint after each

The workflow can be interrupted and resumed from the last checkpoint.

Usage:
    python samples/simple_checkpoint.py                        # CLI mode (with simulated interruptions)
    python samples/simple_checkpoint.py --devui                # DevUI mode (http://localhost:8080)
"""

import asyncio
import sys
from dataclasses import dataclass, field
from random import random
from typing import Any

from agent_framework import (
    Executor,
    InMemoryCheckpointStorage,
    WorkflowBuilder,
    WorkflowCheckpoint,
    WorkflowContext,
    handler,
)

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


# ── Shared message between nodes ─────────────────────────────────────

@dataclass
class BuildTask:
    """Words remaining to process and the result so far."""
    remaining: list[str]
    result: list[str] = field(default_factory=list)


# ── Step 1: Split sentence into words ────────────────────────────────

class StartNode(Executor):
    @handler
    async def handle(self, sentence: str, ctx: WorkflowContext[BuildTask]) -> None:
        words = sentence.strip().split()
        print(f"  [Start] Splitting into {len(words)} words: {words}")
        await ctx.send_message(BuildTask(remaining=words))


# ── Step 2: Process one word at a time (self-loop) ───────────────────

class BuilderNode(Executor):
    def __init__(self, id: str) -> None:
        super().__init__(id=id)
        self._processed: list[str] = []

    @handler
    async def handle(
        self,
        task: BuildTask,
        ctx: WorkflowContext[BuildTask, str],
    ) -> None:
        word = task.remaining.pop(0)
        styled = word.upper()
        task.result.append(styled)
        self._processed.append(styled)

        print(f"  [Builder] Processed: {word!r} → {styled!r}  (done: {len(task.result)}, left: {len(task.remaining)})")

        if not task.remaining:
            output = " ".join(task.result)
            print(f"  [Builder] Final: {output}")
            await ctx.yield_output(output)
        else:
            await ctx.send_message(task)

    @override
    async def on_checkpoint_save(self) -> dict[str, Any]:
        """Save processed words to checkpoint."""
        return {"processed": self._processed}

    @override
    async def on_checkpoint_restore(self, state: dict[str, Any]) -> None:
        """Restore processed words from checkpoint."""
        self._processed = state.get("processed", [])


# ── Build workflow ───────────────────────────────────────────────────

def create_workflow(checkpoint_storage=None):
    start = StartNode(id="1-start")
    builder = BuilderNode(id="2-builder")
    wb = WorkflowBuilder(start_executor=start, checkpoint_storage=checkpoint_storage)
    wb.add_edge(start, builder)
    wb.add_edge(builder, builder)  # self-loop: process one word per iteration
    return wb


# ── CLI: run with simulated interruptions ────────────────────────────

async def main():
    storage = InMemoryCheckpointStorage()
    builder = create_workflow(checkpoint_storage=storage)

    test_input = "the quick brown fox jumps"
    latest_cp: WorkflowCheckpoint | None = None
    attempt = 0

    while True:
        attempt += 1
        wf = builder.build()
        print(f"\n{'='*40}")
        print(f"  Attempt #{attempt}  (workflow: {wf.id})")
        print(f"{'='*40}")

        stream = (
            wf.run(message=test_input, stream=True)
            if latest_cp is None
            else wf.run(checkpoint_id=latest_cp.checkpoint_id, stream=True)
        )

        output = None
        async for event in stream:
            if event.type == "output":
                output = event.data
                break
            if event.type == "superstep_completed" and random() < 0.4:
                print("\n  ⚡ Simulated crash! Stopping...\n")
                break

        latest_cp = await storage.get_latest(workflow_name=wf.name)
        if latest_cp:
            print(f"  📦 Checkpoint saved (iteration={latest_cp.iteration_count})")

        if output is not None:
            print(f"\n  ✅ Done: {output!r}")
            break

    print()


if __name__ == "__main__":
    if "--devui" in sys.argv:
        from agent_framework.devui import serve

        storage = InMemoryCheckpointStorage()
        wb = create_workflow(checkpoint_storage=storage)
        wf = wb.build()
        print("Starting DevUI at http://localhost:8080")
        print('Try input: the quick brown fox jumps')
        serve(entities=[wf], port=8080)
    else:
        asyncio.run(main())
