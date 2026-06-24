"""Staged-diff Git provider for commit-time reviews.

Unlike PR-Agent's LocalGitProvider (which compares branches and requires
a clean working tree), this provider reviews **staged changes only**
(``git diff --cached``).  It is designed to be called from a pre-commit
hook and works in dirty working directories.

Integration note
~~~~~~~~~~~~~~~~
This module imports PR-Agent types directly.  Add ``pr-agent`` to the
Python path or install it as a dependency before importing this module.
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import List, Optional

from git import Repo

from pr_agent.algo.types import EDIT_TYPE, FilePatchInfo
from pr_agent.git_providers.git_provider import GitProvider
from pr_agent.log import get_logger


# ---------------------------------------------------------------------------
# PullRequest mimic (reused from LocalGitProvider concept)
# ---------------------------------------------------------------------------

class _PullRequestMimic:
    """Mimics the PullRequest object expected by PR-Agent tools."""

    def __init__(self, title: str, diff_files: List[FilePatchInfo]):
        self.title = title
        self.diff_files = diff_files


# ---------------------------------------------------------------------------
# Main provider
# ---------------------------------------------------------------------------

class StagedDiffProvider(GitProvider):
    """GitProvider implementation that reviews staged (``--cached``) changes.

    Parameters
    ----------
    repo_path : str | Path | None
        Explicit path to the repository root.  If *None*, the provider
        walks up from *cwd* looking for a ``.git`` directory.
    """

    def __init__(self, repo_path: str | Path | None = None):
        self.repo_path = self._find_repo_root(repo_path)
        self.repo = Repo(str(self.repo_path))
        self.diff_files: list[FilePatchInfo] | None = None
        self.pr = _PullRequestMimic(
            title=self._build_title(),
            diff_files=self.get_diff_files(),
        )
        self._review_output: str = ""

    # ------------------------------------------------------------------
    # Repository discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _find_repo_root(hint: str | Path | None = None) -> Path:
        """Walk up from *hint* (or cwd) to find the repository root."""
        start = Path(hint) if hint else Path.cwd()
        current = start.resolve()
        while True:
            if (current / ".git").exists():
                return current
            parent = current.parent
            if parent == current:
                raise FileNotFoundError(
                    f"No git repository found starting from {start}"
                )
            current = parent

    # ------------------------------------------------------------------
    # Title / description helpers
    # ------------------------------------------------------------------

    def _build_title(self) -> str:
        """Build a human-readable title for the 'pseudo-PR'.

        Uses the current branch name + a summary of staged file count.
        """
        try:
            branch = self.repo.active_branch.name
        except TypeError:
            branch = "detached-HEAD"
        return f"[staged] {branch}"

    # ------------------------------------------------------------------
    # Core GitProvider interface
    # ------------------------------------------------------------------

    def is_supported(self, capability: str) -> bool:
        unsupported = {
            "get_issue_comments",
            "create_inline_comment",
            "publish_inline_comments",
            "get_labels",
            "gfm_markdown",
        }
        return capability not in unsupported

    def get_diff_files(self) -> list[FilePatchInfo]:
        """Return ``FilePatchInfo`` objects for every staged file.

        Equivalent to ``git diff --cached`` but parsed into the
        structure PR-Agent's review engine expects.
        """
        if self.diff_files is not None:
            return self.diff_files

        # Compare index (staged) against HEAD.
        # If HEAD does not exist (initial commit), compare against the
        # empty tree.
        try:
            head_commit = self.repo.head.commit
            diffs = self.repo.index.diff(head_commit, create_patch=True, R=True)
        except ValueError:
            # Initial commit — no HEAD yet.  Compare against empty tree.
            diffs = self.repo.index.diff(None, create_patch=True, R=True)

        diff_files: list[FilePatchInfo] = []
        for diff_item in diffs:
            # Original (base) file content — from HEAD.
            if diff_item.a_blob is not None:
                try:
                    original_content = diff_item.a_blob.data_stream.read().decode("utf-8")
                except UnicodeDecodeError:
                    continue  # skip binary files
            else:
                original_content = ""

            # New (head) file content — from the index (staging area).
            if diff_item.b_blob is not None:
                try:
                    new_content = diff_item.b_blob.data_stream.read().decode("utf-8")
                except UnicodeDecodeError:
                    continue  # skip binary files
            else:
                new_content = ""

            # Determine edit type.
            if diff_item.new_file:
                edit_type = EDIT_TYPE.ADDED
            elif diff_item.deleted_file:
                edit_type = EDIT_TYPE.DELETED
            elif diff_item.renamed_file:
                edit_type = EDIT_TYPE.RENAMED
            else:
                edit_type = EDIT_TYPE.MODIFIED

            # Decode patch bytes.
            try:
                patch_str = diff_item.diff.decode("utf-8")
            except (UnicodeDecodeError, AttributeError):
                patch_str = ""

            if not patch_str and edit_type != EDIT_TYPE.DELETED:
                continue  # nothing to review

            # Count +/- lines.
            num_plus = sum(1 for ln in patch_str.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
            num_minus = sum(1 for ln in patch_str.splitlines() if ln.startswith("-") and not ln.startswith("---"))

            diff_files.append(
                FilePatchInfo(
                    base_file=original_content,
                    head_file=new_content,
                    patch=patch_str,
                    filename=diff_item.b_path or diff_item.a_path,
                    edit_type=edit_type,
                    old_filename=(
                        diff_item.a_path
                        if diff_item.a_path != diff_item.b_path
                        else None
                    ),
                    num_plus_lines=num_plus,
                    num_minus_lines=num_minus,
                )
            )

        self.diff_files = diff_files
        return diff_files

    def get_files(self) -> List[str]:
        """Return list of staged file paths."""
        return [f.filename for f in self.get_diff_files()]

    # ------------------------------------------------------------------
    # Publishing — write to local files / in-memory buffer
    # ------------------------------------------------------------------

    def publish_description(self, pr_title: str, pr_body: str):
        """Write description to the lrc output directory."""
        out = self._lrc_dir() / "description.md"
        out.write_text(f"{pr_title}\n{pr_body}", encoding="utf-8")

    def publish_comment(self, pr_comment: str, is_temporary: bool = False):
        """Store review markdown for the dashboard to read."""
        self._review_output = pr_comment
        out = self._lrc_dir() / "review.md"
        out.write_text(pr_comment, encoding="utf-8")

    def publish_inline_comment(self, body, relevant_file, relevant_line_in_file, original_suggestion=None):
        pass  # Inline comments are rendered by the dashboard, not the git provider.

    def publish_inline_comments(self, comments: list[dict]):
        pass  # Same as above — handled by the dashboard.

    def publish_code_suggestions(self, code_suggestions: list) -> bool:
        return False  # Not applicable; suggestions are in the structured JSON.

    def publish_labels(self, labels):
        pass

    def remove_initial_comment(self):
        pass

    def remove_comment(self, comment):
        pass

    def add_eyes_reaction(self, issue_comment_id: int, disable_eyes: bool = False):
        return None

    def remove_reaction(self, issue_comment_id: int, reaction_id: int) -> bool:
        return False

    def get_commit_messages(self):
        """Return recent commit messages for context."""
        try:
            commits = list(self.repo.iter_commits("HEAD", max_count=5))
            return "\n".join(c.message.strip() for c in commits)
        except Exception:
            return ""

    def get_repo_settings(self):
        """Look for .pr_agent.toml in the repository root."""
        settings_path = self.repo_path / ".pr_agent.toml"
        if settings_path.exists():
            return settings_path.read_text(encoding="utf-8")
        return None

    def get_languages(self):
        """Calculate language distribution from the repository tree."""
        try:
            filepaths = [
                Path(item.path)
                for item in self.repo.tree().traverse()
                if item.type == "blob"
            ]
            lang_count = Counter(
                fp.suffix.lstrip(".").lower()
                for fp in filepaths
                if fp.suffix
            )
            total = len(filepaths) or 1
            return {lang: count / total * 100 for lang, count in lang_count.items()}
        except Exception:
            return {}

    def get_pr_branch(self):
        try:
            return self.repo.active_branch.name
        except TypeError:
            return "HEAD"

    def get_user_id(self):
        return -1

    def get_pr_description_full(self) -> str:
        """Use recent commit messages as a stand-in for PR description."""
        return self.get_commit_messages()[:400]

    def get_issue_comments(self):
        return []

    def get_pr_labels(self, update=False):
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lrc_dir(self) -> Path:
        """Return (and create) the ``.git/lrc/`` directory."""
        lrc = self.repo_path / ".git" / "lrc"
        lrc.mkdir(parents=True, exist_ok=True)
        return lrc

    def get_staged_file_count(self) -> int:
        """How many files are staged."""
        return len(self.get_diff_files())

    def get_total_lines_changed(self) -> tuple[int, int]:
        """Return (lines_added, lines_removed) across all staged files."""
        added = sum(f.num_plus_lines for f in self.get_diff_files() if f.num_plus_lines > 0)
        removed = sum(f.num_minus_lines for f in self.get_diff_files() if f.num_minus_lines > 0)
        return added, removed
