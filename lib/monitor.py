"""Health monitor for running agents.

Checks agent heartbeats, detects stalled processes, and supports
auto-recovery by restarting failed agents.

Usage:
    from lib.monitor import HealthMonitor

    monitor = HealthMonitor(dispatcher)
    monitor.check_all()  # returns list of issues found
"""

from __future__ import annotations

import os
import time
import datetime
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from lib.agent_status import AgentStatus, list_agents, STATUS_DIR

if TYPE_CHECKING:
    from swarm import Dispatcher, AgentProcess


# Thresholds
HEARTBEAT_STALE_SEC = 300    # 5 minutes without heartbeat = stale
PROCESS_DEAD_GRACE_SEC = 30  # grace period after process death before flagging


@dataclass
class HealthIssue:
    """A detected health problem with an agent."""

    task_id: str
    agent_name: str
    issue_type: str  # stale_heartbeat | process_dead | no_status_file
    message: str
    severity: str = "warning"  # warning | critical


class HealthMonitor:
    """Monitors agent health via status files and process checks."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        stale_threshold: int = HEARTBEAT_STALE_SEC,
        max_retries: int = 1,
    ):
        self.dispatcher = dispatcher
        self.stale_threshold = stale_threshold
        self.max_retries = max_retries
        self.retry_counts: dict[str, int] = {}

    def check_all(self) -> list[HealthIssue]:
        """Check health of all running agents. Returns issues found."""
        issues: list[HealthIssue] = []
        now = datetime.datetime.now(datetime.timezone.utc)

        for task_id, ap in self.dispatcher.agents.items():
            if ap.state != "running":
                continue

            task_issues = self._check_agent(task_id, ap, now)
            issues.extend(task_issues)

        return issues

    def _check_agent(
        self,
        task_id: str,
        ap: AgentProcess,
        now: datetime.datetime,
    ) -> list[HealthIssue]:
        """Check a single agent's health."""
        issues: list[HealthIssue] = []
        agent_name = ap.task.agent

        # Check if process is still alive
        if ap.process is not None and ap.process.poll() is not None:
            exit_code = ap.process.returncode
            if exit_code != 0:
                issues.append(HealthIssue(
                    story_id=task_id,
                    agent_name=agent_name,
                    issue_type="process_dead",
                    message=f"Process exited with code {exit_code}",
                    severity="critical",
                ))
            return issues

        # Check heartbeat via status file
        status_file = os.path.join(STATUS_DIR, f"{agent_name}.json")
        if not os.path.exists(status_file):
            issues.append(HealthIssue(
                story_id=task_id,
                agent_name=agent_name,
                issue_type="no_status_file",
                message="No status file found",
                severity="warning",
            ))
            return issues

        status = AgentStatus(agent_name).read()
        if status:
            hb = status.get("last_heartbeat", "")
            if hb:
                hb_dt = datetime.datetime.fromisoformat(hb.replace("Z", "+00:00"))
                age_sec = (now - hb_dt).total_seconds()
                if age_sec > self.stale_threshold:
                    issues.append(HealthIssue(
                        story_id=task_id,
                        agent_name=agent_name,
                        issue_type="stale_heartbeat",
                        message=f"Heartbeat stale for {int(age_sec)}s (threshold: {self.stale_threshold}s)",
                        severity="critical" if age_sec > self.stale_threshold * 2 else "warning",
                    ))

        return issues

    def attempt_recovery(self, issue: HealthIssue) -> bool:
        """Attempt to recover from a health issue by restarting the agent.

        Returns True if recovery was attempted.
        """
        task_id = issue.task_id
        retry_count = self.retry_counts.get(task_id, 0)

        if retry_count >= self.max_retries:
            print(f"[monitor] {task_id}: max retries ({self.max_retries}) exceeded, marking failed")
            ap = self.dispatcher.agents.get(task_id)
            if ap:
                ap.state = "failed"
                self.dispatcher.failed.add(task_id)
            return False

        if issue.issue_type == "process_dead":
            print(f"[monitor] {task_id}: restarting (attempt {retry_count + 1}/{self.max_retries})")
            ap = self.dispatcher.agents.get(task_id)
            if ap:
                new_ap = self.dispatcher._spawn_agent(ap.task)
                self.dispatcher.agents[task_id] = new_ap
                self.retry_counts[task_id] = retry_count + 1
                return True

        return False


def print_health_report(issues: list[HealthIssue]) -> None:
    """Print a health report to stdout."""
    if not issues:
        print("[monitor] All agents healthy.")
        return
    print(f"[monitor] {len(issues)} health issue(s):")
    for issue in issues:
        icon = "!!" if issue.severity == "critical" else "  "
        print(f"  {icon} {issue.task_id} ({issue.agent_name}): {issue.issue_type} — {issue.message}")
