#!/usr/bin/env python3
"""Swarm dispatcher — the brain of the orchestrator.

Pipeline:
    1. Read manifest (sprint.yaml)
    2. PLAN PHASE — spawn planner agents per project (read-only, produce plans)
    3. TEAM PHASE — spawn dev-leads per project with agent teams enabled
    4. Dev-leads create agent teams, delegate sub-tasks, monitor, unblock

Usage:
    python3 swarm.py sprint.yaml                # Full pipeline: plan + dispatch
    python3 swarm.py sprint.yaml --dry-run      # Show plan without executing
    python3 swarm.py sprint.yaml --skip-plan    # Skip planning, dispatch directly
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
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.agent_status import AgentStatus, list_agents
from lib.conflict import detect_conflicts, apply_serialization, print_conflicts
from lib.manifest import PhaseManifest, Task
from lib.gitea_updates import GiteaUpdater
from lib.monitor import HealthMonitor, print_health_report
from lib.planner import PlanPhase, ProjectPlan, ReplanRequest, REPO_PATHS


STATUS_DIR = os.path.expanduser("~/.claude/agents/status")
POLL_INTERVAL = 10  # seconds between status checks
REPLAN_CHECK_INTERVAL = 6  # check for replans every 6th poll (60s)
SCOREBOARD_FILE = "scoreboard.md"
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")


@dataclass
class DevLeadProcess:
    """Tracks a running dev-lead session (one per project)."""

    repo: str
    tasks: list[Task]
    plan: Optional[ProjectPlan] = None
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    state: str = "pending"  # pending | running | done | failed
    exit_code: Optional[int] = None
    output_file: Optional[str] = None


# Keep legacy AgentProcess for backward compat with health monitor
@dataclass
class AgentProcess:
    """Tracks a running agent process (legacy compat)."""

    task: Task
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    state: str = "pending"
    exit_code: Optional[int] = None
    output_file: Optional[str] = None


def _clean_env() -> dict[str, str]:
    """Build a clean environment for spawning Claude sessions."""
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
    # Enable agent teams for dev-leads
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
    return env


class Dispatcher:
    """Orchestrates the full sprint pipeline: plan -> dispatch dev-leads."""

    def __init__(
        self,
        manifest: PhaseManifest,
        dry_run: bool = False,
        skip_plan: bool = False,
    ):
        self.manifest = manifest
        self.dry_run = dry_run
        self.skip_plan = skip_plan
        self.dev_leads: dict[str, DevLeadProcess] = {}
        self.completed: set[str] = set()  # repo keys
        self.failed: set[str] = set()  # repo keys
        self._shutdown = False
        self._plans: dict[str, ProjectPlan] = {}

        # Legacy compat: agents dict for health monitor
        self.agents: dict[str, AgentProcess] = {}

        # Multi-repo updaters
        self._gitea_updaters: dict[str, GiteaUpdater] = {}
        repos = set(s.repo for s in manifest.tasks if s.repo)
        for repo in repos:
            self._gitea_updaters[repo] = GiteaUpdater(repo)
        self.gitea = GiteaUpdater(manifest.repo) if manifest.repo else None

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        print(f"\n[swarm] Received signal {signum}, shutting down...")
        self._shutdown = True
        self._kill_all()

    def _kill_all(self) -> None:
        """Terminate all running dev-lead processes."""
        for repo, dl in self.dev_leads.items():
            if dl.process and dl.process.poll() is None:
                print(f"[swarm] Terminating dev-lead for {repo} (PID {dl.pid})")
                dl.process.terminate()
                try:
                    dl.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    dl.process.kill()

    def _group_by_repo(self) -> dict[str, list[Task]]:
        """Group manifest tasks by repository."""
        groups: dict[str, list[Task]] = {}
        for task in self.manifest.tasks:
            repo = task.repo or self.manifest.repo
            if repo not in groups:
                groups[repo] = []
            groups[repo].append(task)
        return groups

    # ── Planning Phase ─────────────────────────────────────────────

    def plan_phase(self) -> dict[str, ProjectPlan]:
        """Run the planning phase — spawn planner agents per project."""
        if self.skip_plan:
            print("[swarm] Skipping planning phase (--skip-plan)")
            return {}

        print("\n[swarm] ═══ PLANNING PHASE ═══")
        planner = PlanPhase(self.manifest, dry_run=self.dry_run)
        self._plans = planner.run()
        print(f"[swarm] Planning complete: {len(self._plans)} project(s) planned")
        return self._plans

    # ── Dev-Lead Prompt ────────────────────────────────────────────

    def _build_dev_lead_prompt(
        self, repo: str, tasks: list[Task], plan: Optional[ProjectPlan]
    ) -> str:
        """Build the prompt for a dev-lead with agent teams."""
        repo_path = REPO_PATHS.get(
            repo, os.path.expanduser(f"~/projects/{repo.split('/')[-1]}")
        )
        repo_short = repo.split("/")[-1]

        # Story summaries
        story_block = ""
        for task in tasks:
            story_block += f"\n### {task.id}: {task.title}\n"
            if task.issue:
                story_block += f"Issue: #{task.issue}\n"
            if task.prompt:
                story_block += f"{task.prompt[:500]}\n"

        # Plan block
        plan_block = "No detailed plan available. Use your judgment to break stories into tasks."
        if plan:
            plan_block = json.dumps(plan.to_dict(), indent=2)

        # Agent roster from manifest
        agents = list(set(t.agent for t in tasks))
        agent_list = ", ".join(agents) if agents else "general-purpose developers"

        return f"""You are the Dev Team Lead for {repo_short}.
