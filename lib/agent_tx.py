"""Transaction system for agent work sessions.

Groups related actions into auditable units with stated intent.
Feeds the dashboard, audit trail, and future claude-gate integration.

Usage:
    from lib.agent_tx import Transaction

    tx = Transaction("pm")
    tx.begin("Implementing rolling summary", "Phase 1 task #18", repo="tquick/meeting-scribe", issue=18)
    tx.action("Created src/summary_prompt.py", "Prompt template for condensed meeting minutes")
    tx.action("Updated pipeline.py", "Integrated summary into batch loop")
    tx.end("success", "Rolling summary working")

    # Read current/recent:
    current = Transaction.current("pm")
    recent = Transaction.recent(limit=10)
"""

import json
import os
import glob
import time
import datetime
from typing import Optional


TX_DIR = os.path.expanduser("~/.claude/agents/transactions")
TX_LOG_DIR = os.path.join(TX_DIR, "log")


class Transaction:
    """Manages agent work transactions."""

    VALID_OUTCOMES = ("success", "partial", "failed", "cancelled", "interrupted")

    def __init__(self, agent_name: Optional[str] = None):
        self.agent_name = agent_name or os.environ.get("CLAUDE_AGENT_NAME", "unknown")
        self.tx_dir = TX_DIR
        self.log_dir = TX_LOG_DIR
        self.current_file = os.path.join(self.tx_dir, f"{self.agent_name}.current.json")
        os.makedirs(self.tx_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)

    def begin(
        self,
        intent: str,
        justification: str,
        repo: Optional[str] = None,
        issue: Optional[int] = None,
    ) -> str:
        """Start a new transaction. Returns the transaction ID."""
        tx_id = f"tx_{int(time.time())}_{self.agent_name}"
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        tx = {
            "id": tx_id,
            "agent": self.agent_name,
            "intent": intent,
            "justification": justification,
            "repo": repo,
            "issue": issue,
            "state": "active",
            "started_at": now,
            "actions": [],
        }
        with open(self.current_file, "w") as f:
            json.dump(tx, f, indent=2)
        return tx_id

    def action(self, what: str, why: str) -> bool:
        """Log an action within the current transaction."""
        if not os.path.exists(self.current_file):
            return False
        try:
            with open(self.current_file) as f:
                tx = json.load(f)
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            tx["actions"].append({
                "timestamp": now,
                "what": what,
                "why": why,
            })
            with open(self.current_file, "w") as f:
                json.dump(tx, f, indent=2)
            return True
        except Exception:
            return False

    def end(self, outcome: str = "success", summary: str = "") -> Optional[str]:
        """End the current transaction and archive it."""
        if not os.path.exists(self.current_file):
            return None
        try:
            with open(self.current_file) as f:
                tx = json.load(f)
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            tx["state"] = "completed"
            tx["outcome"] = outcome
            tx["summary"] = summary or None
            tx["ended_at"] = now
            tx["action_count"] = len(tx["actions"])

            # Archive
            log_file = os.path.join(self.log_dir, f"{tx['id']}.json")
            with open(log_file, "w") as f:
                json.dump(tx, f, indent=2)

            os.remove(self.current_file)
            return tx["id"]
        except Exception:
            return None

    def read_current(self) -> Optional[dict]:
        """Read the current active transaction."""
        if not os.path.exists(self.current_file):
            return None
        try:
            with open(self.current_file) as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def get_current(agent_name: str) -> Optional[dict]:
        """Read a specific agent's current transaction."""
        f = os.path.join(TX_DIR, f"{agent_name}.current.json")
        if not os.path.exists(f):
            return None
        try:
            with open(f) as fh:
                return json.load(fh)
        except Exception:
            return None

    @staticmethod
    def recent(limit: int = 10) -> list[dict]:
        """List recent transactions across all agents."""
        txs = []

        # Active transactions first
        for f in glob.glob(os.path.join(TX_DIR, "*.current.json")):
            try:
                with open(f) as fh:
                    txs.append(json.load(fh))
            except Exception:
                pass

        # Completed transactions
        log_files = sorted(
            glob.glob(os.path.join(TX_LOG_DIR, "*.json")),
            reverse=True,
        )[:limit]
        for f in log_files:
            try:
                with open(f) as fh:
                    txs.append(json.load(fh))
            except Exception:
                pass

        return txs[:limit]
