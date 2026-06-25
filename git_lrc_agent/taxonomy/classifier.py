"""Post-LLM classifier that validates and corrects issue categorization.

The LLM is asked to classify issues directly, but sometimes returns
invalid or missing categories. This module provides a deterministic
fallback classifier that uses keyword matching against the issue title
and message to assign the correct (pillar, category, pattern) triple.
"""

from __future__ import annotations

import re
from typing import Optional

from git_lrc_agent.output.structured_output import ReviewIssue, Severity
from git_lrc_agent.taxonomy.taxonomy import (
    ALL_PILLARS,
    CATEGORY_BY_NAME,
    PATTERN_BY_NAME,
    validate_classification,
)


def classify_issue(issue: ReviewIssue) -> ReviewIssue:
    """Validate and correct the classification of a single issue.

    If the LLM-provided (pillar, category, pattern) is valid in the
    taxonomy, it is kept as-is. Otherwise, keyword matching is used to
    find the best-fit classification.

    This mutates and returns the same ReviewIssue instance.
    """
    # Step 1: Try to validate the LLM-provided classification directly.
    pillar, category, pattern = validate_classification(
        issue.pillar, issue.category, issue.pattern,
    )

    # Step 2: If the classification changed (i.e., was invalid), try
    # keyword matching for a better fit.
    if (pillar, category, pattern) != (issue.pillar, issue.category, issue.pattern):
        kw_result = _keyword_classify(issue.title, issue.message)
        if kw_result is not None:
            pillar, category, pattern = kw_result

    issue.pillar = pillar
    issue.category = category
    issue.pattern = pattern

    return issue


def classify_issues(issues: list[ReviewIssue]) -> list[ReviewIssue]:
    """Validate and correct classification for a batch of issues."""
    return [classify_issue(issue) for issue in issues]


# ---------------------------------------------------------------------------
# Keyword-based fallback classifier
# ---------------------------------------------------------------------------

def _keyword_classify(
    title: str,
    message: str,
) -> Optional[tuple[str, str, str]]:
    """Match issue text against pattern keywords.

    Scans all patterns across all pillars/categories. Returns the best
    match by keyword hit count, or None if no keyword matches.
    """
    text = f"{title} {message}".lower()

    best_match: Optional[tuple[str, str, str]] = None
    best_score = 0

    for pillar in ALL_PILLARS:
        for category in pillar.categories:
            for pattern in category.patterns:
                score = _compute_keyword_score(text, pattern.keywords)
                if score > best_score:
                    best_score = score
                    best_match = (pillar.name, category.name, pattern.name)

    # Require at least 1 keyword hit.
    if best_score >= 1:
        return best_match
    return None


def _compute_keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    """Count how many keywords appear in the text with word boundaries.

    Uses word-boundary-aware matching so 'auth' doesn't match 'author',
    but does match 'authentication', 'auth-token', etc.

    Underscore variations get partial credit (0.5 per hit). The final
    score is rounded up via ``math.ceil`` so a single partial still
    contributes 1 to the total.
    """
    import math

    score: float = 0
    text_lower = text.lower()

    for kw in keywords:
        kw_lower = kw.lower()
        # Use word boundary regex for more precise matching
        pattern = r'\b' + re.escape(kw_lower) + r'\b'
        if re.search(pattern, text_lower):
            score += 1
        # Partial credit for underscore variations (e.g., 'sql_inject' -> 'sql injection')
        elif '_' in kw_lower and kw_lower.replace('_', '') in text_lower.replace('_', ''):
            score += 0.5

    return math.ceil(score)