You have {len(tasks)} stories to deliver this sprint.
Repository path: {repo_path}

## YOUR ROLE — DELEGATION ONLY

You are a coordinator, NOT an implementer. Your job:
1. Create an agent team with teammates
2. Delegate ALL work through the task list
3. Monitor teammates — check progress regularly
4. Unblock stuck teammates — provide context, resolve conflicts
5. If a plan is insufficient, submit a replan request (see below)
6. After all tasks complete, verify and clean up the team

You MUST NOT write code yourself. Delegate everything.

## Your Sprint Stories
{story_block}

## Implementation Plan (from planning stage)

```json
{plan_block}
```

## Agent Team Instructions

Create an agent team with 3-5 teammates. Suggested roles based on manifest:
{agent_list}

For each teammate:
- Spawn with a clear prompt describing their assigned sub-tasks
- Require plan approval before they implement (tell the team lead to review plans)
- Each teammate works in their own git worktree:
  ```
  git worktree add .worktrees/issue-N-description -b feat/issue-N-description origin/_dev
  ```
- Teammates must NOT edit the same files

Target 5-6 tasks per teammate. Use the sub-tasks from the plan above to create your task list.

## Workflow

1. Review the plan above. If it's too vague or wrong, submit a replan request.
2. Create your agent team: "Create an agent team with N teammates..."
3. Create the task list from the plan's sub-tasks
4. Assign tasks to teammates (or let them self-claim)
5. Monitor progress — use Shift+Down to check on teammates
6. When a teammate finishes: review their work
7. After all tasks: verify, merge PRs to _dev, dispatch docs agent
8. Clean up the team

## Replan Feedback Loop

If a plan is insufficient (too vague, wrong approach, missing info):

1. Write the reason and what questions you need answered
2. Create a replan request file:
```bash
mkdir -p ~/.claude/state/replan-queue
cat > ~/.claude/state/replan-queue/replan-{repo_short}-ISSUE-$(date +%s).json << 'REPLAN'
{{
  "story_issue": ISSUE_NUMBER,
  "repo": "{repo}",
  "sprint_id": "{self.manifest.phase}",
  "reason": "Why the plan is insufficient",
  "what_was_attempted": "What was tried and failed",
  "questions_for_planner": ["Specific question 1", "Specific question 2"]
}}
REPLAN
```
3. Pause that task and work on other stories while replanning happens
4. The orchestrator will detect the request and run a focused replan

## Git & PR Conventions

- Feature branches: `feat/issue-N-description` targeting `_dev`
- Conventional commits: feat:, fix:, docs:, refactor:, test:
- Every PR must reference the issue: title includes `(#N)`, body includes `Closes #N`
- PRs target `_dev` branch (NOT main)
- After review passes, merge to `_dev`
- Co-Authored-By header on all commits

## Agent Protocol

```bash
source ~/.claude/lib/agent-status.sh
source ~/.claude/lib/gitea-api.sh
source ~/.claude/lib/agent-tx.sh
export CLAUDE_AGENT_NAME="dev-lead-{repo_short}"
agent_status_update "working" "Leading sprint for {repo_short}" "{repo}"
```

