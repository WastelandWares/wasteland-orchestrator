#!/usr/bin/env python3
"""PostToolUse hook for Wasteland Orchestrator.

Logs tool results for transaction context. Light-touch — just captures
what happened for the audit trail.
"""

import json
import os
import sys
import datetime

STATUS_DIR = os.path.expanduser("~/.claude/agents/status")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "unknown")


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    # Update heartbeat
    status_file = os.path.join(STATUS_DIR, f"{AGENT_NAME}.json")
    if os.path.exists(status_file):
        try:
            with open(status_file) as f:
                data = json.load(f)
            data["last_heartbeat"] = datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Track last tool used (useful for dashboard)
            data["last_tool"] = input_data.get("tool_name", "")
            with open(status_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # No blocking on post-tool, just tracking
    sys.exit(0)


if __name__ == "__main__":
    main()
