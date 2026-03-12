#!/usr/bin/env python3
"""Swarm dispatcher — the brain of the orchestrator.

Reads a phase manifest, builds a dependency DAG, spawns `claude -p` agents
in worktrees, and monitors their progress via status files.

Usage:
    python3 swarm.py phase.yaml                # Launch the swarm
    python3 swarm.py phase.yaml --dry-run      # Show execution plan
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
from lib.manifest import PhaseManifest, Task
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

    task: Task
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    state: str = "pending"  # pending | running | done | failed
    exit_code: Optional[int] = None
    output_file: Optional[str] = None


class Dispatcher:
    """Spawns and manages agent processes from a phase manifest."""

    def __init__(self, manifest: PhaseManifest, dry_run: bool = False):
        self.manifest = manifest
        self.dry_run = dry_run
        self.agents: dict[str, AgentProcess] = {}
        self.completed: set[str] = set()
        self.failed: set[str] = set()
        self._shutdown = False

        # Multi-repo: create per-repo updaters
        self._gitea_updaters: dict[str, GiteaUpdater] = {}
        repos = set(s.repo for s in manifest.tasks if s.repo)
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
        for task_id, ap in self.agents.items():
            if ap.process and ap.process.poll() is None:
                print(f"[swarm] Terminating {task_id} (PID {ap.pid})")
                ap.process.terminate()
                try:
                    ap.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ap.process.kill()

    def _resolve_repo_path(self, task: Task) -> str:
        """Resolve the local filesystem path for a task's repository."""
        return REPO_PATHS.get(task.repo, os.path.expanduser(f"~/projects/{task.repo.split('/')[-1]}"))

    def _build_prompt(self, task: Task) -> str:
        """Build the prompt for a claude -p agent with worktree and PR instructions."""
        repo_path = self._resolve_repo_path(task)
        branch_name = f"feat/issue-{task.issue}-{task.title.lower()[:30].replace(' ', '-').rstrip('-')}"
        worktree_dir = f"{repo_path}/.worktrees/{branch_name}"

        parts = [
            f"You are agent '{task.agent}' working on: {task.title}",
            f"Repository: {task.repo}",
            f"Local repo path: {repo_path}",
        ]
        if task.issue:
            parts.append(f"Gitea issue: #{task.issue}")
        if task.files:
            parts.append(f"Key files: {', '.join(task.files)}")
        if task.prompt:
            parts.append(f"\nTask details:\n{task.prompt}")

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

Closes #{task.issue}

Co-Authored-By: {task.agent} <{task.agent}@wasteland.dev>"
git push -u origin {branch_name}
```

### 5. Create Pull Request
Create a PR using gh or the Gitea API. The PR title should reference the issue.
```bash
gh pr create --repo {task.repo} --title "feat: {task.title}" --body "Closes #{task.issue}

## Summary
<describe changes>

## Test Plan
<how to verify>

