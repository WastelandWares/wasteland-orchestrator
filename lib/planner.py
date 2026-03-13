"""Planning phase — generates implementation plans before dispatch.

Spawns planner agents (claude -p) that read sprint stories and produce
structured implementation plans. Plans are consumed by dev-leads who
use them to create agent team task lists.

The planning phase sits between manifest generation and dev-lead dispatch:
    manifest -> plan_phase() -> dev-lead spawn (with plans)

Usage:
    from lib.planner import PlanPhase, ProjectPlan

    planner = PlanPhase(manifest, dry_run=False)
    plans = planner.run()  # dict[repo, ProjectPlan]
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.manifest import PhaseManifest, Task


PLANS_DIR = os.path.expanduser("~/.claude/state/plans")
REPLAN_QUEUE_DIR = os.path.expanduser("~/.claude/state/replan-queue")
CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
PLANNER_TIMEOUT = 600  # 10 minutes per project


@dataclass
class SubTask:
    """A single sub-task within a story plan."""

    id: str
    description: str
    files: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    estimated_complexity: str = "small"  # trivial/small/medium/large


@dataclass
class StoryPlan:
    """Implementation plan for a single story/issue."""

    issue: int
    title: str
    sub_tasks: list[SubTask] = field(default_factory=list)
    architecture_notes: str = ""
    risks: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)


@dataclass
class ProjectPlan:
    """Complete plan for all stories in a project/repo."""

    sprint: str
    repo: str
    planned_at: str = ""
    stories: list[StoryPlan] = field(default_factory=list)
    planner_output_raw: str = ""

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output."""
        return {
            "sprint": self.sprint,
            "repo": self.repo,
            "planned_at": self.planned_at,
            "stories": [
                {
                    "issue": s.issue,
                    "title": s.title,
                    "sub_tasks": [
                        {
                            "id": st.id,
                            "description": st.description,
                            "files": st.files,
                            "depends_on": st.depends_on,
                            "estimated_complexity": st.estimated_complexity,
                        }
                        for st in s.sub_tasks
                    ],
                    "architecture_notes": s.architecture_notes,
                    "risks": s.risks,
                    "files_to_modify": s.files_to_modify,
                    "files_to_create": s.files_to_create,
                }
                for s in self.stories
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectPlan:
        """Deserialize from dict."""
        stories = []
        for sd in data.get("stories", []):
            sub_tasks = [
                SubTask(
                    id=st["id"],
                    description=st["description"],
                    files=st.get("files", []),
                    depends_on=st.get("depends_on", []),
                    estimated_complexity=st.get("estimated_complexity", "small"),
                )
                for st in sd.get("sub_tasks", [])
            ]
            stories.append(
                StoryPlan(
                    issue=sd["issue"],
                    title=sd["title"],
                    sub_tasks=sub_tasks,
                    architecture_notes=sd.get("architecture_notes", ""),
                    risks=sd.get("risks", []),
                    files_to_modify=sd.get("files_to_modify", []),
                    files_to_create=sd.get("files_to_create", []),
                )
            )
        return cls(
            sprint=data.get("sprint", ""),
            repo=data.get("repo", ""),
            planned_at=data.get("planned_at", ""),
            stories=stories,
        )

    def save(self, sprint_id: str) -> Path:
        """Save plan to disk."""
        plan_dir = Path(PLANS_DIR) / sprint_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        slug = self.repo.replace("/", "-")
        path = plan_dir / f"{slug}.json"
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, sprint_id: str, repo: str) -> Optional[ProjectPlan]:
        """Load a previously saved plan."""
        slug = repo.replace("/", "-")
        path = Path(PLANS_DIR) / sprint_id / f"{slug}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return cls.from_dict(json.load(f))


@dataclass
class ReplanRequest:
    """Request to re-plan a story that a dev-lead couldn't execute."""

    story_issue: int
    repo: str
    sprint_id: str
    reason: str
    what_was_attempted: str
    questions_for_planner: list[str] = field(default_factory=list)
    created_at: str = ""

    def save(self) -> Path:
        """Write replan request to the queue."""
        queue_dir = Path(REPLAN_QUEUE_DIR)
        queue_dir.mkdir(parents=True, exist_ok=True)
        self.created_at = datetime.now(timezone.utc).isoformat()
        slug = self.repo.replace("/", "-")
        path = queue_dir / f"replan-{slug}-{self.story_issue}-{int(time.time())}.json"
        with open(path, "w") as f:
            json.dump(
                {
                    "story_issue": self.story_issue,
                    "repo": self.repo,
                    "sprint_id": self.sprint_id,
                    "reason": self.reason,
                    "what_was_attempted": self.what_was_attempted,
                    "questions_for_planner": self.questions_for_planner,
                    "created_at": self.created_at,
                },
                f,
                indent=2,
            )
        return path

    @classmethod
    def load(cls, path: Path) -> ReplanRequest:
        """Load a replan request from the queue."""
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def pending(cls) -> list[ReplanRequest]:
        """List all pending replan requests."""
        queue_dir = Path(REPLAN_QUEUE_DIR)
        if not queue_dir.exists():
            return []
        requests = []
        for p in sorted(queue_dir.glob("replan-*.json")):
            try:
                requests.append(cls.load(p))
            except Exception:
                continue
        return requests

    def consume(self) -> None:
        """Remove this request from the queue after processing."""
        queue_dir = Path(REPLAN_QUEUE_DIR)
        slug = self.repo.replace("/", "-")
        for p in queue_dir.glob(f"replan-{slug}-{self.story_issue}-*.json"):
            p.unlink(missing_ok=True)


# Map repo slugs to local paths (shared with swarm.py)
REPO_PATHS: dict[str, str] = {
    "tquick/claude-gate": os.path.expanduser("~/projects/claude-gate"),
    "tquick/dnd-tools": os.path.expanduser("~/projects/dnd-tools"),
    "tquick/wasteland-infra": os.path.expanduser("~/projects/wasteland-infra"),
    "tquick/meeting-scribe": os.path.expanduser("~/projects/meeting-scribe"),
    "tquick/dungeon-crawler": os.path.expanduser("~/projects/dungeon-crawler"),
    "tquick/wasteland-orchestrator": os.path.expanduser(
        "~/projects/wasteland-orchestrator"
    ),
    "tquick/wasteland-hq": os.path.expanduser("~/projects/wasteland-hq"),
}


def _build_planner_prompt(repo: str, tasks: list[Task], replan: Optional[ReplanRequest] = None) -> str:
    """Build the prompt for a planner agent."""
    repo_path = REPO_PATHS.get(
        repo, os.path.expanduser(f"~/projects/{repo.split('/')[-1]}")
    )

    stories_block = ""
    for task in tasks:
        stories_block += f"\n### Story: {task.id} — {task.title}\n"
        if task.issue:
            stories_block += f"Issue: #{task.issue}\n"
        if task.files:
            stories_block += f"Known files: {', '.join(task.files)}\n"
        if task.prompt:
            stories_block += f"\n{task.prompt}\n"

    replan_block = ""
    if replan:
        replan_block = f"""
## REPLAN REQUEST

This story was previously planned but the dev-lead couldn't execute it.

**Reason:** {replan.reason}
**What was attempted:** {replan.what_was_attempted}
**Questions from dev-lead:**
{chr(10).join(f'- {q}' for q in replan.questions_for_planner)}

Please produce a revised plan that addresses these issues.
"""

    return f"""You are a planning agent for the {repo} repository.
Your job is to read sprint stories and produce detailed implementation plans.
You do NOT implement anything. You only plan.

Repository path: {repo_path}

## Instructions

For each story below:
1. Read the story description carefully
2. Explore the codebase at {repo_path} to understand current state
3. Identify which files need to change and which need to be created
4. Break the work into sub-tasks (target 5-6 per story)
5. Order sub-tasks by dependency (what must be done first)
6. Identify risks and ambiguities
7. Note architecture decisions

{replan_block}

## Stories to Plan
{stories_block}

## Output Format

You MUST output your plan as a single JSON block wrapped in ```json fences.
The JSON must follow this exact schema:

```json
{{
  "stories": [
    {{
      "issue": <issue_number>,
      "title": "<story title>",
      "sub_tasks": [
        {{
          "id": "<issue_number>.<sequence>",
          "description": "<clear, actionable description of what to do>",
          "files": ["<file paths to create or modify>"],
          "depends_on": ["<other sub_task ids>"],
          "estimated_complexity": "<trivial|small|medium|large>"
        }}
      ],
      "architecture_notes": "<key decisions, patterns to follow, gotchas>",
      "risks": ["<things that could block or go wrong>"],
      "files_to_modify": ["<existing files that need changes>"],
      "files_to_create": ["<new files to create>"]
    }}
  ]
}}
```

Be specific and actionable. Each sub-task should be something a developer
can pick up and implement without needing to do their own research.
File paths should be relative to the repository root.
"""


class PlanPhase:
    """Runs the planning phase of a sprint.

    Groups manifest stories by repo, spawns one planner agent per repo,
    collects structured plans, and saves them to disk.
    """

    def __init__(
        self,
        manifest: PhaseManifest,
        dry_run: bool = False,
        timeout: int = PLANNER_TIMEOUT,
    ):
        self.manifest = manifest
        self.dry_run = dry_run
        self.timeout = timeout
        self._plans: dict[str, ProjectPlan] = {}

    def _group_by_repo(self) -> dict[str, list[Task]]:
        """Group manifest tasks by repository."""
        groups: dict[str, list[Task]] = {}
        for task in self.manifest.tasks:
            repo = task.repo or self.manifest.repo
            if repo not in groups:
                groups[repo] = []
            groups[repo].append(task)
        return groups

    def _run_planner(
        self, repo: str, tasks: list[Task], replan: Optional[ReplanRequest] = None
    ) -> Optional[ProjectPlan]:
        """Spawn a planner agent for one repo and parse its output."""
        prompt = _build_planner_prompt(repo, tasks, replan)
        repo_path = REPO_PATHS.get(
            repo, os.path.expanduser(f"~/projects/{repo.split('/')[-1]}")
        )

        if self.dry_run:
            print(f"[plan] DRY RUN: would plan {len(tasks)} stories for {repo}")
            for t in tasks:
                print(f"[plan]   {t.id}: {t.title}")
            return None

        print(f"[plan] Planning {len(tasks)} stories for {repo}...")

        # Spawn planner as claude -p with read-only tools
        cmd = [
            CLAUDE_BIN,
            "-p",
            prompt,
            "--output-format",
            "text",
            "--allowedTools",
            "Read,Glob,Grep,Bash(find:*),Bash(ls:*),Bash(wc:*),Bash(cat:*)",
        ]

        # Strip CLAUDECODE env to allow nested session
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

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=repo_path,
                env=env,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            print(f"[plan] TIMEOUT: planner for {repo} exceeded {self.timeout}s")
            return None

        if result.returncode != 0:
            print(f"[plan] FAILED: planner for {repo} exited {result.returncode}")
            if result.stderr:
                print(f"[plan]   stderr: {result.stderr[:500]}")
            return None

        output = result.stdout
        plan = self._parse_plan_output(repo, output)
        if plan:
            plan.planner_output_raw = output
        return plan

    def _parse_plan_output(self, repo: str, output: str) -> Optional[ProjectPlan]:
        """Extract structured JSON plan from planner agent output."""
        # Find JSON block in output (between ```json and ```)
        json_start = output.find("```json")
        if json_start == -1:
            # Try bare JSON object
            json_start = output.find('{"stories"')
            if json_start == -1:
                print(f"[plan] WARNING: no JSON plan found in planner output for {repo}")
                print(f"[plan]   Output preview: {output[:200]}")
                return None
            json_end = output.rfind("}") + 1
            json_str = output[json_start:json_end]
        else:
            json_start = output.index("\n", json_start) + 1
            json_end = output.find("```", json_start)
            if json_end == -1:
                print(f"[plan] WARNING: unterminated JSON block for {repo}")
                return None
            json_str = output[json_start:json_end].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[plan] WARNING: invalid JSON in planner output for {repo}: {e}")
            return None

        data["sprint"] = self.manifest.phase
        data["repo"] = repo
        data["planned_at"] = datetime.now(timezone.utc).isoformat()

        return ProjectPlan.from_dict(data)

    def run(self) -> dict[str, ProjectPlan]:
        """Execute the planning phase for all repos in the manifest.

        Returns a dict mapping repo -> ProjectPlan.
        Plans are also saved to disk for audit trail.
        """
        groups = self._group_by_repo()
        print(f"[plan] Planning phase: {len(groups)} project(s), "
              f"{len(self.manifest.tasks)} total stories")

        # Check for replan requests
        replans = ReplanRequest.pending()
        replan_by_repo: dict[str, list[ReplanRequest]] = {}
        for r in replans:
            if r.repo not in replan_by_repo:
                replan_by_repo[r.repo] = []
            replan_by_repo[r.repo].append(r)

        if replans:
            print(f"[plan] Found {len(replans)} replan request(s)")

        for repo, tasks in groups.items():
            # Check if any tasks need replanning
            repo_replans = replan_by_repo.get(repo, [])
            replan = repo_replans[0] if repo_replans else None

            plan = self._run_planner(repo, tasks, replan)
            if plan:
                self._plans[repo] = plan
                saved_path = plan.save(self.manifest.phase)
                print(f"[plan] Saved plan for {repo}: {saved_path}")
                print(f"[plan]   {len(plan.stories)} stories planned, "
                      f"{sum(len(s.sub_tasks) for s in plan.stories)} sub-tasks total")

                # Consume replan requests that were addressed
                if replan:
                    replan.consume()
                    print(f"[plan]   Consumed replan request for issue #{replan.story_issue}")
            else:
                print(f"[plan] WARNING: no plan produced for {repo} — "
                      "stories will be dispatched without detailed plans")

        return self._plans

    def get_plan(self, repo: str) -> Optional[ProjectPlan]:
        """Get the plan for a specific repo."""
        return self._plans.get(repo)

    def get_plan_json(self, repo: str) -> str:
        """Get the plan for a repo as a formatted JSON string for injection."""
        plan = self._plans.get(repo)
        if not plan:
            return '{"stories": [], "note": "No plan available — planner did not produce output"}'
        return json.dumps(plan.to_dict(), indent=2)
