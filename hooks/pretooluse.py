#!/usr/bin/env python3
"""PreToolUse hook for Wasteland Orchestrator.

Responsibilities:
1. Update agent heartbeat on every tool call
2. Enforce worktree isolation for dev agents
3. Log tool usage context for transaction audit
"""

import json
import os
import sys
import datetime

PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
STATUS_DIR = os.path.expanduser("~/.claude/agents/status")
AGENT_NAME = os.environ.get("CLAUDE_AGENT_NAME", "unknown")


def update_heartbeat():
    """Update the agent's heartbeat timestamp."""
    status_file = os.path.join(STATUS_DIR, f"{AGENT_NAME}.json")
    if not os.path.exists(status_file):
        return
    try:
        with open(status_file) as f:
            data = json.load(f)
        data["last_heartbeat"] = datetime.datetime.now(
            datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(status_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def check_worktree_isolation(command: str) -> dict | None:
    """Warn dev agents working outside worktrees."""
    if not AGENT_NAME.startswith("dev-"):
        return None

    # Very basic check: dev agent cd-ing into main project dir
    projects_dir = os.path.expanduser("~/projects")
    if f"cd {projects_dir}/" in command and ".worktrees" not in command:
        return {
            "decision": "allow",
            "systemMessage": (
                "WARNING: Dev agents should work in worktrees, not the main working tree. "
                "Use: git worktree add ../.worktrees/{task-id} -b {branch-name}"
            ),
        }

    return None


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        print(json.dumps({"decision": "allow"}))
        return

    tool_name = input_data.get("tool_name", "")

    # Always update heartbeat
    update_heartbeat()

    # Only check Bash commands
    if tool_name != "Bash":
        print(json.dumps({"decision": "allow"}))
        return

    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Run checks
    for check in [check_worktree_isolation]:
        result = check(command)
        if result:
            print(json.dumps(result))
            return

    # Default: allow
    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
