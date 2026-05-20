# Copyright (c) Microsoft. All rights reserved.
# Modified: Foundry dependency removed — uses stub executor for local demo.

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Annotated

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    WorkflowViz,
    executor,
    handler,
    tool,
)
from typing_extensions import Never

"""
Sample: Agents in a workflow with AI functions requiring approval

This sample creates a workflow that automatically replies to incoming emails.
If historical email data is needed, it uses an AI function to read the data,
which requires human approval before execution.

This sample works as follows:
1. An incoming email is received by the workflow.
2. The EmailPreprocessor executor preprocesses the email, adding special notes if the sender is important.
3. The preprocessed email is sent to the Email Writer agent, which generates a response.
4. If the agent needs to read historical email data, it calls the read_historical_email_data AI function,
   which triggers an approval request.
5. The sample automatically approves the request for demonstration purposes.
6. Once approved, the AI function executes and returns the historical email data to the agent.
7. The agent uses the historical data to compose a comprehensive email response.
8. The response is sent to the conclude_workflow_executor, which yields the final response.

Purpose:
Show how to integrate AI functions with approval requests into a workflow.

Demonstrate:
- Creating AI functions that require approval before execution.
- Building a workflow that includes an agent and executors.
- Handling approval requests during workflow execution.

Prerequisites:
- FOUNDRY_PROJECT_ENDPOINT must be your Azure AI Foundry Agent Service (V2) project endpoint.
- FOUNDRY_MODEL must be set to your Azure OpenAI model deployment name.
- Authentication via azure-identity. Use AzureCliCredential and run az login before executing the sample.
- Basic familiarity with WorkflowBuilder, edges, events, request_info events (type='request_info'), and streaming runs.
"""


# NOTE: approval_mode="never_require" is for sample brevity. Use "always_require" in production;
# See:
# samples/02-agents/tools/function_tool_with_approval.py
# samples/02-agents/tools/function_tool_with_approval_and_sessions.py.
@tool(approval_mode="never_require")
def get_current_date() -> str:
    """Get the current date in YYYY-MM-DD format."""
    # For demonstration purposes, we return a fixed date.
    return "2025-11-07"


@tool(approval_mode="never_require")
def get_team_members_email_addresses() -> list[dict[str, str]]:
    """Get the email addresses of team members."""
    # In a real implementation, this might query a database or directory service.
    return [
        {
            "name": "Alice",
            "email": "alice@contoso.com",
            "position": "Software Engineer",
            "manager": "John Doe",
        },
        {
            "name": "Bob",
            "email": "bob@contoso.com",
            "position": "Product Manager",
            "manager": "John Doe",
        },
        {
            "name": "Charlie",
            "email": "charlie@contoso.com",
            "position": "Senior Software Engineer",
            "manager": "John Doe",
        },
        {
            "name": "Mike",
            "email": "mike@contoso.com",
            "position": "Principal Software Engineer Manager",
            "manager": "VP of Engineering",
        },
    ]


@tool(approval_mode="never_require")
def get_my_information() -> dict[str, str]:
    """Get my personal information."""
    return {
        "name": "John Doe",
        "email": "john@contoso.com",
        "position": "Software Engineer Manager",
        "manager": "Mike",
    }


@tool(approval_mode="always_require")
async def read_historical_email_data(
    email_address: Annotated[str, "The email address to read historical data from"],
    start_date: Annotated[str, "The start date in YYYY-MM-DD format"],
    end_date: Annotated[str, "The end date in YYYY-MM-DD format"],
) -> list[dict[str, str]]:
    """Read historical email data for a given email address and date range."""
    historical_data = {
        "alice@contoso.com": [
            {
                "from": "alice@contoso.com",
                "to": "john@contoso.com",
                "date": "2025-11-05",
                "subject": "Bug Bash Results",
                "body": "We just completed the bug bash and found a few issues that need immediate attention.",
            },
            {
                "from": "alice@contoso.com",
                "to": "john@contoso.com",
                "date": "2025-11-03",
                "subject": "Code Freeze",
                "body": "We are entering code freeze starting tomorrow.",
            },
        ],
        "bob@contoso.com": [
            {
                "from": "bob@contoso.com",
                "to": "john@contoso.com",
                "date": "2025-11-04",
                "subject": "Team Outing",
                "body": "Don't forget about the team outing this Friday!",
            },
            {
                "from": "bob@contoso.com",
                "to": "john@contoso.com",
                "date": "2025-11-02",
                "subject": "Requirements Update",
                "body": "The requirements for the new feature have been updated. Please review them.",
            },
        ],
        "charlie@contoso.com": [
            {
                "from": "charlie@contoso.com",
                "to": "john@contoso.com",
                "date": "2025-11-05",
                "subject": "Project Update",
                "body": "The bug bash went well. A few critical bugs but should be fixed by the end of the week.",
            },
            {
                "from": "charlie@contoso.com",
                "to": "john@contoso.com",
                "date": "2025-11-06",
                "subject": "Code Review",
                "body": "Please review my latest code changes.",
            },
        ],
    }

    emails = historical_data.get(email_address, [])
    return [email for email in emails if start_date <= email["date"] <= end_date]


@tool(approval_mode="always_require")
async def send_email(
    to: Annotated[str, "The recipient email address"],
    subject: Annotated[str, "The email subject"],
    body: Annotated[str, "The email body"],
) -> str:
    """Send an email."""
    await asyncio.sleep(1)  # Simulate sending email
    return "Email successfully sent."


