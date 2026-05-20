# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses local judge executor.

import asyncio
import os
from enum import Enum

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    handler,
)

"""
Sample: Simple Loop (with an Agent Judge)

What it does:
- Guesser performs a binary search; judge is an agent that returns ABOVE/BELOW/MATCHED.
- Demonstrates feedback loops in workflows with agent steps.
- The workflow completes when the correct number is guessed.

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- FOUNDRY_MODEL must be set to your Azure OpenAI model deployment name.
- Authentication via `azure-identity` — uses `AzureCliCredential()` (run `az login`).
"""


class NumberSignal(Enum):
    """Enum to represent number signals for the workflow."""

    # The target number is above the guess.
    ABOVE = "above"
    # The target number is below the guess.
    BELOW = "below"
    # The guess matches the target number.
    MATCHED = "matched"
    # Initial signal to start the guessing process.
    INIT = "init"


class GuessNumberExecutor(Executor):
    """An executor that guesses a number."""

    def __init__(self, bound: tuple[int, int], id: str):
        """Initialize the executor with a target number."""
        super().__init__(id=id)
        self._lower = bound[0]
        self._upper = bound[1]

    @handler
    async def guess_number(self, feedback: NumberSignal, ctx: WorkflowContext[int, str]) -> None:
        """Execute the task by guessing a number."""
        if feedback == NumberSignal.INIT:
            self._guess = (self._lower + self._upper) // 2
            await ctx.send_message(self._guess)
        elif feedback == NumberSignal.MATCHED:
            # The previous guess was correct.
            await ctx.yield_output(f"Guessed the number: {self._guess}")
        elif feedback == NumberSignal.ABOVE:
            # The previous guess was too low.
            # Update the lower bound to the previous guess.
            # Generate a new number that is between the new bounds.
            self._lower = self._guess + 1
            self._guess = (self._lower + self._upper) // 2
            await ctx.send_message(self._guess)
        else:
            # The previous guess was too high.
            # Update the upper bound to the previous guess.
            # Generate a new number that is between the new bounds.
            self._upper = self._guess - 1
            self._guess = (self._lower + self._upper) // 2
            await ctx.send_message(self._guess)


class JudgeExecutor(Executor):
    """Local judge — compares guess to target, no LLM needed."""

    def __init__(self, target: int, id: str = "judge"):
        super().__init__(id=id)
        self._target = target

    @handler
    async def judge(self, guess: int, ctx: WorkflowContext[NumberSignal]) -> None:
        if guess == self._target:
            await ctx.send_message(NumberSignal.MATCHED)
        elif guess < self._target:
            await ctx.send_message(NumberSignal.ABOVE)
        else:
            await ctx.send_message(NumberSignal.BELOW)


async def main():
    """Main function to run the workflow."""
    guess_number = GuessNumberExecutor((1, 100), "guess_number")
    judge = JudgeExecutor(target=30)

    workflow = (
        WorkflowBuilder(start_executor=guess_number)
        .add_edge(guess_number, judge)
        .add_edge(judge, guess_number)
        .build()
    )

    # Visualization
    viz = WorkflowViz(workflow)
    print("Mermaid:\n=======")
    print(viz.to_mermaid())
    print("=======")
    print("\nDiGraph:\n=======")
    print(viz.to_digraph(include_internal_executors=True))
    print("=======")

    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "simple_loop_workflow.svg"))
    print(f"\nSVG exported to: {svg_file}")

    # Run the workflow
    print("\n--- Guessing target=30 in range [1, 100] ---")
    iterations = 0
    async for event in workflow.run(NumberSignal.INIT, stream=True):
        if event.type == "executor_completed" and event.executor_id == "guess_number":
            iterations += 1
        elif event.type == "output":
            print(f"Workflow output: {event.data}")

    print(f"Guessed {iterations - 1} times.")


if __name__ == "__main__":
    asyncio.run(main())