When done:
```bash
agent_status_update "idle" "Sprint complete for {repo_short}"
```
"""

    # ── Dev-Lead Spawn ─────────────────────────────────────────────

    def _spawn_dev_lead(self, repo: str, tasks: list[Task]) -> DevLeadProcess:
        """Spawn a dev-lead session with agent teams enabled for one project."""
        plan = self._plans.get(repo)
        prompt = self._build_dev_lead_prompt(repo, tasks, plan)

        output_dir = Path("logs")
        output_dir.mkdir(exist_ok=True)
        repo_short = repo.split("/")[-1]
        output_file = str(output_dir / f"dev-lead-{repo_short}.log")

        repo_path = REPO_PATHS.get(
            repo, os.path.expanduser(f"~/projects/{repo.split('/')[-1]}")
        )

        print(f"[swarm] Spawning dev-lead for {repo} ({len(tasks)} stories)")
        if plan:
            total_subtasks = sum(len(s.sub_tasks) for s in plan.stories)
            print(f"[swarm]   Plan: {len(plan.stories)} stories, {total_subtasks} sub-tasks")
        else:
            print(f"[swarm]   No plan available — dev-lead will improvise")

        updater = self._gitea_updaters.get(repo) or self.gitea
        if updater and not self.dry_run:
            for task in tasks:
                try:
                    updater.on_task_started(task)
                except Exception as e:
                    print(f"[swarm] Warning: Gitea update failed for {task.id}: {e}")

        if self.dry_run:
            print(f"[swarm]   DRY RUN: would spawn dev-lead with agent teams")
            print(f"[swarm]   Stories: {', '.join(t.id for t in tasks)}")
            return DevLeadProcess(repo=repo, tasks=tasks, plan=plan, state="done")

        # Spawn claude -p with agent teams enabled
        cmd = [
            CLAUDE_BIN,
            "-p",
            prompt,
            "--output-format", "text",
            "--dangerously-skip-permissions",
            "--teammate-mode", "in-process",
        ]

        env = _clean_env()

        with open(output_file, "w") as out:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=repo_path,
                env=env,
            )

        dl = DevLeadProcess(
            repo=repo,
            tasks=tasks,
            plan=plan,
            process=proc,
            pid=proc.pid,
            state="running",
            output_file=output_file,
        )

        self._update_scoreboard()
        return dl

    # ── Legacy Agent Spawn (kept for backward compat) ──────────────

    def _spawn_agent(self, task: Task) -> AgentProcess:
        """Spawn a single agent directly (legacy mode, used with --skip-plan)."""
        repo_path = REPO_PATHS.get(
            task.repo,
            os.path.expanduser(f"~/projects/{task.repo.split('/')[-1]}"),
        )
        branch_name = (
            f"feat/issue-{task.issue}-"
            f"{task.title.lower()[:30].replace(' ', '-').rstrip('-')}"
        )
        worktree_dir = f"{repo_path}/.worktrees/{branch_name}"

        prompt = f"""You are agent '{task.agent}' working on: {task.title}
Repository: {task.repo}
Local repo path: {repo_path}

{'Issue: #' + str(task.issue) if task.issue else ''}
{'Key files: ' + ', '.join(task.files) if task.files else ''}

{task.prompt if task.prompt else ''}

## MANDATORY WORKFLOW

### 1. Worktree Isolation
cd {repo_path} && git fetch origin
git worktree add {worktree_dir} -b {branch_name} origin/_dev
cd {worktree_dir}

