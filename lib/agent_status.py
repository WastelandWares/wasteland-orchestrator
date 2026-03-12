"""Agent status reporting library.

Manages structured status files at ~/.claude/agents/status/{name}.json.
Used by hooks for heartbeat tracking and by the dashboard for real-time
agent visibility.

Usage (from hooks or scripts):
    from lib.agent_status import AgentStatus

    status = AgentStatus("pm")
    status.update("working", "Planning phase 2", repo="tquick/meeting-scribe", issue=17)
    status.heartbeat()
    status.clear()
"""

import json
import os
import glob
import datetime
from typing import Optional

STATUS_DIR = os.path.expanduser("~/.claude/agents/status")


class AgentStatus:
    """Manages a single agent's status file."""

    VALID_STATES = (
        "idle", "working", "reviewing", "brainstorming",
        "meeting", "blocked", "starting", "stopping",
    )

    def __init__(self, agent_name: Optional[str] = None):
        self.agent_name = agent_name or os.environ.get("CLAUDE_AGENT_NAME", "unknown")
        self.status_dir = STATUS_DIR
        self.status_file = os.path.join(self.status_dir, f"{self.agent_name}.json")
        os.makedirs(self.status_dir, exist_ok=True)

    def update(
        self,
        state: str = "idle",
        task: str = "",
        repo: Optional[str] = None,
        issue: Optional[int] = None,
    ) -> dict:
        """Write a full status update."""
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Preserve existing avatar if present
        avatar = {}
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file) as f:
                    existing = json.load(f)
                avatar = existing.get("avatar", {})
            except Exception:
                pass

        data = {
            "agent": self.agent_name,
            "state": state,
            "task": task,
            "repo": repo,
            "issue": issue,
            "started_at": now,
            "last_heartbeat": now,
            "pid": os.getpid(),
            "avatar": avatar,
        }
        with open(self.status_file, "w") as f:
            json.dump(data, f, indent=2)
        return data

    def heartbeat(self) -> bool:
        """Update only the heartbeat timestamp and PID."""
        if not os.path.exists(self.status_file):
            return False
        try:
            with open(self.status_file) as f:
                data = json.load(f)
            data["last_heartbeat"] = datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            data["pid"] = os.getpid()
            with open(self.status_file, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False

    def set_task(self, task: str) -> bool:
        """Update just the task description (quick update without full rewrite)."""
        if not os.path.exists(self.status_file):
            return False
        try:
            with open(self.status_file) as f:
                data = json.load(f)
            data["task"] = task
            data["last_heartbeat"] = datetime.datetime.now(
                datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(self.status_file, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False

    def set_avatar(self, avatar: dict) -> bool:
        """Set avatar properties for the visual HQ."""
        if not os.path.exists(self.status_file):
            return False
        try:
            with open(self.status_file) as f:
                data = json.load(f)
            data["avatar"] = avatar
            with open(self.status_file, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False

    def clear(self):
        """Remove status file (agent shutting down)."""
        if os.path.exists(self.status_file):
            os.remove(self.status_file)

    def read(self) -> Optional[dict]:
        """Read current status."""
        if not os.path.exists(self.status_file):
            return None
        try:
            with open(self.status_file) as f:
                return json.load(f)
        except Exception:
            return None


def list_agents() -> list[dict]:
    """Read all agent statuses (for dashboard use)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    agents = []
    for f in glob.glob(os.path.join(STATUS_DIR, "*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            # Check staleness
            hb = data.get("last_heartbeat", "")
            if hb:
                hb_dt = datetime.datetime.fromisoformat(hb.replace("Z", "+00:00"))
                stale_sec = (now - hb_dt).total_seconds()
                data["stale"] = stale_sec > 300
                data["heartbeat_age_sec"] = int(stale_sec)
            # Check if process alive
            pid = data.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)
                    data["process_alive"] = True
                except (OSError, ProcessLookupError):
                    data["process_alive"] = False
            agents.append(data)
        except Exception:
            pass
    return agents
