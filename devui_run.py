#!/usr/bin/env python3
"""
Launch DevUI for the newsletter workflow agent.
启动 DevUI 用于新闻简报工作流 agent 的开发调试。

Usage:
    python devui_run.py
    python devui_run.py --port 8080
    python devui_run.py --tracing
"""

import argparse

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

from agent_framework.devui import serve
from agent_run import newsletter_workflow


def main():
    parser = argparse.ArgumentParser(description="AI Weekly Digest — DevUI")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--tracing", action="store_true", help="Enable OpenTelemetry tracing")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    print("=" * 60)
    print("  AI Weekly Digest — DevUI")
    print("  http://localhost:%d" % args.port)
    print("=" * 60)
    print()

    serve(
        entities=[newsletter_workflow],
        port=args.port,
        auto_open=not args.no_open,
        instrumentation_enabled=args.tracing,
    )


if __name__ == "__main__":
    main()
