from __future__ import annotations

import subprocess

from compliancegate.config import HarnessConfig
from compliancegate.db import ComplianceDB


class SessionManager:
    def __init__(self, config: HarnessConfig, db: ComplianceDB):
        self.config = config
        self.db = db
        self._session_id: str | None = None

    def ensure_session(self) -> str:
        if self._session_id:
            return self._session_id

        active = self.db.get_active_session(self.config.project_name)
        if active:
            self._session_id = active
            return active

        branch, head = _git_state(self.config.repo_root)
        self._session_id = self.db.create_session(
            project_name=self.config.project_name,
            git_branch=branch,
            git_head=head,
        )
        return self._session_id

    def end_session(self, summary: str = "") -> None:
        if self._session_id:
            self.db.end_session(self._session_id, summary)
            self._session_id = None


def _git_state(repo_root) -> tuple[str, str]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        return branch, head
    except FileNotFoundError:
        return "", ""
