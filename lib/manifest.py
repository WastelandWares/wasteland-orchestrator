"""Phase manifest parser and data model.

Defines the YAML format for automated phase dispatch. The manifest is the
contract between the PM (who plans) and the dispatcher (who executes).

Usage:
    from lib.manifest import PhaseManifest

    manifest = PhaseManifest.from_yaml("phase.yaml")
    for task in manifest.tasks:
        print(f"{task.id}: {task.title} -> {task.agent}")
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Task:
    """A single work item in the phase."""

    id: str
    title: str
    agent: str
    repo: str
    issue: Optional[int] = None
    depends_on: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    prompt: str = ""
    labels: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass
class PhaseManifest:
    """Complete phase manifest parsed from YAML."""

    phase: str
    project: str
    repo: str
    tasks: list[Task]
    worktree_branch: str = ""
    max_parallel: int = 3

    @classmethod
    def from_yaml(cls, path: str | Path) -> PhaseManifest:
        """Parse a phase manifest from a YAML file."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or "phase" not in data:
            raise ValueError(f"Invalid manifest: missing 'phase' key in {path}")

        tasks = []
        for s in data.get("tasks", []):
            tasks.append(
                Task(
                    id=s["id"],
                    title=s["title"],
                    agent=s["agent"],
                    repo=s.get("repo", data.get("repo", "")),
                    issue=s.get("issue"),
                    depends_on=s.get("depends_on", []),
                    files=s.get("files", []),
                    prompt=s.get("prompt", ""),
                    labels=s.get("labels", []),
                    priority=s.get("priority", 0),
                )
            )

        return cls(
            phase=data["phase"],
            project=data.get("project", ""),
            repo=data.get("repo", ""),
            tasks=tasks,
            worktree_branch=data.get("worktree_branch", ""),
            max_parallel=data.get("max_parallel", 3),
        )

    def to_yaml(self, path: str | Path) -> None:
        """Write the manifest to a YAML file."""
        data = {
            "phase": self.phase,
            "project": self.project,
            "repo": self.repo,
            "worktree_branch": self.worktree_branch,
            "max_parallel": self.max_parallel,
            "tasks": [],
        }
        for s in self.tasks:
            task_data: dict = {
                "id": s.id,
                "title": s.title,
                "agent": s.agent,
                "repo": s.repo,
                "issue": s.issue,
                "prompt": s.prompt,
            }
            if s.depends_on:
                task_data["depends_on"] = s.depends_on
            if s.files:
                task_data["files"] = s.files
            if s.labels:
                task_data["labels"] = s.labels
            if s.priority:
                task_data["priority"] = s.priority
            data["tasks"].append(task_data)

        path = Path(path)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_task(self, task_id: str) -> Optional[Task]:
        """Find a task by ID."""
        for s in self.tasks:
            if s.id == task_id:
                return s
        return None

    def dependency_order(self) -> list[list[Task]]:
        """Return tasks grouped into dependency layers.

        Each layer contains tasks that can run in parallel (all deps satisfied
        by previous layers). This is a topological sort by layers.
        """
        completed: set[str] = set()
        remaining = {s.id: s for s in self.tasks}
        layers: list[list[Task]] = []

        while remaining:
            # Find tasks whose deps are all completed
            ready = [
                s for s in remaining.values()
                if all(d in completed for d in s.depends_on)
            ]
            if not ready:
                unresolved = list(remaining.keys())
                raise ValueError(
                    f"Circular or unresolvable dependencies: {unresolved}"
                )
            layers.append(ready)
            for s in ready:
                completed.add(s.id)
                del remaining[s.id]

        return layers
