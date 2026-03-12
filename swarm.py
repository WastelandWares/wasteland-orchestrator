#!/usr/bin/env python3
"""Swarm dispatcher — the brain of the orchestrator.

Reads a sprint manifest, builds a dependency DAG, spawns `claude -p` agents
in worktrees, and monitors their progress via status files.

Usage:
    python3 swarm.py sprint.yaml                # Launch the swarm
    python3 swarm.py sprint.yaml --dry-run      # Show execution plan
    python3 swarm.py --status                   # Show running agents
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib.agent_status import AgentStatus, list_agents
from lib.conflict import detect_conflicts, apply_serialization, print_conflicts
from lib.manifest import SprintManifest, Story
from lib.gitea_updates import GiteaUpdater
from lib.monitor import HealthMonitor, print_health_report


STATUS_DIR = os.path.expanduser("~/.claude/agents/status")
POLL_INTERVAL = 10  # seconds between status checks
SCOREBOARD_FILE = "scoreboard.md"
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")

# Map repo slugs to local paths
REPO_PATHS: dict[str, str] = {
    "tquick/claude-gate": os.path.expanduser("~/projects/claude-gate"),
    "tquick/dnd-tools": os.path.expanduser("~/projects/dnd-tools"),
    "tquick/wasteland-infra": os.path.expanduser("~/projects/wasteland-infra"),
    "tquick/meeting-scribe": os.path.expanduser("~/projects/meeting-scribe"),
    "tquick/dungeon-crawler": os.path.expanduser("~/projects/dungeon-crawler"),
    "tquick/wasteland-orchestrator": os.path.expanduser("~/projects/wasteland-orchestrator"),
}


@dataclass
class AgentProcess:
    """Tracks a running claude -p agent."""

    story: Story
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    state: str = "pending"  # pending | running | done | failed
    exit_code: Optional[int] = None
    output_file: Optional[str] = None


class Dispatcher:
    """Spawns and manages agent processes from a sprint manifest."""

    def __init__(self, manifest: SprintManifest, dry_run: bool = False):
        self.manifest = manifest
        self.dry_run = dry_run
        self.agents: dict[str, AgentProcess] = {}
        self.completed: set[str] = set()
        self.failed: set[str] = set()
        self._shutdown = False

        # Multi-repo: create per-repo updaters
        self._gitea_updaters: dict[str, GiteaUpdater] = {}
        repos = set(s.repo for s in manifest.stories if s.repo)
        for repo in repos:
            self._gitea_updaters[repo] = GiteaUpdater(repo)
        # Legacy single-repo fallback
        self.gitea = GiteaUpdater(manifest.repo) if manifest.repo else None

        # Register signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        print(f"\n[swarm] Received signal {signum}, shutting down...")
        self._shutdown = True
        self._kill_all()

    def _kill_all(self) -> None:
        """Terminate all running agent processes."""
        for story_id, ap in self.agents.items():
            if ap.process and ap.process.poll() is None:
                print(f"[swarm] Terminating {story_id} (PID {ap.pid})")
                ap.process.terminate()
                try:
                    ap.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ap.process.kill()

    def _resolve_repo_path(self, story: Story) -> str:
        """Resolve the local filesystem path for a story's repository."""
        return REPO_PATHS.get(story.repo, os.path.expanduser(f"~/projects/{story.repo.split('/')[-1]}"))

    def _build_prompt(self, story: Story) -> str:
        """Build the prompt for a claude -p agent with worktree and PR instructions."""
        repo_path = self._resolve_repo_path(story)
        branch_name = f"feat/issue-{story.issue}-{story.title.lower()[:30].replace(' ', '-').rstrip('-')}"
        worktree_dir = f"{repo_path}/.worktrees/{branch_name}"

        parts = [
            f"You are agent '{story.agent}' working on: {story.title}",
            f"Repository: {story.repo}",
            f"Local repo path: {repo_path}",
        ]
        if story.issue:
            parts.append(f"Gitea issue: #{story.issue}")
        if story.files:
            parts.append(f"Key files: {', '.join(story.files)}")
        if story.prompt:
            parts.append(f"\nTask details:\n{story.prompt}")

        parts.append(f"""

## MANDATORY WORKFLOW — Follow these steps exactly:

### 1. Worktree Isolation
You MUST work in an isolated git worktree. Never modify the main working tree.
```bash
cd {repo_path}
git fetch origin
git worktree add {worktree_dir} -b {branch_name} origin/main
cd {worktree_dir}
```

### 2. Do Your Work
Implement the changes described above. Follow existing code patterns and conventions.
Use conventional commits: feat:, fix:, docs:, infra:, refactor:, test:, chore:

### 3. Changelog
Update or create CHANGELOG.md in Keep a Changelog format. Add your changes under [Unreleased].

### 4. Commit and Push
```bash
git add -A
git commit -m "feat: <description>

Closes #{story.issue}

Co-Authored-By: {story.agent} <{story.agent}@wasteland.dev>"
git push -u origin {branch_name}
```

### 5. Create Pull Request
Create a PR using gh or the Gitea API. The PR title should reference the issue.
```bash
gh pr create --repo {story.repo} --title "feat: {story.title}" --body "Closes #{story.issue}

## Summary
<describe changes>

## Test Plan
<how to verify>

Agent: {story.agent} | Sprint: {self.manifest.sprint}"
```
If gh doesn't work with Gitea, use curl with the Gitea API:
```bash
source ~/.claude/lib/gitea-api.sh
gitea_post "repos/{story.repo}/pulls" '{{"title":"feat: {story.title}","head":"{branch_name}","base":"main","body":"Closes #{story.issue}\\n\\nAgent: {story.agent}"}}'
```

### 6. Request Review
After creating the PR, add a comment mentioning @claude for automated review:
```bash
# If the repo has claude-review action, it triggers on @claude mention
gitea_post "repos/{story.repo}/issues/<PR_NUMBER>/comments" '{{"body":"@claude please review this PR"}}'
```

### 7. Agent Protocol
```bash
source ~/.claude/lib/agent-status.sh
source ~/.claude/lib/gitea-api.sh
source ~/.claude/lib/agent-tx.sh
export CLAUDE_AGENT_NAME={story.agent}
agent_status_update "working" "{story.title}" "{story.repo}" {story.issue or 0}
tx_begin "{story.title}" "Sprint: {self.manifest.sprint}, Issue #{story.issue}" "{story.repo}" {story.issue or 0}
```
When done:
```bash
tx_end "success" "Brief summary of what was done"
agent_status_update "idle" "Completed {story.id}"
```
""")
        return "\n".join(parts)

    def _get_updater(self, story: Story) -> Optional[GiteaUpdater]:
        """Get the Gitea updater for a story's repo."""
        return self._gitea_updaters.get(story.repo) or self.gitea

    def _spawn_agent(self, story: Story) -> AgentProcess:
        """Spawn a single claude -p agent in the story's repo directory."""
        prompt = self._build_prompt(story)
        output_dir = Path("logs")
        output_dir.mkdir(exist_ok=True)
        output_file = str(output_dir / f"{story.id.replace('#', '')}-{story.agent}.log")

        repo_path = self._resolve_repo_path(story)
        cmd = [
            CLAUDE_BIN, "-p", prompt,
            "--output-format", "text",
            "--dangerously-skip-permissions",
        ]

        print(f"[swarm] Spawning {story.agent} for {story.id}: {story.title}")
        print(f"[swarm]   repo: {story.repo} -> {repo_path}")

        updater = self._get_updater(story)
        if updater and not self.dry_run:
            try:
                updater.on_story_started(story)
            except Exception as e:
                print(f"[swarm] Warning: Gitea update failed: {e}")

        if self.dry_run:
            print(f"[swarm]   DRY RUN: would run: claude -p '<prompt>' > {output_file}")
            return AgentProcess(story=story, state="done")

        # Strip CLAUDECODE env var so nested claude -p sessions can launch
        # Ensure node is on PATH (nvm may not be sourced in subprocess)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        node_dirs = [
            os.path.expanduser("~/.nvm/versions/node/v25.1.0/bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
        ]
        current_path = env.get("PATH", "")
        for d in node_dirs:
            if d not in current_path:
                current_path = f"{d}:{current_path}"
        env["PATH"] = current_path

        with open(output_file, "w") as out:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=repo_path,
                env=env,
            )

        ap = AgentProcess(
            story=story,
            process=proc,
            pid=proc.pid,
            state="running",
            output_file=output_file,
        )

        # Update scoreboard
        self._update_scoreboard()

        return ap

    def _check_agent(self, story_id: str) -> None:
        """Check if an agent process has completed."""
        ap = self.agents[story_id]
        if ap.state != "running" or ap.process is None:
            return

        ret = ap.process.poll()
        if ret is not None:
            ap.exit_code = ret
            updater = self._get_updater(ap.story)
            if ret == 0:
                ap.state = "done"
                self.completed.add(story_id)
                print(f"[swarm] {story_id} completed successfully")
                if updater:
                    try:
                        updater.on_story_completed(ap.story)
                    except Exception as e:
                        print(f"[swarm] Warning: Gitea close failed: {e}")
            else:
                ap.state = "failed"
                self.failed.add(story_id)
                print(f"[swarm] {story_id} FAILED (exit code {ret})")
                if updater:
                    try:
                        updater.on_story_failed(ap.story, f"exit code {ret}")
                    except Exception as e:
                        print(f"[swarm] Warning: Gitea update failed: {e}")
            self._update_scoreboard()

    def _update_scoreboard(self) -> None:
        """Write a live scoreboard markdown file."""
        from datetime import datetime

        lines = [
            f"# Sprint Scoreboard: {self.manifest.sprint}",
            f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n",
            f"**Total:** {len(self.manifest.stories)} stories | "
            f"**Done:** {len(self.completed)} | "
            f"**Failed:** {len(self.failed)} | "
            f"**Running:** {self._running_count()} | "
            f"**Pending:** {len(self.manifest.stories) - len(self.completed) - len(self.failed) - self._running_count()}\n",
        ]

        # Agent leaderboard
        agent_stats: dict[str, dict] = {}
        for story in self.manifest.stories:
            if story.agent not in agent_stats:
                agent_stats[story.agent] = {"done": 0, "failed": 0, "running": 0, "pending": 0, "stories": []}
            state = "pending"
            if story.id in self.completed:
                state = "done"
                agent_stats[story.agent]["done"] += 1
            elif story.id in self.failed:
                state = "failed"
                agent_stats[story.agent]["failed"] += 1
            elif story.id in self.agents and self.agents[story.id].state == "running":
                state = "running"
                agent_stats[story.agent]["running"] += 1
            else:
                agent_stats[story.agent]["pending"] += 1
            agent_stats[story.agent]["stories"].append((story, state))

        lines.append("## Agent Leaderboard\n")
        lines.append("| Agent | Done | Running | Failed | Pending |")
        lines.append("|-------|------|---------|--------|---------|")
        for agent, stats in sorted(agent_stats.items(), key=lambda x: -x[1]["done"]):
            lines.append(f"| {agent} | {stats['done']} | {stats['running']} | {stats['failed']} | {stats['pending']} |")

        lines.append("\n## Stories\n")
        lines.append("| Story | Repo | Agent | Status |")
        lines.append("|-------|------|-------|--------|")
        for story in self.manifest.stories:
            if story.id in self.completed:
                status = "Done"
            elif story.id in self.failed:
                status = "FAILED"
            elif story.id in self.agents and self.agents[story.id].state == "running":
                status = "Running..."
            else:
                status = "Pending"
            repo_short = story.repo.split("/")[-1] if story.repo else ""
            lines.append(f"| {story.id}: {story.title[:50]} | {repo_short} | {story.agent} | {status} |")

        Path(SCOREBOARD_FILE).write_text("\n".join(lines) + "\n")

    def _ready_stories(self) -> list[Story]:
        """Find stories whose dependencies are met and haven't started."""
        started = set(self.agents.keys())
        ready = []
        for story in self.manifest.stories:
            if story.id in started:
                continue
            if story.id in self.failed:
                continue
            # Check all deps are completed
            if all(d in self.completed for d in story.depends_on):
                ready.append(story)
        return ready

    def _running_count(self) -> int:
        """Count currently running agents."""
        return sum(1 for ap in self.agents.values() if ap.state == "running")

    def run(self) -> bool:
        """Execute the full sprint dispatch loop.

        Returns True if all stories completed successfully.
        """
        print(f"[swarm] Starting sprint: {self.manifest.sprint}")
        print(f"[swarm] {len(self.manifest.stories)} stories, max {self.manifest.max_parallel} parallel")

        # Detect and resolve file ownership conflicts
        conflicts = detect_conflicts(self.manifest)
        if conflicts:
            print_conflicts(conflicts)
            apply_serialization(self.manifest, conflicts)
            print("[swarm] Serialization edges added to prevent conflicts")

        if self.dry_run:
            print("\n[swarm] === DRY RUN — Execution Plan ===")
            for i, layer in enumerate(self.manifest.dependency_order()):
                print(f"\nLayer {i} (parallel):")
                for s in layer:
                    deps = f" (after {', '.join(s.depends_on)})" if s.depends_on else ""
                    print(f"  {s.id}: {s.title} -> {s.agent}{deps}")
            print("\n[swarm] === End Plan ===")
            # Still spawn in dry-run to show what would happen
            for story in self.manifest.stories:
                ap = self._spawn_agent(story)
                self.agents[story.id] = ap
                self.completed.add(story.id)
            return True

        health_monitor = HealthMonitor(self)
        health_check_counter = 0

        while not self._shutdown:
            # Check running agents
            for story_id in list(self.agents.keys()):
                self._check_agent(story_id)

            # Periodic health monitoring (every 3rd poll)
            health_check_counter += 1
            if health_check_counter % 3 == 0:
                issues = health_monitor.check_all()
                if issues:
                    print_health_report(issues)
                    for issue in issues:
                        if issue.severity == "critical":
                            health_monitor.attempt_recovery(issue)

            # Check if we're done
            total = len(self.manifest.stories)
            done = len(self.completed) + len(self.failed)
            if done >= total:
                break

            # Spawn ready stories up to max_parallel
            ready = self._ready_stories()
            running = self._running_count()
            slots = self.manifest.max_parallel - running

            for story in ready[:slots]:
                ap = self._spawn_agent(story)
                self.agents[story.id] = ap

            time.sleep(POLL_INTERVAL)

        # Final summary
        print(f"\n[swarm] === Sprint Summary ===")
        print(f"  Completed: {len(self.completed)}/{len(self.manifest.stories)}")
        if self.failed:
            print(f"  Failed: {', '.join(self.failed)}")
        for story_id, ap in self.agents.items():
            status = "OK" if ap.state == "done" else ap.state.upper()
            print(f"  {story_id}: {ap.story.title} [{status}]")

        # Final scoreboard
        self._update_scoreboard()
        print(f"  Scoreboard: {SCOREBOARD_FILE}")

        # Post final sprint status to Gitea (per-repo)
        if not self.dry_run:
            for repo, updater in self._gitea_updaters.items():
                try:
                    # Filter manifest to this repo's stories for the status post
                    updater.post_sprint_status(self.manifest, self.completed, self.failed)
                except Exception as e:
                    print(f"[swarm] Warning: Gitea sprint status for {repo} failed: {e}")

        return len(self.failed) == 0 and not self._shutdown


def show_status() -> None:
    """Display current agent statuses."""
    agents = list_agents()
    if not agents:
        print("No active agents.")
        return
    print(f"{'Agent':<20} {'State':<12} {'Task':<40} {'Stale'}")
    print("-" * 80)
    for a in agents:
        stale = "STALE" if a.get("stale") else ""
        alive = "" if a.get("process_alive", True) else " (dead)"
        print(f"{a.get('agent', '?'):<20} {a.get('state', '?'):<12} {a.get('task', '')[:40]:<40} {stale}{alive}")


def main():
    parser = argparse.ArgumentParser(description="Swarm dispatcher for sprint execution")
    parser.add_argument("manifest", nargs="?", help="Path to sprint.yaml manifest")
    parser.add_argument("--status", action="store_true", help="Show current agent statuses")
    parser.add_argument("--dry-run", action="store_true", help="Show execution plan without spawning")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not args.manifest:
        parser.error("manifest file required (or use --status)")

    manifest = SprintManifest.from_yaml(args.manifest)
    dispatcher = Dispatcher(manifest, dry_run=args.dry_run)
    success = dispatcher.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
