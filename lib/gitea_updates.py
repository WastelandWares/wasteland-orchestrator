"""Gitea integration for auto-closing issues and posting progress updates.

Called by the dispatcher when stories complete, fail, or during periodic
status updates.

Usage:
    from lib.gitea_updates import GiteaUpdater

    updater = GiteaUpdater("tquick/claude-gate")
    updater.on_story_started(story)
    updater.on_story_completed(story)
    updater.on_story_failed(story, "exit code 1")
    updater.post_sprint_status(manifest, completed, failed)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from lib.gitea_api import GiteaClient

if TYPE_CHECKING:
    from lib.manifest import SprintManifest, Story


class GiteaUpdater:
    """Posts updates to Gitea issues as stories progress."""

    def __init__(self, repo: str, client: Optional[GiteaClient] = None):
        self.repo = repo
        self.client = client or GiteaClient()

    def on_story_started(self, story: Story) -> None:
        """Post a comment when an agent starts working on a story."""
        if not story.issue:
            return
        self.client.add_comment(
            self.repo,
            story.issue,
            f"Agent `{story.agent}` has started working on this issue.",
        )

    def on_story_completed(self, story: Story) -> None:
        """Close the issue and post a completion comment."""
        if not story.issue:
            return
        self.client.add_comment(
            self.repo,
            story.issue,
            f"Agent `{story.agent}` has completed this issue.",
        )
        self.client.patch(
            f"repos/{self.repo}/issues/{story.issue}",
            {"state": "closed"},
        )

    def on_story_failed(self, story: Story, reason: str = "") -> None:
        """Post a failure comment (don't close the issue)."""
        if not story.issue:
            return
        msg = f"Agent `{story.agent}` failed on this issue."
        if reason:
            msg += f"\n\nReason: {reason}"
        self.client.add_comment(self.repo, story.issue, msg)

    def post_sprint_status(
        self,
        manifest: SprintManifest,
        completed: set[str],
        failed: set[str],
    ) -> None:
        """Post a sprint summary comment to all open issues in the sprint."""
        total = len(manifest.stories)
        done = len(completed)
        fail = len(failed)
        remaining = total - done - fail

        lines = [
            f"## Sprint Status: {manifest.sprint}",
            f"- Completed: {done}/{total}",
        ]
        if fail:
            lines.append(f"- Failed: {fail}")
        if remaining:
            lines.append(f"- Remaining: {remaining}")

        lines.append("\n| Story | Status |")
        lines.append("|-------|--------|")
        for story in manifest.stories:
            if story.id in completed:
                status = "Done"
            elif story.id in failed:
                status = "Failed"
            else:
                status = "Pending"
            lines.append(f"| {story.id}: {story.title} | {status} |")

        body = "\n".join(lines)

        # Post to each issue that's still open (failed or pending)
        for story in manifest.stories:
            if story.issue and story.id not in completed:
                self.client.add_comment(self.repo, story.issue, body)
