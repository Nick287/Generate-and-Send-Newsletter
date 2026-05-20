# Copyright (c) Microsoft. All rights reserved.

import asyncio
import os
from dataclasses import dataclass

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    handler,
)
from typing_extensions import Never

"""
Sample: Concurrent (Fan-out/Fan-in) with Agents + Visualization

What it does:
- Fan-out: dispatch the same prompt to multiple domain agents (research, marketing, legal).
- Fan-in: aggregate their responses into one consolidated output.
- Visualization: generate Mermaid and GraphViz representations via `WorkflowViz` and optionally export SVG.

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- FOUNDRY_MODEL must be set to your Azure OpenAI model deployment name.
- Authentication via `azure-identity` — uses `AzureCliCredential()` (run `az login`).
- For visualization export: `pip install graphviz>=0.20.0` and install GraphViz binaries.
"""


class DispatchToExperts(Executor):
    """Dispatches the incoming prompt to all expert agent executors (fan-out)."""

    @handler
    async def dispatch(self, prompt: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(prompt)


class ExpertExecutor(Executor):
    """Stub expert executor (replaces real Agent for viz-only mode)."""

    @handler
    async def process(self, prompt: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(f"[{self.id}] processed: {prompt}")


class AggregateInsights(Executor):
    """Aggregates expert responses into a single consolidated result (fan-in)."""

    @handler
    async def aggregate(self, results: list[str], ctx: WorkflowContext[Never, str]) -> None:
        consolidated = "\n".join(results)
        await ctx.yield_output(consolidated)


async def main() -> None:
    """Build and visualize the concurrent workflow (no Foundry dependency)."""

    dispatcher = DispatchToExperts(id="dispatcher")
    researcher = ExpertExecutor(id="researcher")
    marketer = ExpertExecutor(id="marketer")
    legal = ExpertExecutor(id="legal")
    aggregator = AggregateInsights(id="aggregator")

    # Build a simple fan-out/fan-in workflow
    workflow = (
        WorkflowBuilder(start_executor=dispatcher)
        .add_fan_out_edges(dispatcher, [researcher, marketer, legal])
        .add_fan_in_edges([researcher, marketer, legal], aggregator)
        .build()
    )

    # Generate workflow visualization
    print("Generating workflow visualization...")
    viz = WorkflowViz(workflow)
    # Print out the mermaid string.
    print("Mermaid string: \n=======")
    print(viz.to_mermaid())
    print("=======")
    # Print out the DiGraph string with internal executors.
    print("DiGraph string: \n=======")
    print(viz.to_digraph(include_internal_executors=True))
    print("=======")

    # Export the DiGraph visualization as SVG to current directory.
    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "concurrent_workflow.svg"))
    print(f"SVG file saved to: {svg_file}")


if __name__ == "__main__":
    asyncio.run(main())