### 2. Implement, commit (conventional commits), push, create PR targeting _dev
### 3. Update CHANGELOG.md
### 4. Wait for claude-review, address feedback
### 5. Agent protocol: source libs, status updates, transactions
"""

        output_dir = Path("logs")
        output_dir.mkdir(exist_ok=True)
        output_file = str(
            output_dir / f"{task.id.replace('#', '')}-{task.agent}.log"
        )

        cmd = [
            CLAUDE_BIN, "-p", prompt,
            "--output-format", "text",
            "--dangerously-skip-permissions",
        ]

        print(f"[swarm] Spawning {task.agent} for {task.id}: {task.title}")

        if self.dry_run:
            return AgentProcess(task=task, state="done")

        env = _clean_env()
        with open(output_file, "w") as out:
            proc = subprocess.Popen(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=repo_path,
                env=env,
            )

        return AgentProcess(
            task=task, process=proc, pid=proc.pid,
            state="running", output_file=output_file,
        )

    # ── Monitoring ─────────────────────────────────────────────────

    def _check_dev_lead(self, repo: str) -> None:
        """Check if a dev-lead process has completed."""
        dl = self.dev_leads[repo]
        if dl.state != "running" or dl.process is None:
            return

        ret = dl.process.poll()
        if ret is not None:
            dl.exit_code = ret
            updater = self._gitea_updaters.get(repo) or self.gitea
            if ret == 0:
                dl.state = "done"
                self.completed.add(repo)
                print(f"[swarm] Dev-lead for {repo} completed successfully")
                if updater:
                    for task in dl.tasks:
                        try:
                            updater.on_task_completed(task)
                        except Exception as e:
                            print(f"[swarm] Warning: update failed for {task.id}: {e}")
            else:
                dl.state = "failed"
                self.failed.add(repo)
                print(f"[swarm] Dev-lead for {repo} FAILED (exit code {ret})")
                if updater:
                    for task in dl.tasks:
                        try:
                            updater.on_task_failed(task, f"dev-lead exit code {ret}")
                        except Exception as e:
                            print(f"[swarm] Warning: update failed for {task.id}: {e}")
            self._update_scoreboard()

    def _check_replan_queue(self) -> None:
        """Check for replan requests from dev-leads and process them."""
        replans = ReplanRequest.pending()
        if not replans:
            return

        for replan in replans:
            print(f"[swarm] Replan request for {replan.repo} issue #{replan.story_issue}")
            print(f"[swarm]   Reason: {replan.reason}")

            # Find the affected tasks
            tasks = [
                t for t in self.manifest.tasks
                if t.repo == replan.repo
                and t.issue == replan.story_issue
            ]
            if not tasks:
                print(f"[swarm]   WARNING: no matching task found, skipping")
                replan.consume()
                continue

            # Run a focused replan
            from lib.planner import PlanPhase
            mini_manifest = PhaseManifest(
                phase=self.manifest.phase,
                project=replan.repo.split("/")[-1],
                repo=replan.repo,
                tasks=tasks,
                max_parallel=1,
            )
            planner = PlanPhase(mini_manifest, dry_run=self.dry_run)
            # The planner picks up the replan request automatically
            new_plans = planner.run()

            if replan.repo in new_plans:
                self._plans[replan.repo] = new_plans[replan.repo]
                print(f"[swarm]   Replan complete — updated plan saved")
                # Note: the dev-lead needs to detect the new plan file
                # and reload. This happens via file watching or polling.
            else:
                print(f"[swarm]   Replan produced no output")

    # ── Scoreboard ─────────────────────────────────────────────────

    def _update_scoreboard(self) -> None:
        """Write a live scoreboard markdown file."""
        lines = [
            f"# Sprint Scoreboard: {self.manifest.phase}",
            f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n",
        ]

        groups = self._group_by_repo()
        total_projects = len(groups)

        lines.append(
            f"**Projects:** {total_projects} | "
            f"**Done:** {len(self.completed)} | "
            f"**Failed:** {len(self.failed)} | "
            f"**Running:** {sum(1 for dl in self.dev_leads.values() if dl.state == 'running')} | "
            f"**Pending:** {total_projects - len(self.completed) - len(self.failed) - sum(1 for dl in self.dev_leads.values() if dl.state == 'running')}\n"
        )

        lines.append("## Projects\n")
        lines.append("| Project | Stories | Plan | Dev-Lead | Status |")
        lines.append("|---------|---------|------|----------|--------|")

        for repo, tasks in groups.items():
            repo_short = repo.split("/")[-1]
            plan = self._plans.get(repo)
            plan_status = f"{len(plan.stories)} planned" if plan else "No plan"
            dl = self.dev_leads.get(repo)
            if not dl:
                status = "Pending"
            elif dl.state == "running":
                status = "Running..."
            elif dl.state == "done":
                status = "Done"
            elif dl.state == "failed":
                status = "FAILED"
            else:
                status = dl.state
            dl_info = f"PID {dl.pid}" if dl and dl.pid else "—"
            lines.append(
                f"| {repo_short} | {len(tasks)} | {plan_status} | {dl_info} | {status} |"
            )

        lines.append("\n## Stories\n")
        lines.append("| Story | Repo | Agent | Status |")
        lines.append("|-------|------|-------|--------|")
        for task in self.manifest.tasks:
            repo_short = task.repo.split("/")[-1] if task.repo else ""
            dl = self.dev_leads.get(task.repo)
            if dl:
                status = dl.state.capitalize()
            else:
                status = "Pending"
            lines.append(
                f"| {task.id}: {task.title[:50]} | {repo_short} | {task.agent} | {status} |"
            )

        Path(SCOREBOARD_FILE).write_text("\n".join(lines) + "\n")

    def _running_count(self) -> int:
        """Count currently running dev-leads."""
        return sum(1 for dl in self.dev_leads.values() if dl.state == "running")

    # ── Main Run Loop ──────────────────────────────────────────────

    def run(self) -> bool:
        """Execute the full sprint pipeline: plan -> dispatch dev-leads.

        Returns True if all projects completed successfully.
        """
        print(f"[swarm] Starting sprint: {self.manifest.phase}")
        print(f"[swarm] {len(self.manifest.tasks)} stories, "
              f"max {self.manifest.max_parallel} parallel dev-leads")

        # Detect and resolve file ownership conflicts
        conflicts = detect_conflicts(self.manifest)
        if conflicts:
            print_conflicts(conflicts)
            apply_serialization(self.manifest, conflicts)
            print("[swarm] Serialization edges added to prevent conflicts")

        # ── Phase 1: Planning ──────────────────────────────────────
        self.plan_phase()

        # ── Phase 2: Dev-Lead Dispatch ─────────────────────────────
        groups = self._group_by_repo()

        if self.dry_run:
            print("\n[swarm] ═══ DRY RUN — Dispatch Plan ═══")
            for repo, tasks in groups.items():
                plan = self._plans.get(repo)
                print(f"\n  Project: {repo}")
                print(f"    Stories: {len(tasks)}")
                if plan:
                    subtasks = sum(len(s.sub_tasks) for s in plan.stories)
                    print(f"    Plan: {len(plan.stories)} stories, {subtasks} sub-tasks")
                else:
                    print(f"    Plan: none (dev-lead will improvise)")
                for t in tasks:
                    print(f"      {t.id}: {t.title} -> {t.agent}")
            print("\n[swarm] ═══ End Plan ═══")
            return True

        print(f"\n[swarm] ═══ DISPATCH PHASE ═══")
        print(f"[swarm] Spawning {len(groups)} dev-lead(s) with agent teams")

        # Spawn dev-leads up to max_parallel
        repos_to_spawn = list(groups.keys())
        spawn_idx = 0
        replan_counter = 0

        while not self._shutdown:
            # Check running dev-leads
            for repo in list(self.dev_leads.keys()):
                self._check_dev_lead(repo)

            # Periodically check for replan requests
            replan_counter += 1
            if replan_counter % REPLAN_CHECK_INTERVAL == 0:
                self._check_replan_queue()

            # Check if we're done
            total = len(groups)
            done = len(self.completed) + len(self.failed)
            if done >= total:
                break

            # Spawn dev-leads up to max_parallel
            running = self._running_count()
            slots = self.manifest.max_parallel - running

            while slots > 0 and spawn_idx < len(repos_to_spawn):
                repo = repos_to_spawn[spawn_idx]
                if repo not in self.dev_leads:
                    dl = self._spawn_dev_lead(repo, groups[repo])
                    self.dev_leads[repo] = dl
                    slots -= 1
                spawn_idx += 1

            time.sleep(POLL_INTERVAL)

        # ── Final Summary ──────────────────────────────────────────
        print(f"\n[swarm] ═══ Sprint Summary ═══")
        print(f"  Projects: {len(self.completed)}/{len(groups)} completed")
        if self.failed:
            print(f"  Failed: {', '.join(self.failed)}")
        for repo, dl in self.dev_leads.items():
            status = "OK" if dl.state == "done" else dl.state.upper()
            print(f"  {repo}: {len(dl.tasks)} stories [{status}]")

        self._update_scoreboard()
        print(f"  Scoreboard: {SCOREBOARD_FILE}")

        # Post final status
        if not self.dry_run:
            for repo, updater in self._gitea_updaters.items():
                try:
                    updater.post_phase_status(self.manifest, self.completed, self.failed)
                except Exception as e:
                    print(f"[swarm] Warning: status post for {repo} failed: {e}")

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
        print(
            f"{a.get('agent', '?'):<20} {a.get('state', '?'):<12} "
            f"{a.get('task', '')[:40]:<40} {stale}{alive}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Swarm dispatcher — plan + dispatch dev-leads with agent teams"
    )
    parser.add_argument("manifest", nargs="?", help="Path to sprint.yaml manifest")
    parser.add_argument(
        "--status", action="store_true", help="Show current agent statuses"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show execution plan without spawning",
    )
    parser.add_argument(
        "--skip-plan", action="store_true",
        help="Skip planning phase, dispatch dev-leads with raw stories",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not args.manifest:
        parser.error("manifest file required (or use --status)")

    manifest = PhaseManifest.from_yaml(args.manifest)
    dispatcher = Dispatcher(
        manifest, dry_run=args.dry_run, skip_plan=args.skip_plan
    )
    success = dispatcher.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
