"""Sprint manifest parser and data model.

Defines the YAML format for automated sprint dispatch. The manifest is the
contract between the PM (who plans) and the dispatcher (who executes).

Usage:
    from lib.manifest import SprintManifest

    manifest = SprintManifest.from_yaml("sprint.yaml")
    for story in manifest.stories:
        print(f"{story.id}: {story.title} -> {story.agent}")
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Story:
    """A single work item in the sprint."""

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
class SprintManifest:
    """Complete sprint manifest parsed from YAML."""

    sprint: str
    project: str
    repo: str
    stories: list[Story]
    worktree_branch: str = ""
    max_parallel: int = 3

    @classmethod
    def from_yaml(cls, path: str | Path) -> SprintManifest:
        """Parse a sprint manifest from a YAML file."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        if not data or "sprint" not in data:
            raise ValueError(f"Invalid manifest: missing 'sprint' key in {path}")

        stories = []
        for s in data.get("stories", []):
            stories.append(
                Story(
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
            sprint=data["sprint"],
            project=data.get("project", ""),
            repo=data.get("repo", ""),
            stories=stories,
            worktree_branch=data.get("worktree_branch", ""),
            max_parallel=data.get("max_parallel", 3),
        )

    def to_yaml(self, path: str | Path) -> None:
        """Write the manifest to a YAML file."""
        data = {
            "sprint": self.sprint,
            "project": self.project,
            "repo": self.repo,
            "worktree_branch": self.worktree_branch,
            "max_parallel": self.max_parallel,
            "stories": [],
        }
        for s in self.stories:
            story_data: dict = {
                "id": s.id,
                "title": s.title,
                "agent": s.agent,
                "repo": s.repo,
                "issue": s.issue,
                "prompt": s.prompt,
            }
            if s.depends_on:
                story_data["depends_on"] = s.depends_on
            if s.files:
                story_data["files"] = s.files
            if s.labels:
                story_data["labels"] = s.labels
            if s.priority:
                story_data["priority"] = s.priority
            data["stories"].append(story_data)

        path = Path(path)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_story(self, story_id: str) -> Optional[Story]:
        """Find a story by ID."""
        for s in self.stories:
            if s.id == story_id:
                return s
        return None

    def dependency_order(self) -> list[list[Story]]:
        """Return stories grouped into dependency layers.

        Each layer contains stories that can run in parallel (all deps satisfied
        by previous layers). This is a topological sort by layers.
        """
        completed: set[str] = set()
        remaining = {s.id: s for s in self.stories}
        layers: list[list[Story]] = []

        while remaining:
            # Find stories whose deps are all completed
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
