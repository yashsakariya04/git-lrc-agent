"""Severity scoring and normalisation utilities.

Provides logic for:
  • Normalising LLM-provided severity strings to valid enum values
  • Adjusting severity based on category (e.g., Security → bump to high)
  • Computing aggregated risk scores from a set of issues
"""

from __future__ import annotations

from git_lrc_agent.output.structured_output import (
    ReviewIssue,
    Severity,
    SEVERITY_WEIGHTS,
    FIX_TIME_MINUTES,
)


# Categories where severity should be bumped upward if too low.
_SEVERITY_FLOOR: dict[str, Severity] = {
    "Security": Severity.HIGH,
    "Compliance & Governance": Severity.MEDIUM,
    "Reliability": Severity.MEDIUM,
    "Correctness": Severity.MEDIUM,
}

# Patterns that should always be critical regardless of LLM output.
_ALWAYS_CRITICAL_PATTERNS = frozenset({
    "Secrets Management",
    "Injection Vulnerabilities",
    "Authentication",
})


def normalise_severity(raw: str) -> Severity:
    """Convert a raw severity string from LLM output to a valid enum.

    Handles common variations like 'Critical', 'CRITICAL', 'crit', 'warn',
    'warning', 'important', etc.
    """
    raw = raw.strip().lower()

    severity_map = {
        "critical": Severity.CRITICAL,
        "crit": Severity.CRITICAL,
        "severe": Severity.CRITICAL,
        "high": Severity.HIGH,
        "important": Severity.HIGH,
        "major": Severity.HIGH,
        "warning": Severity.MEDIUM,
        "warn": Severity.MEDIUM,
        "medium": Severity.MEDIUM,
        "moderate": Severity.MEDIUM,
        "low": Severity.LOW,
        "minor": Severity.LOW,
        "trivial": Severity.LOW,
        "info": Severity.INFO,
        "informational": Severity.INFO,
        "note": Severity.INFO,
        "suggestion": Severity.INFO,
    }

    return severity_map.get(raw, Severity.MEDIUM)


def adjust_severity(issue: ReviewIssue) -> ReviewIssue:
    """Apply severity floor rules based on category and pattern.

    This ensures that security issues are never marked as 'info' and
    that known-critical patterns (like hardcoded secrets) are always
    flagged as critical.
    """
    severity_order = [
        Severity.INFO,
        Severity.LOW,
        Severity.MEDIUM,
        Severity.HIGH,
        Severity.CRITICAL,
    ]

    # Always-critical patterns override everything.
    if issue.pattern in _ALWAYS_CRITICAL_PATTERNS:
        issue.severity = Severity.CRITICAL
        return issue

    # Apply severity floor for certain categories.
    floor = _SEVERITY_FLOOR.get(issue.category)
    if floor is not None:
        current_idx = severity_order.index(issue.severity)
        floor_idx = severity_order.index(floor)
        if current_idx < floor_idx:
            issue.severity = floor

    return issue


def compute_risk_score(issues: list[ReviewIssue]) -> int:
    """Compute a 0–100 risk score from a set of issues.

    Uses the SEVERITY_WEIGHTS defined in structured_output.py.
    """
    raw = sum(SEVERITY_WEIGHTS.get(i.severity, 0) for i in issues)
    return min(100, raw)


def estimate_fix_time(issues: list[ReviewIssue]) -> int:
    """Estimate total fix time in minutes based on issue severities."""
    return sum(FIX_TIME_MINUTES.get(i.severity, 0) for i in issues)
