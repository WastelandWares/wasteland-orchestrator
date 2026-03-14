#!/usr/bin/env python3
"""Generate a phase manifest YAML from issue data.

Provides helper functions for parsing issue bodies into manifest tasks.
The original Gitea integration has been removed. Provide a YAML manifest
directly or use a different issue source.

Usage:
    python3 generate_manifest.py  # prints removal notice
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from lib.manifest import PhaseManifest, Task


def extract_files(body: str) -> list[str]:
    """Extract file paths from issue body.

    Looks for a '## Files' or '### Files' section with a bulleted list.
    """
    files: list[str] = []
    in_files_section = False
    for line in (body or "").splitlines():
        if re.match(r"^#{2,3}\s+Files", line, re.IGNORECASE):
            in_files_section = True
            continue
        if in_files_section:
            if line.startswith("#"):
                break
            m = re.match(r"^\s*[-*]\s+`?([^`\s]+)`?", line)
            if m:
                files.append(m.group(1))
    return files


def extract_depends_on(body: str) -> list[str]:
    """Extract dependency task IDs from issue body.

    Looks for 'depends on: #X, #Y' or a '## Dependencies' section.
    """
    deps: list[str] = []

    # Inline pattern: "depends on: #3, #4" or "blocked by: #5"
    m = re.search(r"(?:depends on|blocked by)[:\s]+([#\d,\s]+)", body or "", re.IGNORECASE)
    if m:
        for num in re.findall(r"#(\d+)", m.group(1)):
            deps.append(f"#{num}")

    return deps


def extract_agent(issue: dict) -> str:
    """Determine agent name from issue labels or assignees."""
    labels = [l.get("name", "") for l in issue.get("labels", [])]
    for label in labels:
        if label.startswith("agent:"):
            return label.split(":", 1)[1].strip()
    # Fall back to first assignee
    assignees = issue.get("assignees") or []
    if assignees:
        return assignees[0].get("login", "dev-general")
    return "dev-general"


def issues_to_manifest(
    repo: str,
    issues: list[dict],
    phase_name: str = "",
    max_parallel: int = 3,
) -> PhaseManifest:
    """Convert issue dicts to a PhaseManifest."""
    tasks = []
    for issue in issues:
        task_id = f"#{issue['number']}"
        body = issue.get("body", "") or ""

        tasks.append(
            Task(
                id=task_id,
                title=issue["title"],
                agent=extract_agent(issue),
                repo=repo,
                issue=issue["number"],
                depends_on=extract_depends_on(body),
                files=extract_files(body),
                prompt=body.strip(),
                labels=[l["name"] for l in issue.get("labels", [])],
                priority=0,
            )
        )

    # Sort by issue number for deterministic ordering
    tasks.sort(key=lambda s: s.issue or 0)

    return PhaseManifest(
        phase=phase_name or f"{repo.split('/')[-1]}-phase",
        project=repo.split("/")[-1],
        repo=repo,
        tasks=tasks,
        max_parallel=max_parallel,
    )


def main():
    print(
        "Gitea integration removed. Provide a YAML manifest directly "
        "or use a different issue source.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
