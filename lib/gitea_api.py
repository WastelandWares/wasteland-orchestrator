"""Gitea API client library.

Handles the dual-auth pattern (Caddy basic auth + Gitea token) automatically.
All agents should use this instead of raw curl/requests.

Usage:
    from lib.gitea_api import GiteaClient

    gitea = GiteaClient()
    issues = gitea.get("repos/tquick/meeting-scribe/issues", params={"state": "open"})
    gitea.post("repos/tquick/meeting-scribe/issues", {"title": "New issue", "body": "..."})
    gitea.patch("repos/tquick/meeting-scribe/issues/1", {"state": "closed"})
    gitea.create_issue("tquick/meeting-scribe", "Title", "Body", labels=[1, 2])
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Optional, Union


class GiteaClient:
    """Gitea API client with dual-auth support."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        token: Optional[str] = None,
        basic_auth: Optional[str] = None,
    ):
        self.api_url = (
            api_url
            or os.environ.get("GITEA_API_URL", "https://git.wastelandwares.com/api/v1")
        )
        self.token = (
            token
            or os.environ.get("GITEA_API_TOKEN", "")
        )
        self.basic_auth = (
            basic_auth
            or os.environ.get("GITEA_BASIC_AUTH", "")
        )

    def _curl(self, method: str, endpoint: str, data: Optional[dict] = None, params: Optional[dict] = None) -> Union[dict, list, str]:
        """Execute a curl request with dual-auth."""
        # Build URL with token and params
        url = f"{self.api_url}/{endpoint}?token={self.token}"
        if params:
            for k, v in params.items():
                url += f"&{k}={v}"

        cmd = ["curl", "-sf"]
        if self.basic_auth:
            cmd += ["-u", self.basic_auth]
        cmd += ["-X", method]

        tmpfile = None
        if data is not None:
            tmpfile = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            )
            json.dump(data, tmpfile)
            tmpfile.close()
            cmd += ["-H", "Content-Type: application/json", "-d", f"@{tmpfile.name}"]

        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if tmpfile:
                os.unlink(tmpfile.name)
            if result.stdout:
                return json.loads(result.stdout)
            return ""
        except json.JSONDecodeError:
            return result.stdout
        except subprocess.TimeoutExpired:
            if tmpfile:
                os.unlink(tmpfile.name)
            raise
        except Exception:
            if tmpfile and os.path.exists(tmpfile.name):
                os.unlink(tmpfile.name)
            raise

    def get(self, endpoint: str, params: Optional[dict] = None):
        """GET request."""
        return self._curl("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict):
        """POST request."""
        return self._curl("POST", endpoint, data=data)

    def patch(self, endpoint: str, data: dict):
        """PATCH request."""
        return self._curl("PATCH", endpoint, data=data)

    def delete(self, endpoint: str):
        """DELETE request."""
        return self._curl("DELETE", endpoint)

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[int]] = None,
        assignees: Optional[list[str]] = None,
        milestone: Optional[int] = None,
    ) -> dict:
        """Create an issue with proper escaping."""
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        if milestone:
            payload["milestone"] = milestone
        return self.post(f"repos/{repo}/issues", payload)

    def add_comment(self, repo: str, issue_number: int, body: str) -> dict:
        """Add a comment to an issue."""
        return self.post(
            f"repos/{repo}/issues/{issue_number}/comments",
            {"body": body},
        )

    def list_issues(self, repo: str, state: str = "open", limit: int = 50) -> list:
        """List issues for a repo."""
        return self.get(
            f"repos/{repo}/issues",
            params={"state": state, "limit": str(limit)},
        )

    def list_labels(self, repo: str) -> list:
        """List labels for a repo."""
        return self.get(f"repos/{repo}/labels")

    def create_label(self, repo: str, name: str, color: str, description: str = "") -> dict:
        """Create a label."""
        return self.post(
            f"repos/{repo}/labels",
            {"name": name, "color": color, "description": description},
        )
