"""Gitea integration for auto-closing issues and posting progress updates.

Called by the dispatcher when tasks complete, fail, or during periodic
status updates.

Usage:
    from lib.gitea_updates import GiteaUpdater

    updater = GiteaUpdater("tquick/claude-gate")
    updater.on_task_started(task)
    updater.on_task_completed(task)
    updater.on_task_failed(task, "exit code 1")
    updater.post_phase_status(manifest, completed, failed)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from lib.gitea_api import GiteaClient

if TYPE_CHECKING:
    from lib.manifest import PhaseManifest, Task


class GiteaUpdater:
    """Posts updates to Gitea issues as tasks progress."""

    def __init__(self, repo: str, client: Optional[GiteaClient] = None):
        self.repo = repo
        self.client = client or GiteaClient()

    def on_task_started(self, task: Task) -> None:
        """Post a comment when an agent starts working on a task."""
        if not task.issue:
            return
        self.client.add_comment(
            self.repo,
            task.issue,
            f"Agent `{task.agent}` has started working on this issue.",
        )

    def on_task_completed(self, task: Task) -> None:
        """Close the issue and post a completion comment."""
        if not task.issue:
            return
        self.client.add_comment(
            self.repo,
            task.issue,
            f"Agent `{task.agent}` has completed this issue.",
        )
        self.client.patch(
            f"repos/{self.repo}/issues/{task.issue}",
            {"state": "closed"},
        )

    def on_task_failed(self, task: Task, reason: str = "") -> None:
        """Post a failure comment (don't close the issue)."""
        if not task.issue:
            return
        msg = f"Agent `{task.agent}` failed on this issue."
        if reason:
            msg += f"\n\nReason: {reason}"
        self.client.add_comment(self.repo, task.issue, msg)

    def post_phase_status(
        self,
        manifest: PhaseManifest,
        completed: set[str],
        failed: set[str],
    ) -> None:
        """Post a phase summary comment to all open issues in the phase."""
        total = len(manifest.tasks)
        done = len(completed)
        fail = len(failed)
        remaining = total - done - fail

        lines = [
            f"## Phase Status: {manifest.phase}",
            f"- Completed: {done}/{total}",
        ]
        if fail:
            lines.append(f"- Failed: {fail}")
        if remaining:
            lines.append(f"- Remaining: {remaining}")

        lines.append("\n| Task | Status |")
        lines.append("|-------|--------|")
        for task in manifest.tasks:
            if task.id in completed:
                status = "Done"
            elif task.id in failed:
                status = "Failed"
            else:
                status = "Pending"
            lines.append(f"| {task.id}: {task.title} | {status} |")

        body = "\n".join(lines)

        # Post to each issue that's still open (failed or pending)
        for task in manifest.tasks:
            if task.issue and task.id not in completed:
                self.client.add_comment(self.repo, task.issue, body)
