from __future__ import annotations

import fnmatch
import subprocess
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from compliance_harness.config import HarnessConfig, load_config
from compliance_harness.reviewer import ComplianceReviewer


class CodingAlertHandler(FileSystemEventHandler):
    def __init__(self, reviewer: ComplianceReviewer, config: HarnessConfig):
        self.reviewer = reviewer
        self.config = config
        self._last_run = 0.0
        self._pending = False

    def on_modified(self, event):
        if event.is_directory:
            return
        self._schedule_review(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        self._schedule_review(event.src_path)

    def _schedule_review(self, src_path: str) -> None:
        rel = Path(src_path)
        for pattern in self.config.watch.ignore_patterns:
            if fnmatch.fnmatch(str(rel), pattern) or fnmatch.fnmatch(src_path, pattern):
                return

        now = time.time()
        if now - self._last_run < self.config.watch.debounce_seconds:
            self._pending = True
            return

        self._last_run = now
        self._pending = False
        self._run_alert(str(rel))

    def _run_alert(self, file_path: str) -> None:
        try:
            diff = _file_diff(self.config.repo_root, file_path)
            result = self.reviewer.review_changes(
                trigger=f"watch:{file_path}",
                diff_text=diff,
                files_changed=[file_path],
                block_threshold="critical",
            )
            _print_alert(result)
        except Exception as exc:
            print(f"[crh:watch] alert error: {exc}", file=sys.stderr)


def run_watcher(config_path: Path | None = None) -> None:
    config = load_config(config_path)
    if not config.watch.enabled:
        print("Watch mode disabled in config.")
        return

    reviewer = ComplianceReviewer(config)
    handler = CodingAlertHandler(reviewer, config)
    observer = Observer()
    observer.schedule(handler, str(config.repo_root), recursive=True)
    observer.start()

    print(f"[crh:watch] Monitoring {config.repo_root} for compliance alerts...")
    print("[crh:watch] Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def _file_diff(repo_root: Path, file_path: str) -> str:
    try:
        staged = subprocess.run(
            ["git", "diff", "--", file_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        if staged.strip():
            return staged
        return subprocess.run(
            ["git", "diff", "HEAD", "--", file_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except FileNotFoundError:
        p = repo_root / file_path
        if p.exists():
            return p.read_text(errors="replace")[:10000]
        return ""


def _print_alert(result) -> None:
    if not result.findings:
        return
    print("\n" + "=" * 60)
    print("COMPLIANCE ALERT (live coding)")
    print("=" * 60)
    for f in result.findings:
        if f.severity in ("critical", "high"):
            print(f"  [{f.severity.upper()}] {f.title}")
            print(f"    {f.description[:200]}")
    print(f"Verdict: {result.verdict} | Decision: {'ALLOW' if result.allowed else 'BLOCK'}")
    print("=" * 60 + "\n")
