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
    Handles Git operations required by the evaluator.

    Responsibilities:
    - Detect repository URLs
    - Clone remote repositories
    - Resolve branches/tags/SHAs to immutable commit SHAs
    - Compare base and target revisions
    - Handle same base/target revision by evaluating latest commit
    - Handle repository initial commit
    - Detect changed files and change types
    - Detect actual added/deleted line ranges
    - Read files directly from a Git revision
    - List files from a single revision

    Evaluation does not depend on the currently checked-out branch.
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
        self.repository_path = Path(
            repository_path
        ).resolve()

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

    # ────────────────────────────────────────────────────────
    # Repository preparation
    # ────────────────────────────────────────────────────────

    @staticmethod
    def is_repository_url(
        value: str,
    ) -> bool:
        """
        Determine whether the supplied value looks like
        a Git repository URL.
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
        Clone a remote Git repository into destination.
        """

        if not repository_url:
            raise ValueError(
                "Repository URL cannot be empty."
            )

        if not GitService.is_repository_url(
            repository_url
        ):
            raise ValueError(
                f"Invalid repository URL: "
                f"{repository_url}"
            )

        destination_path = Path(
            destination
        )

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
                "Make sure Git is installed "
                "and available in PATH."
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

    # ────────────────────────────────────────────────────────
    # Public API
    # ────────────────────────────────────────────────────────

    def get_files_at_revision(
        self,
        revision: str,
    ) -> List[str]:
        """
        Return supported, non-sensitive source files
        available in the supplied Git revision.

        Used when:
        - target_commit is empty
        - repository contains only an initial commit
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

            if self._is_sensitive(
                file_path
            ):
                continue

            extension = (
                Path(file_path)
                .suffix
                .lower()
            )

            # Only source formats supported by
            # parser_service are evaluated.
            if (
                extension
                not in LANGUAGE_EXTENSION_MAP
            ):
                continue

            files.append(
                file_path
            )

        return files

    def get_diff(
        self,
        base_commit: str,
        target_commit: str,
        branch: Optional[str] = None,
    ) -> dict:
        """
        Return evaluation changes between base and target.

        Normal case
        -----------
        base != target

            base
              ↓
            target

        The normal Git diff is evaluated.

        Same revision case
        ------------------
        Example:

            base_commit   = "main"
            target_commit = "main"

        If both resolve to:

            C1 -> C2 -> C3
                        ↑
                       main

        then evaluation becomes:

            base   = C2
            target = C3

        Therefore only the latest commit is evaluated.

        Initial commit case
        -------------------
        If repository history is:

            C1
            ↑
           main

        C1 has no parent. Every supported source file
        in C1 is therefore treated as newly added.

        branch is retained for API compatibility but
        is intentionally not checked out.
        """

        # Resolve both supplied values first.
        base_sha = self._resolve_commit(
            base_commit
        )

        target_sha = self._resolve_commit(
            target_commit
        )

        # ────────────────────────────────────────────────────
        # SAME REVISION
        # ────────────────────────────────────────────────────
        #
        # This works not only for:
        #
        #   main / main
        #
        # but also:
        #
        #   main / origin/main
        #
        # if they resolve to the same SHA.
        #
        if base_sha == target_sha:

            latest_sha = target_sha

            parent_sha = self._get_parent_commit(
                latest_sha
            )

            # ── Initial commit ───────────────────────────────
            #
            # No previous commit exists.
            #
            # Treat all supported files in the initial commit
            # as newly added.
            #
            if parent_sha is None:

                files = self.get_files_at_revision(
                    latest_sha
                )

                changes = [
                    {
                        "change_type": "added",
                        "old_path": None,
                        "new_path": file_path,
                        "added_lines": [],
                        "deleted_lines": [],
                    }
                    for file_path in files
                ]

                return {
                    # There is no true parent/base commit.
                    #
                    # Keeping base and target equal allows
                    # evaluation_service to continue using
                    # target_sha to read complete files.
                    "base_commit": latest_sha,
                    "target_commit": latest_sha,
                    "changed_file_count": len(
                        changes
                    ),
                    "changes": changes,
                    "evaluation_mode":
                        "initial_commit",
                }

            # ── Latest commit evaluation ─────────────────────
            #
            # C1 -> C2 -> C3
            #
            # base   = C2
            # target = C3
            #
            base_sha = parent_sha
            target_sha = latest_sha

            evaluation_mode = (
                "latest_commit"
            )

        else:

            # Normal explicitly supplied base → target.
            evaluation_mode = (
                "base_to_target"
            )

        # ────────────────────────────────────────────────────
        # Git diff
        # ────────────────────────────────────────────────────

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

            # Ignore configured sensitive/binary files.
            if self._is_sensitive(
                file_path
            ):
                continue

            extension = (
                Path(file_path)
                .suffix
                .lower()
            )

            # Only evaluate parser-supported source files.
            if (
                extension
                not in LANGUAGE_EXTENSION_MAP
            ):
                continue

            line_changes = (
                self._get_line_changes(
                    base_sha,
                    target_sha,
                    change,
                )
            )

            change["added_lines"] = (
                line_changes[
                    "added_lines"
                ]
            )

            change["deleted_lines"] = (
                line_changes[
                    "deleted_lines"
                ]
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
            "evaluation_mode":
                evaluation_mode,
        }

    def read_file_content(
        self,
        relative_path: str,
    ) -> Optional[str]:
        """
        Read a file from the current working tree.

        Retained for backward compatibility.

        Evaluation should normally use
        read_file_at_revision().
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
        Read a file exactly as it exists at
        a specific Git revision.

        Equivalent to:

            git show <sha>:<path>
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
                (
                    f"{revision_sha}:"
                    f"{normalized_path}"
                ),
            ])

        except RuntimeError:
            return None

    # ────────────────────────────────────────────────────────
    # Git commands
    # ────────────────────────────────────────────────────────

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
                "Make sure Git is installed "
                "and available in PATH."
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
        Check whether repository_path is
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
                "Make sure Git is installed "
                "and available in PATH."
            ) from exc

    def _resolve_commit(
        self,
        revision: str,
    ) -> str:
        """
        Resolve a local branch, remote branch,
        tag, short SHA, or full SHA.

        First tries exactly what was supplied.

        Example:
            main

        If that fails, tries:

            origin/main
        """

        if not revision:
            raise ValueError(
                "Commit ID cannot be empty."
            )

        revision = revision.strip()

        # First try exactly what was supplied.
        try:
            return self._run_git([
                "rev-parse",
                f"{revision}^{{commit}}",
            ])

        except RuntimeError as first_error:

            # If caller already supplied origin/...,
            # don't create origin/origin/...
            if revision.startswith(
                "origin/"
            ):
                raise first_error

            remote_revision = (
                f"origin/{revision}"
            )

            try:
                return self._run_git([
                    "rev-parse",
                    (
                        f"{remote_revision}"
                        f"^{{commit}}"
                    ),
                ])

            except RuntimeError:
                raise ValueError(
                    f"Unable to resolve Git revision "
                    f"'{revision}' or "
                    f"'{remote_revision}'."
                ) from first_error

    def _get_parent_commit(
        self,
        commit_sha: str,
    ) -> Optional[str]:
        """
        Return the first parent of a commit.

        Example:

            C1 -> C2 -> C3

        For C3:
            returns C2

        For the repository's initial commit:
            returns None

        For a merge commit, the first parent is used.
        This represents the branch state immediately
        before the merge commit.
        """

        if not commit_sha:
            raise ValueError(
                "Commit SHA cannot be empty."
            )

        # Example output:
        #
        # Normal commit:
        #   C3 C2
        #
        # Merge commit:
        #   C3 C2 OTHER_PARENT
        #
        # Initial commit:
        #   C1
        #
        output = self._run_git([
            "rev-list",
            "--parents",
            "-n",
            "1",
            commit_sha,
        ])

        if not output:
            return None

        parts = output.split()

        # Only the commit SHA itself means this
        # is the root/initial commit.
        if len(parts) < 2:
            return None

        # First parent.
        return parts[1]

    # ────────────────────────────────────────────────────────
    # Diff parsing
    # ────────────────────────────────────────────────────────

    def _parse_name_status(
        self,
        diff_output: str,
    ) -> List[dict]:
        """
        Parse output from:

            git diff --name-status
        """

        changes = []

        if not diff_output:
            return changes

        for line in diff_output.splitlines():

            parts = line.split(
                "\t"
            )

            if len(parts) < 2:
                continue

            raw_status = parts[0]

            if not raw_status:
                continue

            status_code = (
                raw_status[0]
            )

            change_type = (
                self.STATUS_MAP.get(
                    status_code,
                    "unknown",
                )
            )

            # Rename or copy.
            if status_code in {
                "R",
                "C",
            }:

                if len(parts) < 3:
                    continue

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
        Return actual added/deleted line ranges.

        This walks the diff body and records only
        lines prefixed with '+' or '-'.

        It does not consider the entire Git hunk
        to be modified code.
        """

        file_path = (
            change.get("new_path")
            or change.get("old_path")
        )

        if not file_path:
            return {
                "added_lines": [],
                "deleted_lines": [],
            }

        diff_output = self._run_git([
            "diff",
            "--unified=0",
            base_sha,
            target_sha,
            "--",
            file_path,
        ])

        added_line_numbers = []
        deleted_line_numbers = []

        old_line = None
        new_line = None

        for line in diff_output.splitlines():

            # Start of a Git diff hunk.
            if line.startswith("@@"):

                (
                    old_start,
                    _old_count,
                    new_start,
                    _new_count,
                ) = self._parse_hunk_header(
                    line
                )

                old_line = old_start
                new_line = new_start

                continue

            # Ignore diff file-header lines.
            if (
                line.startswith("---")
                or line.startswith("+++")
            ):
                continue

            # Ignore everything before a valid hunk.
            if (
                old_line is None
                or new_line is None
            ):
                continue

            # Added line exists in target.
            if line.startswith("+"):

                added_line_numbers.append(
                    new_line
                )

                new_line += 1

            # Deleted line existed in base.
            elif line.startswith("-"):

                deleted_line_numbers.append(
                    old_line
                )

                old_line += 1

            # Context line exists in both.
            else:

                old_line += 1
                new_line += 1

        return {
            "added_lines":
                self._group_line_numbers(
                    added_line_numbers
                ),
            "deleted_lines":
                self._group_line_numbers(
                    deleted_line_numbers
                ),
        }

    def _group_line_numbers(
        self,
        line_numbers: List[int],
    ) -> List[list]:
        """
        Convert individual line numbers into
        contiguous ranges.

        Example:

            [4, 5, 6, 10, 11]

        becomes:

            [
                [4, 6],
                [10, 11]
            ]
        """

        if not line_numbers:
            return []

        ranges = []

        start = line_numbers[0]
        previous = line_numbers[0]

        for line_number in (
            line_numbers[1:]
        ):

            if (
                line_number
                == previous + 1
            ):
                previous = line_number
                continue

            ranges.append([
                start,
                previous,
            ])

            start = line_number
            previous = line_number

        ranges.append([
            start,
            previous,
        ])

        return ranges

    def _parse_hunk_header(
        self,
        header: str,
    ):
        """
        Parse a Git diff hunk header.

        Example:

            @@ -27,7 +34,32 @@

        Returns:

            old_start
            old_count
            new_start
            new_count
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
        Parse Git diff ranges such as:

            -27,7
            +34,32
            +10
            -0,0
        """

        value = value[1:]

        if "," in value:

            start, count = value.split(
                ",",
                1,
            )

        else:

            start = value
            count = 1

        return (
            int(start),
            int(count),
        )

    # ────────────────────────────────────────────────────────
    # Filtering
    # ────────────────────────────────────────────────────────

    def _is_sensitive(
        self,
        file_path: str,
    ) -> bool:
        """
        Check whether a path matches one of
        the configured sensitive-file patterns.
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