Agent: {task.agent} | Phase: {self.manifest.phase}"
```
If gh doesn't work with Gitea, use curl with the Gitea API:
```bash
source ~/.claude/lib/gitea-api.sh
gitea_post "repos/{task.repo}/pulls" '{{"title":"feat: {task.title}","head":"{branch_name}","base":"main","body":"Closes #{task.issue}\\n\\nAgent: {task.agent}"}}'
```

### 6. Request Review
After creating the PR, add a comment mentioning @claude for automated review:
```bash
# If the repo has claude-review action, it triggers on @claude mention
gitea_post "repos/{task.repo}/issues/<PR_NUMBER>/comments" '{{"body":"@claude please review this PR"}}'
```

### 7. Agent Protocol
```bash
source ~/.claude/lib/agent-status.sh
source ~/.claude/lib/gitea-api.sh
source ~/.claude/lib/agent-tx.sh
export CLAUDE_AGENT_NAME={task.agent}
agent_status_update "working" "{task.title}" "{task.repo}" {task.issue or 0}
tx_begin "{task.title}" "Phase: {self.manifest.phase}, Issue #{task.issue}" "{task.repo}" {task.issue or 0}
```
When done:
```bash
tx_end "success" "Brief summary of what was done"
agent_status_update "idle" "Completed {task.id}"
```
""")
        return "\n".join(parts)

    def _get_updater(self, task: Task) -> Optional[GiteaUpdater]:
        """Get the Gitea updater for a task's repo."""
        return self._gitea_updaters.get(task.repo) or self.gitea

    def _spawn_agent(self, task: Task) -> AgentProcess:
        """Spawn a single claude -p agent in the task's repo directory."""
        prompt = self._build_prompt(task)
        output_dir = Path("logs")
        output_dir.mkdir(exist_ok=True)
        output_file = str(output_dir / f"{task.id.replace('#', '')}-{task.agent}.log")

        repo_path = self._resolve_repo_path(task)
        cmd = [
            CLAUDE_BIN, "-p", prompt,
            "--output-format", "text",
            "--dangerously-skip-permissions",
        ]

        print(f"[swarm] Spawning {task.agent} for {task.id}: {task.title}")
        print(f"[swarm]   repo: {task.repo} -> {repo_path}")

        updater = self._get_updater(task)
        if updater and not self.dry_run:
            try:
                updater.on_task_started(task)
            except Exception as e:
                print(f"[swarm] Warning: Gitea update failed: {e}")

        if self.dry_run:
            print(f"[swarm]   DRY RUN: would run: claude -p '<prompt>' > {output_file}")
            return AgentProcess(task=task, state="done")

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
            task=task,
            process=proc,
            pid=proc.pid,
            state="running",
            output_file=output_file,
        )

        # Update scoreboard
        self._update_scoreboard()

        return ap

    def _check_agent(self, task_id: str) -> None:
        """Check if an agent process has completed."""
        ap = self.agents[task_id]
        if ap.state != "running" or ap.process is None:
            return

        ret = ap.process.poll()
        if ret is not None:
            ap.exit_code = ret
            updater = self._get_updater(ap.task)
            if ret == 0:
                ap.state = "done"
                self.completed.add(task_id)
                print(f"[swarm] {task_id} completed successfully")
                if updater:
                    try:
                        updater.on_task_completed(ap.task)
                    except Exception as e:
                        print(f"[swarm] Warning: Gitea close failed: {e}")
            else:
                ap.state = "failed"
                self.failed.add(task_id)
                print(f"[swarm] {task_id} FAILED (exit code {ret})")
                if updater:
                    try:
                        updater.on_task_failed(ap.task, f"exit code {ret}")
                    except Exception as e:
                        print(f"[swarm] Warning: Gitea update failed: {e}")
            self._update_scoreboard()

    def _update_scoreboard(self) -> None:
        """Write a live scoreboard markdown file."""
        from datetime import datetime

        lines = [
            f"# Phase Scoreboard: {self.manifest.phase}",
            f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n",
            f"**Total:** {len(self.manifest.tasks)} tasks | "
            f"**Done:** {len(self.completed)} | "
            f"**Failed:** {len(self.failed)} | "
            f"**Running:** {self._running_count()} | "
            f"**Pending:** {len(self.manifest.tasks) - len(self.completed) - len(self.failed) - self._running_count()}\n",
        ]

        # Agent leaderboard
        agent_stats: dict[str, dict] = {}
        for task in self.manifest.tasks:
            if task.agent not in agent_stats:
                agent_stats[task.agent] = {"done": 0, "failed": 0, "running": 0, "pending": 0, "tasks": []}
            state = "pending"
            if task.id in self.completed:
                state = "done"
                agent_stats[task.agent]["done"] += 1
            elif task.id in self.failed:
                state = "failed"
                agent_stats[task.agent]["failed"] += 1
            elif task.id in self.agents and self.agents[task.id].state == "running":
                state = "running"
                agent_stats[task.agent]["running"] += 1
            else:
                agent_stats[task.agent]["pending"] += 1
            agent_stats[task.agent]["tasks"].append((task, state))

        lines.append("## Agent Leaderboard\n")
        lines.append("| Agent | Done | Running | Failed | Pending |")
        lines.append("|-------|------|---------|--------|---------|")
        for agent, stats in sorted(agent_stats.items(), key=lambda x: -x[1]["done"]):
            lines.append(f"| {agent} | {stats['done']} | {stats['running']} | {stats['failed']} | {stats['pending']} |")

        lines.append("\n## Tasks\n")
        lines.append("| Task | Repo | Agent | Status |")
        lines.append("|-------|------|-------|--------|")
        for task in self.manifest.tasks:
            if task.id in self.completed:
                status = "Done"
            elif task.id in self.failed:
                status = "FAILED"
            elif task.id in self.agents and self.agents[task.id].state == "running":
                status = "Running..."
            else:
                status = "Pending"
            repo_short = task.repo.split("/")[-1] if task.repo else ""
            lines.append(f"| {task.id}: {task.title[:50]} | {repo_short} | {task.agent} | {status} |")

        Path(SCOREBOARD_FILE).write_text("\n".join(lines) + "\n")

    def _ready_tasks(self) -> list[Task]:
        """Find tasks whose dependencies are met and haven't started."""
        started = set(self.agents.keys())
        ready = []
        for task in self.manifest.tasks:
            if task.id in started:
                continue
            if task.id in self.failed:
                continue
            # Check all deps are completed
            if all(d in self.completed for d in task.depends_on):
                ready.append(task)
        return ready

    def _running_count(self) -> int:
        """Count currently running agents."""
        return sum(1 for ap in self.agents.values() if ap.state == "running")

    def run(self) -> bool:
        """Execute the full phase dispatch loop.

        Returns True if all tasks completed successfully.
        """
        print(f"[swarm] Starting phase: {self.manifest.phase}")
        print(f"[swarm] {len(self.manifest.tasks)} tasks, max {self.manifest.max_parallel} parallel")

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
            for task in self.manifest.tasks:
                ap = self._spawn_agent(task)
                self.agents[task.id] = ap
                self.completed.add(task.id)
            return True

        health_monitor = HealthMonitor(self)
        health_check_counter = 0

        while not self._shutdown:
            # Check running agents
            for task_id in list(self.agents.keys()):
                self._check_agent(task_id)

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
            total = len(self.manifest.tasks)
            done = len(self.completed) + len(self.failed)
            if done >= total:
                break

            # Spawn ready tasks up to max_parallel
            ready = self._ready_tasks()
            running = self._running_count()
            slots = self.manifest.max_parallel - running

            for task in ready[:slots]:
                ap = self._spawn_agent(task)
                self.agents[task.id] = ap

            time.sleep(POLL_INTERVAL)

        # Final summary
        print(f"\n[swarm] === Phase Summary ===")
        print(f"  Completed: {len(self.completed)}/{len(self.manifest.tasks)}")
        if self.failed:
            print(f"  Failed: {', '.join(self.failed)}")
        for task_id, ap in self.agents.items():
            status = "OK" if ap.state == "done" else ap.state.upper()
            print(f"  {task_id}: {ap.task.title} [{status}]")

        # Final scoreboard
        self._update_scoreboard()
        print(f"  Scoreboard: {SCOREBOARD_FILE}")

        # Post final phase status to Gitea (per-repo)
        if not self.dry_run:
            for repo, updater in self._gitea_updaters.items():
                try:
                    # Filter manifest to this repo's tasks for the status post
                    updater.post_phase_status(self.manifest, self.completed, self.failed)
                except Exception as e:
                    print(f"[swarm] Warning: Gitea phase status for {repo} failed: {e}")

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
    parser = argparse.ArgumentParser(description="Swarm dispatcher for phase execution")
    parser.add_argument("manifest", nargs="?", help="Path to phase.yaml manifest")
    parser.add_argument("--status", action="store_true", help="Show current agent statuses")
    parser.add_argument("--dry-run", action="store_true", help="Show execution plan without spawning")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not args.manifest:
        parser.error("manifest file required (or use --status)")

    manifest = PhaseManifest.from_yaml(args.manifest)
    dispatcher = Dispatcher(manifest, dry_run=args.dry_run)
    success = dispatcher.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
