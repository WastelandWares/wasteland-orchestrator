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
from lib.monitor import HealthMonitor, print_health_report


STATUS_DIR = os.path.expanduser("~/.claude/agents/status")
POLL_INTERVAL = 10  # seconds between status checks


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

    def _build_prompt(self, story: Story) -> str:
        """Build the prompt for a claude -p agent."""
        parts = [
            f"You are agent '{story.agent}' working on: {story.title}",
            f"Repository: {story.repo}",
        ]
        if story.issue:
            parts.append(f"Gitea issue: #{story.issue}")
        if story.files:
            parts.append(f"Key files: {', '.join(story.files)}")
        if story.prompt:
            parts.append(f"\nTask details:\n{story.prompt}")
        parts.append(
            "\nFollow the agent protocol: source ~/.claude/lib/agent-status.sh && "
            "source ~/.claude/lib/gitea-api.sh && source ~/.claude/lib/agent-tx.sh && "
            f"export CLAUDE_AGENT_NAME={story.agent}"
        )
        return "\n".join(parts)

    def _spawn_agent(self, story: Story) -> AgentProcess:
        """Spawn a single claude -p agent."""
        prompt = self._build_prompt(story)
        output_dir = Path("logs")
        output_dir.mkdir(exist_ok=True)
        output_file = str(output_dir / f"{story.id.replace('#', '')}-{story.agent}.log")

        cmd = [
            "claude", "-p", prompt,
            "--output-format", "text",
        ]

        print(f"[swarm] Spawning {story.agent} for {story.id}: {story.title}")

        if self.dry_run:
            print(f"[swarm]   DRY RUN: would run: claude -p '<prompt>' > {output_file}")
            return AgentProcess(story=story, state="done")

        with open(output_file, "w") as out:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                cwd=os.getcwd(),
            )

        ap = AgentProcess(
            story=story,
            process=proc,
            pid=proc.pid,
            state="running",
            output_file=output_file,
        )
        return ap

    def _check_agent(self, story_id: str) -> None:
        """Check if an agent process has completed."""
        ap = self.agents[story_id]
        if ap.state != "running" or ap.process is None:
            return

        ret = ap.process.poll()
        if ret is not None:
            ap.exit_code = ret
            if ret == 0:
                ap.state = "done"
                self.completed.add(story_id)
                print(f"[swarm] {story_id} completed successfully")
            else:
                ap.state = "failed"
                self.failed.add(story_id)
                print(f"[swarm] {story_id} FAILED (exit code {ret})")

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
