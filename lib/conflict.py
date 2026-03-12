"""Conflict detection via file ownership.

Analyzes a phase manifest to detect tasks that touch the same files.
Tasks with overlapping file ownership must be serialized (not run in
parallel) to prevent merge conflicts.

Usage:
    from lib.conflict import detect_conflicts, apply_serialization
    from lib.manifest import PhaseManifest

    manifest = PhaseManifest.from_yaml("phase.yaml")
    conflicts = detect_conflicts(manifest)
    if conflicts:
        apply_serialization(manifest, conflicts)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from lib.manifest import PhaseManifest


@dataclass
class FileConflict:
    """A conflict where multiple tasks touch the same file."""

    file_path: str
    task_ids: list[str]


def build_ownership_map(manifest: PhaseManifest) -> dict[str, list[str]]:
    """Build a map of file -> list of task IDs that touch it."""
    ownership: dict[str, list[str]] = defaultdict(list)
    for task in manifest.tasks:
        for f in task.files:
            ownership[f].append(task.id)
    return dict(ownership)


def detect_conflicts(manifest: PhaseManifest) -> list[FileConflict]:
    """Find files touched by multiple tasks."""
    ownership = build_ownership_map(manifest)
    conflicts = []
    for file_path, task_ids in ownership.items():
        if len(task_ids) > 1:
            conflicts.append(FileConflict(file_path=file_path, task_ids=task_ids))
    return conflicts


def apply_serialization(
    manifest: PhaseManifest,
    conflicts: Optional[list[FileConflict]] = None,
) -> list[FileConflict]:
    """Add dependency edges to serialize conflicting tasks.

    For each conflict, the task with the higher issue number gets a
    dependency on the lower one, ensuring sequential execution.

    Returns the conflicts that were resolved.
    """
    if conflicts is None:
        conflicts = detect_conflicts(manifest)

    if not conflicts:
        return []

    # Build a lookup for tasks
    task_map = {s.id: s for s in manifest.tasks}

    for conflict in conflicts:
        # Sort by issue number (or task ID) to get deterministic ordering
        sorted_ids = sorted(
            conflict.task_ids,
            key=lambda sid: task_map[sid].issue or 0,
        )
        # Chain them: each task depends on the previous one
        for i in range(1, len(sorted_ids)):
            later = task_map[sorted_ids[i]]
            earlier_id = sorted_ids[i - 1]
            if earlier_id not in later.depends_on:
                later.depends_on.append(earlier_id)

    return conflicts


def print_conflicts(conflicts: list[FileConflict]) -> None:
    """Print conflict report to stdout."""
    if not conflicts:
        print("[conflict] No file ownership conflicts detected.")
        return
    print(f"[conflict] {len(conflicts)} file conflict(s) detected:")
    for c in conflicts:
        print(f"  {c.file_path}: {', '.join(c.task_ids)}")
