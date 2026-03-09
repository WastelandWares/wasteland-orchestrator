"""Conflict detection via file ownership.

Analyzes a sprint manifest to detect stories that touch the same files.
Stories with overlapping file ownership must be serialized (not run in
parallel) to prevent merge conflicts.

Usage:
    from lib.conflict import detect_conflicts, apply_serialization
    from lib.manifest import SprintManifest

    manifest = SprintManifest.from_yaml("sprint.yaml")
    conflicts = detect_conflicts(manifest)
    if conflicts:
        apply_serialization(manifest, conflicts)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from lib.manifest import SprintManifest


@dataclass
class FileConflict:
    """A conflict where multiple stories touch the same file."""

    file_path: str
    story_ids: list[str]


def build_ownership_map(manifest: SprintManifest) -> dict[str, list[str]]:
    """Build a map of file -> list of story IDs that touch it."""
    ownership: dict[str, list[str]] = defaultdict(list)
    for story in manifest.stories:
        for f in story.files:
            ownership[f].append(story.id)
    return dict(ownership)


def detect_conflicts(manifest: SprintManifest) -> list[FileConflict]:
    """Find files touched by multiple stories."""
    ownership = build_ownership_map(manifest)
    conflicts = []
    for file_path, story_ids in ownership.items():
        if len(story_ids) > 1:
            conflicts.append(FileConflict(file_path=file_path, story_ids=story_ids))
    return conflicts


def apply_serialization(
    manifest: SprintManifest,
    conflicts: Optional[list[FileConflict]] = None,
) -> list[FileConflict]:
    """Add dependency edges to serialize conflicting stories.

    For each conflict, the story with the higher issue number gets a
    dependency on the lower one, ensuring sequential execution.

    Returns the conflicts that were resolved.
    """
    if conflicts is None:
        conflicts = detect_conflicts(manifest)

    if not conflicts:
        return []

    # Build a lookup for stories
    story_map = {s.id: s for s in manifest.stories}

    for conflict in conflicts:
        # Sort by issue number (or story ID) to get deterministic ordering
        sorted_ids = sorted(
            conflict.story_ids,
            key=lambda sid: story_map[sid].issue or 0,
        )
        # Chain them: each story depends on the previous one
        for i in range(1, len(sorted_ids)):
            later = story_map[sorted_ids[i]]
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
        print(f"  {c.file_path}: {', '.join(c.story_ids)}")
