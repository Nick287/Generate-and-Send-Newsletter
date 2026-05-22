#!/usr/bin/env python3
"""
AI Weekly Digest — CLI entry point.
AI 周刊摘要 — 命令行入口。

Usage | 用法:
    python agent_run.py                         # Full pipeline | 完整流水线
    python agent_run.py --dry-run               # Skip send | 跳过发送
    python agent_run.py --to user@x.com         # Override recipient | 覆盖收件人
    python agent_run.py --retries 2             # Auto-retry on failure | 失败自动重试
"""

from __future__ import annotations

import argparse
import asyncio
import sys

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

from agent_framework import (
    AgentResponseUpdate,
    InMemoryCheckpointStorage,
    WorkflowCheckpoint,
)

from agent_workflow import WorkflowInput, build_workflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Weekly Digest — Agent Framework workflow"
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip email sending")
    parser.add_argument("--to", help="Override recipient email(s), comma-separated")
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        metavar="N",
        help="Auto-retry up to N times on failure using checkpoint resume (失败时自动重试N次)",
    )
    parser.add_argument(
        "--languages",
        nargs="*",
        default=None,
        metavar="LOCALE",
        help=(
            "Override config.compose_languages. Example: --languages zh ko ja vi. "
            "Pass --languages with no values to force EN-only (legacy linear shape). "
            "Omit the flag entirely to use config.yaml. (覆盖 config.compose_languages)"
        ),
    )
    return parser.parse_args()


async def run_cli(args: argparse.Namespace) -> int:
    """Run the newsletter workflow with in-process checkpoint retry.
    使用进程内 checkpoint 重试运行新闻简报工作流。"""
    print("=" * 60)
    print("  AI Weekly Digest — Agent Framework Workflow")
    print("=" * 60)
    print()

    storage = InMemoryCheckpointStorage()
    workflow_input = WorkflowInput(
        dry_run=args.dry_run,
        to_override=args.to or "",
        languages=args.languages,
    )
    latest_checkpoint: WorkflowCheckpoint | None = None
    max_retries = args.retries
    attempt = 0

    while True:
        attempt += 1
        workflow = build_workflow(
            checkpoint_storage=storage,
            languages=args.languages,
        )

        if latest_checkpoint is not None:
            print(
                "⚡ Retry %d/%d — resuming from checkpoint %s"
                % (attempt - 1, max_retries, latest_checkpoint.checkpoint_id[:12])
            )
            print(
                "  (iteration %d, saved at %s)"
                % (latest_checkpoint.iteration_count, latest_checkpoint.timestamp)
            )
            print()
            stream = workflow.run(
                checkpoint_id=latest_checkpoint.checkpoint_id, stream=True
            )
        else:
            stream = workflow.run(workflow_input, stream=True)

        try:
            async for event in stream:
                if isinstance(event, AgentResponseUpdate):
                    for c in event.contents or []:
                        if hasattr(c, "text") and c.text:
                            print(c.text)

            result = await stream.get_final_response()

            # Check if workflow ended with an error
            # 检查工作流是否以错误结束
            final_state = result.get_final_state()
            if final_state and hasattr(final_state, "error") and final_state.error:
                raise RuntimeError(final_state.error)

            # Success
            return 0

        except Exception as exc:
            # Grab the latest checkpoint for potential retry
            # 获取最新检查点用于可能的重试
            latest_checkpoint = await storage.get_latest(workflow_name=workflow.name)

            if attempt > max_retries or latest_checkpoint is None:
                print()
                print("❌ Failed after %d attempt(s): %s" % (attempt, exc))
                return 2

            print()
            print("⚠️  Step failed: %s" % str(exc)[:200])
            print("   Checkpoint available — will retry…")
            print()


async def main() -> int:
    args = parse_args()
    return await run_cli(args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