@dataclass
class Email:
    sender: str
    subject: str
    body: str


class EmailPreprocessor(Executor):
    def __init__(self, special_email_addresses: set[str]) -> None:
        super().__init__(id="email_preprocessor")
        self.special_email_addresses = special_email_addresses

    @handler
    async def preprocess(self, email: Email, ctx: WorkflowContext[str]) -> None:
        """Preprocess the incoming email."""
        email_payload = f"Incoming email:\nFrom: {email.sender}\nSubject: {email.subject}\nBody: {email.body}"
        message = email_payload
        if email.sender in self.special_email_addresses:
            note = (
                "Priority sender context: this message is business-critical. "
                "If additional context is needed, use available tools to retrieve only the minimum relevant "
                "prior team communication related to this request."
            )
            message = f"{note}\n\n{email_payload}"

        await ctx.send_message(message)


class EmailWriterExecutor(Executor):
    """Stub executor that simulates the LLM Agent's email-writing behaviour.

    It calls the tool functions directly (no LLM needed) and composes a reply.
    """

    @handler
    async def write_reply(self, email_text: str, ctx: WorkflowContext[str]) -> None:
        """Simulate the agent reading tools and composing a reply."""
        my_info = get_my_information()
        team = get_team_members_email_addresses()
        current_date = get_current_date()

        print(f"\n[EmailWriter] My info: {my_info['name']} ({my_info['position']})")
        print(f"[EmailWriter] Current date: {current_date}")
        print(f"[EmailWriter] Team size: {len(team)}")

        # Read historical emails for each team member — requires human approval
        all_history: dict[str, list[dict[str, str]]] = {}
        for member in team:
            if member["email"] == my_info["email"]:
                continue  # skip self
            args = {"email_address": member["email"], "start_date": "2025-10-31", "end_date": current_date}
            approved = await self._request_approval("read_historical_email_data", args)
            if not approved:
                print("  ⏭️  Skipped")
                continue
            emails = await read_historical_email_data(**args)
            if emails:
                all_history[member["name"]] = emails
                print(f"  📧 Found {len(emails)} email(s)")
            else:
                print("  📭 No emails found")

        # Compose the reply
        lines = [f"Hi {email_text.split('From: ')[1].split(chr(10))[0].strip()},", ""]
        lines.append("Here's the status update from our team:")
        for name, emails in all_history.items():
            lines.append(f"\n**{name}:**")
            for e in emails:
                lines.append(f"  - [{e['date']}] {e['subject']}: {e['body']}")
        lines.append(f"\nBest regards,\n{my_info['name']}")
        response = "\n".join(lines)

        # Send the email — requires human approval
        sender_email = email_text.split("From: ")[1].split("\n")[0].strip()
        send_args = {"to": sender_email, "subject": "Re: Team's Status Update", "body": "(see above)"}
        approved = await self._request_approval("send_email", send_args)
        if approved:
            result = await send_email(to=sender_email, subject="Re: Team's Status Update", body=response)
            print(f"  ✅ {result}")
        else:
            print("  ❌ Email sending denied by human reviewer")

        await ctx.send_message(response)

    @staticmethod
    async def _request_approval(func_name: str, args: dict) -> bool:
        """Pause and ask human for approval before executing a sensitive tool."""
        print(f"\n{'─' * 50}")
        print(f"🔒 APPROVAL REQUIRED: {func_name}")
        print(f"   Arguments: {json.dumps(args, indent=4)}")
        answer = await asyncio.to_thread(input, "   Approve? [Y/n]: ")
        approved = answer.strip().lower() in ("", "y", "yes")
        if approved:
            print("  ✅ Approved")
        else:
            print("  ❌ Denied")
        return approved


@executor(id="conclude_workflow_executor")
async def conclude_workflow(
    email_response: str,
    ctx: WorkflowContext[Never, str],
) -> None:
    """Conclude the workflow by yielding the final email response."""
    await ctx.yield_output(email_response)


async def main() -> None:
    # Create executors
    email_processor = EmailPreprocessor(special_email_addresses={"mike@contoso.com"})
    email_writer = EmailWriterExecutor(id="email_writer")

    # Build the workflow
    workflow = (
        WorkflowBuilder(start_executor=email_processor, output_executors=[conclude_workflow])
        .add_edge(email_processor, email_writer)
        .add_edge(email_writer, conclude_workflow)
        .build()
    )

    # --- Visualization ---
    viz = WorkflowViz(workflow)
    print("Mermaid:\n=======")
    print(viz.to_mermaid())
    print("=======\n")
    _dir = os.path.dirname(os.path.abspath(__file__))
    svg_file = viz.export(format="svg", filename=os.path.join(_dir, "agents_with_approval_workflow.svg"))
    print(f"SVG exported to: {svg_file}\n")

    # Simulate an incoming email
    incoming_email = Email(
        sender="mike@contoso.com",
        subject="Important: Project Update",
        body="Please provide your team's status update on the project since last week.",
    )

    print("=" * 60)
    print("Running email workflow...")
    print("=" * 60)
    async for event in workflow.run(incoming_email, stream=True):
        if event.type == "output":
            print("\nFinal email response:")
            print(event.data)


if __name__ == "__main__":
    asyncio.run(main())
