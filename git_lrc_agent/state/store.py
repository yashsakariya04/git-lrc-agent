"""Review state storage in ``.git/lrc/``.

Persists reviews as JSON files and provides query capabilities:
  • Save / load individual reviews
  • List review history with pagination
  • Compare two reviews (diff of issues)
  • Auto-prune old reviews
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from git_lrc_agent.output.structured_output import StructuredReview, ReviewIssue


class ReviewStore:
    """Manages review state in ``.git/lrc/reviews/``."""

    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)
        self.reviews_dir = self.repo_path / ".git" / "lrc" / "reviews"
        self.state_file = self.repo_path / ".git" / "lrc" / "state.json"

    def _ensure_dir(self) -> None:
        self.reviews_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save_review(self, review: StructuredReview) -> Path:
        """Save a review and return the file path."""
        self._ensure_dir()
        path = self.reviews_dir / f"{review.id}.json"
        review.save(path)
        self._update_state(review)
        return path

    def get_review(self, review_id: str) -> Optional[StructuredReview]:
        """Load a review by its ID."""
        path = self.reviews_dir / f"{review_id}.json"
        if not path.exists():
            return None
        return StructuredReview.load(path)

    def get_latest_review(self) -> Optional[StructuredReview]:
        """Return the most recent review."""
        files = self._sorted_review_files()
        if not files:
            return None
        return StructuredReview.load(files[0])

    def get_review_history(self, limit: int = 10) -> list[StructuredReview]:
        """Return the N most recent reviews."""
        files = self._sorted_review_files()[:limit]
        reviews = []
        for f in files:
            try:
                reviews.append(StructuredReview.load(f))
            except Exception:
                continue
        return reviews

    def delete_review(self, review_id: str) -> bool:
        """Delete a single review."""
        path = self.reviews_dir / f"{review_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_reviews(
        self,
        old_id: str,
        new_id: str,
    ) -> dict:
        """Compare two reviews and return a diff summary.

        Returns a dict with:
          - ``new_issues``: issues in new but not in old
          - ``resolved_issues``: issues in old but not in new
          - ``persistent_issues``: issues in both
        """
        old = self.get_review(old_id)
        new = self.get_review(new_id)
        if old is None or new is None:
            raise ValueError("Both review IDs must exist.")

        old_ids = {i.id for i in old.issues}
        new_ids = {i.id for i in new.issues}

        new_issue_map = {i.id: i for i in new.issues}
        old_issue_map = {i.id: i for i in old.issues}

        return {
            "new_issues": [new_issue_map[iid] for iid in (new_ids - old_ids)],
            "resolved_issues": [old_issue_map[iid] for iid in (old_ids - new_ids)],
            "persistent_issues": [new_issue_map[iid] for iid in (old_ids & new_ids)],
        }

    # ------------------------------------------------------------------
    # State tracking
    # ------------------------------------------------------------------

    def get_iteration_count(self) -> int:
        """Return the current iteration count for this staged diff."""
        state = self._load_state()
        return state.get("iteration", 0)

    def increment_iteration(self) -> int:
        """Increment and return the iteration counter."""
        state = self._load_state()
        state["iteration"] = state.get("iteration", 0) + 1
        self._save_state(state)
        return state["iteration"]

    def reset_iteration(self) -> None:
        """Reset iteration count (e.g., after a commit)."""
        state = self._load_state()
        state["iteration"] = 0
        self._save_state(state)

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune(self, max_age_days: int = 30) -> int:
        """Delete reviews older than ``max_age_days``.  Returns count deleted."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        deleted = 0
        for f in self.reviews_dir.glob("*.json"):
            try:
                review = StructuredReview.load(f)
                if review.timestamp < cutoff:
                    f.unlink()
                    deleted += 1
            except Exception:
                continue
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sorted_review_files(self) -> list[Path]:
        """Return review files sorted by modification time (newest first)."""
        if not self.reviews_dir.exists():
            return []
        return sorted(
            self.reviews_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _load_state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        return {}

    def _save_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )

    def _update_state(self, review: StructuredReview) -> None:
        """Update state.json with the latest review metadata."""
        state = self._load_state()
        state["last_review_id"] = review.id
        state["last_review_status"] = review.status
        state["last_review_timestamp"] = review.timestamp.isoformat()
        state["iteration"] = review.iteration
        self._save_state(state)
