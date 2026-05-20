# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executors for local demo.

import asyncio
import os
import sys
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
Sample: Concurrent fan out and fan in with three domain agents

A dispatcher fans out the same user prompt to research, marketing, and legal AgentExecutor nodes.
An aggregator then fans in their responses and produces a single consolidated report.

Purpose:
Show how to construct a parallel branch pattern in workflows. Demonstrate:
- Fan out by targeting multiple AgentExecutor nodes from one dispatcher.
- Fan in by collecting a list of AgentExecutorResponse objects and reducing them to a single result.

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- FOUNDRY_MODEL must be set to your Azure OpenAI model deployment name.
- Familiarity with WorkflowBuilder, executors, edges, events, and streaming runs.
- Comfort reading AgentExecutorResponse.agent_response.text for assistant output aggregation.
"""


class DispatchToExperts(Executor):
    """Dispatches the incoming prompt to all expert executors for parallel processing (fan out)."""

    @handler
    async def dispatch(self, prompt: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(prompt)


@dataclass
class ExpertResponse:
    """Typed response from a stub expert."""
    executor_id: str
    text: str


class ExpertExecutor(Executor):
    """Stub domain expert — returns a canned insight based on its role."""

    def __init__(self, role: str, id: str):
        super().__init__(id=id)
        self._role = role

    @handler
    async def run(self, prompt: str, ctx: WorkflowContext[ExpertResponse]) -> None:
        await asyncio.sleep(2)  # Simulate processing time
        response = f"[{self._role}] Analysis of: {prompt[:50]}... — Key points identified."
        await ctx.send_message(ExpertResponse(executor_id=self.id, text=response))


@dataclass
class AggregatedInsights:
    research: str
    marketing: str
    legal: str


class AggregateInsights(Executor):
    """Aggregates expert responses into a single consolidated result (fan in)."""

    @handler
    async def aggregate(self, results: list[ExpertResponse], ctx: WorkflowContext[Never, str]) -> None:
        by_id: dict[str, str] = {}
        for r in results:
            by_id[r.executor_id] = r.text

        aggregated = AggregatedInsights(
            research=by_id.get("researcher", ""),
            marketing=by_id.get("marketer", ""),
            legal=by_id.get("legal", ""),
        )

        consolidated = (
            "Consolidated Insights\n"
            "====================\n\n"
            f"Research Findings:\n{aggregated.research}\n\n"
            f"Marketing Angle:\n{aggregated.marketing}\n\n"
            f"Legal/Compliance Notes:\n{aggregated.legal}\n"
        )

        await ctx.yield_output(consolidated)


async def main() -> None:
    # 1) Create executor instances
    dispatcher = DispatchToExperts(id="dispatcher")
    researcher = ExpertExecutor(role="Market Researcher", id="researcher")
    marketer = ExpertExecutor(role="Marketing Strategist", id="marketer")
    legal = ExpertExecutor(role="Legal/Compliance Reviewer", id="legal")
    aggregator = AggregateInsights(id="aggregator")

    # 2) Build a simple fan out and fan in workflow
    workflow = (
        WorkflowBuilder(start_executor=dispatcher)
        .add_fan_out_edges(dispatcher, [researcher, marketer, legal])
        .add_fan_in_edges([researcher, marketer, legal], aggregator)
        .build()
    )

    # 3) Visualization
    viz = WorkflowViz(workflow)
    print("Mermaid:\n=======")
    print(viz.to_mermaid())
    print("=======")
    print("\nDiGraph:\n=======")
    print(viz.to_digraph(include_internal_executors=True))
    print("=======")

    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "02_fan_out_fan_in_workflow.svg"))
    print(f"\nSVG exported to: {svg_file}\n")

    # 4) Run with a prompt
    print("=" * 60)
    print("Running fan-out/fan-in workflow...")
    print("=" * 60)
    prompt = "We are launching a new budget-friendly electric bike for urban commuters."
    print(f"Prompt: {prompt}\n")

    async for event in workflow.run(prompt, stream=True):
        if event.type == "output":
            print(f"\n{event.data}")


def devui():
    """Launch the workflow in DevUI."""
    from agent_framework.devui import serve

    dispatcher = DispatchToExperts(id="dispatcher")
    researcher = ExpertExecutor(role="Market Researcher", id="researcher")
    marketer = ExpertExecutor(role="Marketing Strategist", id="marketer")
    legal = ExpertExecutor(role="Legal/Compliance Reviewer", id="legal")
    aggregator = AggregateInsights(id="aggregator")

    workflow = (
        WorkflowBuilder(start_executor=dispatcher)
        .add_fan_out_edges(dispatcher, [researcher, marketer, legal])
        .add_fan_in_edges([researcher, marketer, legal], aggregator)
        .build()
    )

    print("Starting DevUI...")
    serve(entities=[workflow], port=8090, auto_open=True)


if __name__ == "__main__":
    if "--devui" in sys.argv:
        devui()
    else:
        asyncio.run(main())
