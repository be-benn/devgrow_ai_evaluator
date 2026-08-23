import re
import subprocess
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from evaluator.config import (
SENSITIVE_FILE_PATTERNS,
LANGUAGE_EXTENSION_MAP,
)


class GitService:
    """
    Handles Git operations required by the evaluator:

    - Resolve branches/tags/commit IDs to immutable commit SHAs
    - Find changed files between base and target revisions
    - Find added/deleted line ranges
    - Read files directly from a specific Git revision
    - List files available at a specific revision
    - Detect repository URLs
    - Clone repositories

    Evaluation should not depend on the currently checked-out branch.
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
                f"Repository path does not exist: "
                f"{self.repository_path}"
            )

        if not self._is_git_repository():
            raise ValueError(
                f"Not a valid Git repository: "
                f"{self.repository_path}"
            )

    # ── Repository preparation ──────────────────────────────

    @staticmethod
    def is_repository_url(value: str) -> bool:
        """
        Determine whether the supplied value looks like
        a Git repository URL.

        Supported examples:

            https://github.com/user/repository.git
            http://server/repository.git
            git://server/repository.git
            ssh://server/repository.git

        Local paths return False.
        """

        if not value:
            return False

        value = value.strip()

        try:
            parsed = urlparse(value)
        except Exception:
            return False

        return parsed.scheme.lower() in {
            "http",
            "https",
            "git",
            "ssh",
        }

    @staticmethod
    def clone_repository(
        repository_url: str,
        destination: str,
    ) -> str:
        """
        Clone a Git repository into the supplied destination.

        Normally the destination will be inside a
        TemporaryDirectory created by evaluation_service.py.
        """

        if not repository_url:
            raise ValueError(
                "Repository URL cannot be empty."
            )

        if not GitService.is_repository_url(
            repository_url
        ):
            raise ValueError(
                f"Invalid repository URL: {repository_url}"
            )

        destination_path = Path(destination)

        command = [
            "git",
            "clone",
            repository_url,
            str(destination_path),
        ]

        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )

        except FileNotFoundError as exc:
            raise RuntimeError(
                "Git executable not found. "
                "Make sure Git is installed and available in PATH."
            ) from exc

        except subprocess.CalledProcessError as exc:
            error_message = (
                exc.stderr.strip()
                if exc.stderr
                else "Unknown Git clone error."
            )

            raise RuntimeError(
                f"Failed to clone repository: "
                f"{error_message}"
            ) from exc

        return str(
            destination_path.resolve()
        )

    # ── Public API ──────────────────────────────────────────

    def get_files_at_revision(
    self,
    revision: str,
) -> List[str]:
        """
        `Return supported, non-sensitive source files
    that exist in the supplied Git revision.
    """

        revision_sha = self._resolve_commit(
        revision
    )

        output = self._run_git([
        "ls-tree",
        "-r",
        "--name-only",
        revision_sha,
    ])

        if not output:
            return []

        files = []

        for file_path in output.splitlines():
            file_path = file_path.strip()

            if not file_path:
                continue

            if self._is_sensitive(file_path):
                continue

        # Only send file types supported by the parser.
            extension = Path(file_path).suffix.lower()

            if extension not in LANGUAGE_EXTENSION_MAP:
                continue

            files.append(file_path)

        return files

    def get_diff(
        self,
        base_commit: str,
        target_commit: str,
        branch: Optional[str] = None,
    ) -> dict:
        """
        Return changed files between two Git revisions
        together with added/deleted line ranges.

        branch is retained for backward compatibility,
        but it is intentionally NOT checked out.

        base_commit and target_commit may be:

        - local branch names
        - remote branch names
        - tags
        - short SHAs
        - full SHAs
        """

        base_sha = self._resolve_commit(
            base_commit
        )

        target_sha = self._resolve_commit(
            target_commit
        )

        name_status = self._run_git([
            "diff",
            "--name-status",
            "--find-renames",
            "--find-copies",
            base_sha,
            target_sha,
        ])

        changes = self._parse_name_status(
            name_status
        )

        filtered_changes = []

        for change in changes:
            file_path = (
                change.get("new_path")
                or change.get("old_path")
            )

            if not file_path:
                continue

            if self._is_sensitive(
                file_path
            ):
                continue

            line_changes = self._get_line_changes(
                base_sha,
                target_sha,
                change,
            )

            change["added_lines"] = (
                line_changes["added_lines"]
            )

            change["deleted_lines"] = (
                line_changes["deleted_lines"]
            )

            filtered_changes.append(
                change
            )

        return {
            "base_commit": base_sha,
            "target_commit": target_sha,
            "changed_file_count": len(
                filtered_changes
            ),
            "changes": filtered_changes,
        }

    def read_file_content(
        self,
        relative_path: str,
    ) -> Optional[str]:
        """
        Read a file from the current working tree.

        Retained temporarily for backward compatibility.

        Evaluation should prefer read_file_at_revision().
        """

        full_path = (
            self.repository_path
            / relative_path
        )

        if not full_path.exists():
            return None

        try:
            return full_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )

        except Exception:
            return None

    def read_file_at_revision(
        self,
        revision_sha: str,
        relative_path: str,
    ) -> Optional[str]:
        """
        Read a file exactly as it exists at a Git revision.

        Equivalent command:

            git show <revision_sha>:<relative_path>

        This does not depend on the currently checked-out branch.
        """

        if not revision_sha:
            return None

        if not relative_path:
            return None

        normalized_path = (
            relative_path
            .replace("\\", "/")
            .lstrip("/")
        )

        if not normalized_path:
            return None

        try:
            return self._run_git([
                "show",
                f"{revision_sha}:{normalized_path}",
            ])

        except RuntimeError:
            return None

    # ── Git commands ────────────────────────────────────────

    def _run_git(
        self,
        arguments: list,
    ) -> str:
        """
        Execute a Git command inside the repository.
        """

        command = [
            "git",
            *arguments,
        ]

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

        except FileNotFoundError as exc:
            raise RuntimeError(
                "Git executable not found. "
                "Make sure Git is installed and available in PATH."
            ) from exc

        except subprocess.CalledProcessError as exc:
            error_message = (
                exc.stderr.strip()
                if exc.stderr
                else "Unknown Git error."
            )

            raise RuntimeError(
                f"Git command failed: "
                f"{' '.join(command)}\n"
                f"{error_message}"
            ) from exc

    def _is_git_repository(
        self,
    ) -> bool:
        """
        Check whether repository_path points to
        a valid Git working tree.
        """

        try:
            result = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "--is-inside-work-tree",
                ],
                cwd=self.repository_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            return (
                result.returncode == 0
                and result.stdout
                .strip()
                .lower()
                == "true"
            )

        except FileNotFoundError as exc:
            raise RuntimeError(
                "Git executable not found. "
                "Make sure Git is installed and available in PATH."
            ) from exc

    def _resolve_commit(
        self,
        revision: str,
    ) -> str:
        """
        Resolve a local branch, remote branch, tag,
        short SHA, or full SHA to an immutable commit SHA.

        If a plain branch such as 'deva' is not available
        locally, try the corresponding 'origin/deva' ref.
        """

        if not revision:
            raise ValueError(
                "Commit ID cannot be empty."
            )

        revision = revision.strip()

        # First try exactly what the user supplied.
        try:
            return self._run_git([
                "rev-parse",
                f"{revision}^{{commit}}",
            ])

        except RuntimeError as first_error:
            # If origin/... was already supplied,
            # do not prepend origin again.
            if revision.startswith(
                "origin/"
            ):
                raise first_error

            remote_revision = (
                f"origin/{revision}"
            )

            # Try the remote-tracking branch.
            try:
                return self._run_git([
                    "rev-parse",
                    f"{remote_revision}^{{commit}}",
                ])

            except RuntimeError:
                raise ValueError(
                    f"Unable to resolve Git revision "
                    f"'{revision}' or "
                    f"'{remote_revision}'."
                ) from first_error

    # ── Diff parsing ────────────────────────────────────────

    def _parse_name_status(
        self,
        diff_output: str,
    ) -> List[dict]:
        """
        Parse git diff --name-status output.
        """

        changes = []

        if not diff_output:
            return changes

        for line in diff_output.splitlines():
            parts = line.split("\t")

            raw_status = parts[0]
            status_code = raw_status[0]

            change_type = (
                self.STATUS_MAP.get(
                    status_code,
                    "unknown",
                )
            )

            if status_code in {
                "R",
                "C",
            }:
                old_path = parts[1]
                new_path = parts[2]

                similarity = None

                similarity_text = (
                    raw_status[1:]
                )

                if similarity_text.isdigit():
                    similarity = int(
                        similarity_text
                    )

                changes.append({
                    "change_type":
                        change_type,
                    "old_path":
                        old_path,
                    "new_path":
                        new_path,
                    "similarity":
                        similarity,
                })

            else:
                file_path = parts[1]

                if status_code == "D":
                    old_path = file_path
                    new_path = None

                elif status_code == "A":
                    old_path = None
                    new_path = file_path

                else:
                    old_path = file_path
                    new_path = file_path

                changes.append({
                    "change_type":
                        change_type,
                    "old_path":
                        old_path,
                    "new_path":
                        new_path,
                })

        return changes

    def _get_line_changes(
        self,
        base_sha: str,
        target_sha: str,
        change: dict,
    ) -> dict:
        """
        Get added and deleted line ranges for a changed file.
        """

        file_path = (
            change.get("new_path")
            or change.get("old_path")
        )

        diff_output = self._run_git([
            "diff",
            "--unified=0",
            base_sha,
            target_sha,
            "--",
            file_path,
        ])

        added_lines = []
        deleted_lines = []

        for line in diff_output.splitlines():
            if not line.startswith("@@"):
                continue

            (
                old_start,
                old_count,
                new_start,
                new_count,
            ) = self._parse_hunk_header(
                line
            )

            if old_count > 0:
                deleted_lines.append([
                    old_start,
                    old_start
                    + old_count
                    - 1,
                ])

            if new_count > 0:
                added_lines.append([
                    new_start,
                    new_start
                    + new_count
                    - 1,
                ])

        return {
            "added_lines":
                added_lines,
            "deleted_lines":
                deleted_lines,
        }

    def _parse_hunk_header(
        self,
        header: str,
    ):
        """
        Parse a Git diff hunk header such as:

            @@ -10,2 +10,4 @@
        """

        hunk = (
            header
            .split("@@")[1]
            .strip()
        )

        old_part, new_part = (
            hunk
            .split(" ")[:2]
        )

        old_start, old_count = (
            self._parse_range(
                old_part
            )
        )

        new_start, new_count = (
            self._parse_range(
                new_part
            )
        )

        return (
            old_start,
            old_count,
            new_start,
            new_count,
        )

    def _parse_range(
        self,
        value: str,
    ):
        """
        Parse a Git diff range such as:

            -10,3
            +12,5
            +18
        """

        value = value[1:]

        if "," in value:
            start, count = (
                value.split(",")
            )
        else:
            start = value
            count = 1

        return (
            int(start),
            int(count),
        )

    # ── Filtering ───────────────────────────────────────────

    def _is_sensitive(
        self,
        file_path: str,
    ) -> bool:
        """
        Return True if the path matches any configured
        sensitive-file pattern.
        """

        return any(
            re.search(
                pattern,
                file_path,
                re.IGNORECASE,
            )
            for pattern
            in SENSITIVE_FILE_PATTERNS
        )