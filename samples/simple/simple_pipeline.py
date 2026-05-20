# Copyright (c) Microsoft. All rights reserved.

"""
Sample: Simple 3-step message pipeline with DevUI support.

A greeting card generator:
  1) ParseInput  — parse user input into name + language
  2) Greeting    — generate a greeting message
  3) FormatCard  — wrap it into a styled card

Usage:
    python samples/simple_pipeline.py                          # CLI mode
    python samples/simple_pipeline.py --devui                  # DevUI mode (http://localhost:8080)
"""

import asyncio
import sys
from dataclasses import dataclass

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)


# ── Shared state passed between nodes ────────────────────────────────

@dataclass
class CardData:
    name: str = ""
    language: str = "en"
    greeting: str = ""


# ── Step 1: Parse input ─────────────────────────────────────────────

class ParseInput(Executor):
    """Parse 'name [language]' string into structured data."""

    @handler
    async def handle(self, text: str, ctx: WorkflowContext[CardData]) -> None:
        parts = text.strip().split()
        name = parts[0] if parts else "World"
        lang = parts[1] if len(parts) > 1 else "en"
        print(f"  [ParseInput] name={name}, language={lang}")
        await ctx.send_message(CardData(name=name, language=lang))


# ── Step 2: Generate greeting ────────────────────────────────────────

GREETINGS = {
    "en": "Hello",
    "zh": "你好",
    "es": "Hola",
    "fr": "Bonjour",
    "ja": "こんにちは",
}


class Greeting(Executor):
    """Generate a greeting in the specified language."""

    @handler(input=CardData, output=CardData)
    async def handle(self, data, ctx) -> None:  # type: ignore
        word = GREETINGS.get(data.language, "Hello")
        data.greeting = f"{word}, {data.name}!"
        print(f"  [Greeting] {data.greeting}")
        await ctx.send_message(data)


# ── Step 3: Format card ─────────────────────────────────────────────

class FormatCard(Executor):
    """Wrap the greeting into a styled card string."""

    @handler(input=CardData, workflow_output=str)
    async def handle(self, data, ctx) -> None:  # type: ignore
        border = "+" + "-" * (len(data.greeting) + 4) + "+"
        card = f"{border}\n|  {data.greeting}  |\n{border}"
        print(f"  [FormatCard]\n{card}")
        await ctx.yield_output(card)


# ── Build workflow ───────────────────────────────────────────────────

def create_workflow():
    parse = ParseInput(id="1-parse-input")
    greet = Greeting(id="2-greeting")
    fmt = FormatCard(id="3-format-card")
    return (
        WorkflowBuilder(start_executor=parse)
        .add_edge(parse, greet)
        .add_edge(greet, fmt)
        .build()
    )


# ── Entry point ──────────────────────────────────────────────────────

async def main():
    workflow = create_workflow()

    for test_input in ["Alice zh", "Bob es", "Charlie"]:
        print(f"\nInput: {test_input!r}")
        result = await workflow.run(test_input)
        outputs = result.get_outputs()
        print(f"Output:\n{outputs[0]}")
        print(f"State: {result.get_final_state()}")


if __name__ == "__main__":
    if "--devui" in sys.argv:
        from agent_framework.devui import serve

        wf = create_workflow()
        print("Starting DevUI at http://localhost:8080")
        print("Try input: Alice zh")
        serve(entities=[wf], port=8080)
    else:
        asyncio.run(main())
