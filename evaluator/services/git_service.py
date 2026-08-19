import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from evaluator.config import SENSITIVE_FILE_PATTERNS


class GitService:
    """
    Extracts git commit diffs: changed files, change types,
    and added/deleted line ranges using git subprocess operations.
    """

    STATUS_MAP = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type_changed",
    }

    def __init__(self, repository_path: str):
        self.repository_path = Path(repository_path).resolve()

        if not self.repository_path.exists():
            raise FileNotFoundError(
                f"Repository path does not exist: {self.repository_path}"
            )

        if not self._is_git_repository():
            raise ValueError(
                f"Not a valid Git repository: {self.repository_path}"
            )

    # ── Public API ──────────────────────────────────────────

    def get_diff(
        self,
        base_commit: str,
        target_commit: str,
        branch: Optional[str] = None,
    ) -> dict:
        """
        Returns changed files between two commits with line ranges.

        If branch is provided, checks it out first so the target
        file content can be read from disk.
        """
        if branch:
            self._run_git(["checkout", branch])

        base_sha = self._resolve_commit(base_commit)
        target_sha = self._resolve_commit(target_commit)

        name_status = self._run_git([
            "diff", "--name-status", "--find-renames",
            "--find-copies", base_sha, target_sha,
        ])

        changes = self._parse_name_status(name_status)

        # Enrich with line ranges and filter sensitive files
        filtered_changes = []
        for change in changes:
            file_path = change.get("new_path") or change.get("old_path")
            if not file_path:
                continue

            if self._is_sensitive(file_path):
                continue

            line_changes = self._get_line_changes(
                base_sha, target_sha, change
            )
            change["added_lines"] = line_changes["added_lines"]
            change["deleted_lines"] = line_changes["deleted_lines"]
            filtered_changes.append(change)

        return {
            "base_commit": base_sha,
            "target_commit": target_sha,
            "changed_file_count": len(filtered_changes),
            "changes": filtered_changes,
        }

    def read_file_content(self, relative_path: str) -> Optional[str]:
        """Read a file's current content from the repository."""
        full_path = self.repository_path / relative_path
        if not full_path.exists():
            return None
        try:
            return full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    # ── Git commands ────────────────────────────────────────

    def _run_git(self, arguments: list) -> str:
        command = ["git"] + arguments
        try:
            result = subprocess.run(
                command,
                cwd=self.repository_path,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Git command failed: {' '.join(command)}\n"
                f"{exc.stderr.strip()}"
            ) from exc

    def _is_git_repository(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repository_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            return (
                result.returncode == 0
                and result.stdout.strip().lower() == "true"
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Git executable not found. "
                "Make sure Git is installed and available in PATH."
            )

    def _resolve_commit(self, commit_id: str) -> str:
        if not commit_id:
            raise ValueError("Commit ID cannot be empty.")
        return self._run_git(["rev-parse", f"{commit_id}^{{commit}}"])

    # ── Diff parsing ────────────────────────────────────────

    def _parse_name_status(self, diff_output: str) -> List[dict]:
        changes = []
        if not diff_output:
            return changes

        for line in diff_output.splitlines():
            parts = line.split("\t")
            raw_status = parts[0]
            status_code = raw_status[0]
            change_type = self.STATUS_MAP.get(status_code, "unknown")

            if status_code in {"R", "C"}:
                old_path = parts[1]
                new_path = parts[2]
                similarity = None
                similarity_text = raw_status[1:]
                if similarity_text.isdigit():
                    similarity = int(similarity_text)
                changes.append({
                    "change_type": change_type,
                    "old_path": old_path,
                    "new_path": new_path,
                    "similarity": similarity,
                })
            else:
                file_path = parts[1]
                if status_code == "D":
                    old_path, new_path = file_path, None
                elif status_code == "A":
                    old_path, new_path = None, file_path
                else:
                    old_path, new_path = file_path, file_path
                changes.append({
                    "change_type": change_type,
                    "old_path": old_path,
                    "new_path": new_path,
                })

        return changes

    def _get_line_changes(
        self, base_sha: str, target_sha: str, change: dict
    ) -> dict:
        file_path = change.get("new_path") or change.get("old_path")
        diff_output = self._run_git([
            "diff", "--unified=0", base_sha, target_sha, "--", file_path,
        ])

        added_lines = []
        deleted_lines = []

        for line in diff_output.splitlines():
            if not line.startswith("@@"):
                continue
            old_start, old_count, new_start, new_count = (
                self._parse_hunk_header(line)
            )
            if old_count > 0:
                deleted_lines.append([old_start, old_start + old_count - 1])
            if new_count > 0:
                added_lines.append([new_start, new_start + new_count - 1])

        return {"added_lines": added_lines, "deleted_lines": deleted_lines}

    def _parse_hunk_header(self, header: str):
        hunk = header.split("@@")[1].strip()
        old_part, new_part = hunk.split(" ")[:2]
        old_start, old_count = self._parse_range(old_part)
        new_start, new_count = self._parse_range(new_part)
        return old_start, old_count, new_start, new_count

    def _parse_range(self, value: str):
        value = value[1:]  # strip - or +
        if "," in value:
            start, count = value.split(",")
        else:
            start = value
            count = 1
        return int(start), int(count)

    # ── Filtering ───────────────────────────────────────────

    def _is_sensitive(self, file_path: str) -> bool:
        return any(
            re.search(p, file_path, re.IGNORECASE)
            for p in SENSITIVE_FILE_PATTERNS
        )
