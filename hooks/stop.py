#!/usr/bin/env python3
"""Stop hook for Wasteland Orchestrator.

Cleans up agent status when a session ends. Removes the status file
so the dashboard knows the agent is no longer active.
"""

import json
import os
import sys
import datetime

STATUS_DIR = os.path.expanduser("~/.claude/agents/status")
TX_DIR = os.path.expanduser("~/.claude/agents/transactions")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "unknown")


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        input_data = {}

    # Clean up status file
    status_file = os.path.join(STATUS_DIR, f"{AGENT_NAME}.json")
    if os.path.exists(status_file):
        try:
            os.remove(status_file)
        except OSError:
            pass

    # If there's an active transaction, mark it as interrupted
    tx_file = os.path.join(TX_DIR, f"{AGENT_NAME}.current.json")
    if os.path.exists(tx_file):
        try:
            with open(tx_file) as f:
                tx = json.load(f)
            tx["state"] = "interrupted"
            tx["outcome"] = "session_ended"
            tx["ended_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            tx["action_count"] = len(tx.get("actions", []))

            # Archive to log
            log_dir = os.path.join(TX_DIR, "log")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{tx['id']}.json")
            with open(log_file, "w") as f:
                json.dump(tx, f, indent=2)

            os.remove(tx_file)
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
