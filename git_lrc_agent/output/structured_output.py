"""Structured output models for git-lrc-agent review results.

Every issue found by the review engine is serialized into a ReviewIssue
instance. A full review session is captured as a StructuredReview, which
is the canonical data structure consumed by the dashboard, state tracker,
and all downstream features.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Pillar(str, Enum):
    OUTAGES = "Outages"
    BREACHES = "Breaches"
    TECHNICAL_DEBT = "Technical Debt"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Severity weights used for risk-score computation and fix-time estimates.
SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 15,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
    Severity.INFO: 0,
}

# Heuristic fix-time estimates (in minutes) per severity.
FIX_TIME_MINUTES: dict[Severity, int] = {
    Severity.CRITICAL: 120,
    Severity.HIGH: 60,
    Severity.MEDIUM: 30,
    Severity.LOW: 10,
    Severity.INFO: 0,
}


# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------

class ReviewIssue(BaseModel):
    """A single issue identified during code review."""

    id: str = Field(
        default="",
        description="Unique identifier (auto-generated if empty).",
    )
    file: str = Field(
        ...,
        description="Path to the file containing the issue.",
    )
    line_start: int = Field(
        ...,
        description="Start line of the problematic code (1-indexed).",
    )
    line_end: int = Field(
        ...,
        description="End line of the problematic code (1-indexed).",
    )
    pillar: Literal["Outages", "Breaches", "Technical Debt"] = Field(
        ...,
        description="Top-level risk pillar.",
    )
    category: str = Field(
        ...,
        description="Risk category within the pillar (e.g. 'Reliability').",
    )
    pattern: str = Field(
        ...,
        description="Specific failure pattern (e.g. 'Error Handling').",
    )
    severity: Severity = Field(
        ...,
        description="Issue severity level.",
    )
    title: str = Field(
        ...,
        description="Short, human-readable title for the issue.",
    )
    message: str = Field(
        ...,
        description="Detailed explanation of why this is risky.",
    )
    suggestion: Optional[str] = Field(
        default=None,
        description="Concrete fix recommendation (with code if applicable).",
    )
    code_snippet: Optional[str] = Field(
        default=None,
        description="The problematic code extracted from the diff.",
    )
    diff_hunk: Optional[str] = Field(
        default=None,
        description="Full diff context surrounding the issue.",
    )
    # Enhanced context fields for better code understanding
    function_name: Optional[str] = Field(
        default=None,
        description="Name of the function/method containing the issue.",
    )
    context_lines: Optional[list[str]] = Field(
        default=None,
        description="3-5 lines of surrounding code for context.",
    )
    fix_confidence: int = Field(
        default=50,
        ge=0,
        le=100,
        description="Confidence in the suggested fix (0-100%).",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags: 'security', 'performance', 'maintainability', etc.",
    )

    def model_post_init(self, __context) -> None:
        """Auto-generate a deterministic ID if one was not provided."""
        if not self.id:
            raw = f"{self.file}:{self.line_start}:{self.line_end}:{self.title}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:12]


class SecurityFinding(BaseModel):
    """A security-specific finding (subset of ReviewIssue)."""

    file: str
    line_start: int
    line_end: int
    pattern: str = Field(
        ...,
        description="Security pattern (e.g. 'Secrets Management').",
    )
    severity: Severity
    title: str
    message: str
    suggestion: Optional[str] = None


class FileSummary(BaseModel):
    """Per-file summary statistics."""

    filename: str
    lines_added: int = 0
    lines_removed: int = 0
    issue_count: int = 0
    max_severity: Optional[Severity] = None
    patch: Optional[str] = None


class ReviewSummary(BaseModel):
    """High-level overview of a completed review."""

    total_issues: int = 0
    issues_by_pillar: dict[str, int] = Field(default_factory=dict)
    issues_by_severity: dict[str, int] = Field(default_factory=dict)
    issues_by_category: dict[str, int] = Field(default_factory=dict)
    risk_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Weighted risk score (0 = clean, 100 = critical).",
    )
    # Configurable limit instead of hardcoded 3
    max_issues_to_show: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum issues to show in summary (configurable, was hardcoded 3).",
    )
    top_issues: list[ReviewIssue] = Field(
        default_factory=list,
        description="Most critical issues (up to max_issues_to_show).",
    )
    file_hotspots: list[FileSummary] = Field(
        default_factory=list,
        description="Files ranked by issue count.",
    )
    estimated_fix_time_minutes: int = 0
    prose_summary: str = ""
    # Quick lookup map for line-level issues
    issues_by_line: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of 'file:line_start' to issue IDs for quick lookup.",
    )


class StructuredReview(BaseModel):
    """Complete structured output for a single review session."""

    id: str = Field(default="", description="Review session ID.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    title: str = ""
    status: Literal["reviewed", "vouched", "skipped"] = "reviewed"
    iteration: int = 1
    coverage_pct: float = 0.0

    issues: list[ReviewIssue] = Field(default_factory=list)
    security_findings: list[SecurityFinding] = Field(default_factory=list)
    summary: ReviewSummary = Field(default_factory=ReviewSummary)
    files: list[FileSummary] = Field(default_factory=list)

    # Raw LLM output preserved for debugging.
    raw_llm_response: Optional[str] = None

    def model_post_init(self, __context) -> None:
        if not self.id:
            ts = self.timestamp.strftime("%Y%m%dT%H%M%S")
            sha = (self.commit_sha or "staged")[:8]
            self.id = f"{ts}_{sha}"

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def compute_summary(self, max_issues: int | None = None) -> None:
        """Populate the summary from the issues list.

        Parameters
        ----------
        max_issues
            Override the max number of top issues to include.
            If None, uses summary.max_issues_to_show (default 50).
        """
        s = self.summary
        s.total_issues = len(self.issues)

        # Use configurable max instead of hardcoded 3
        max_shown = max_issues if max_issues is not None else s.max_issues_to_show

        # Counts by pillar / severity / category
        s.issues_by_pillar = {}
        s.issues_by_severity = {}
        s.issues_by_category = {}
        for issue in self.issues:
            s.issues_by_pillar[issue.pillar] = s.issues_by_pillar.get(issue.pillar, 0) + 1
            s.issues_by_severity[issue.severity.value] = s.issues_by_severity.get(issue.severity.value, 0) + 1
            s.issues_by_category[issue.category] = s.issues_by_category.get(issue.category, 0) + 1

        # Risk score
        s.risk_score = min(
            100,
            sum(SEVERITY_WEIGHTS.get(i.severity, 0) for i in self.issues),
        )

        # Top N most critical issues (configurable, not hardcoded 3)
        severity_order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
        sorted_issues = sorted(
            self.issues,
            key=lambda i: severity_order.index(i.severity),
        )
        s.top_issues = sorted_issues[:max_shown]

        # Build line-by-line issue map for quick lookup
        s.issues_by_line = {}
        for issue in self.issues:
            key = f"{issue.file}:{issue.line_start}"
            if key not in s.issues_by_line:
                s.issues_by_line[key] = []
            s.issues_by_line[key].append(issue.id)

        # File hotspots
        file_issue_counts: dict[str, list[ReviewIssue]] = {}
        for issue in self.issues:
            file_issue_counts.setdefault(issue.file, []).append(issue)

        s.file_hotspots = []
        for filename, file_issues in sorted(
            file_issue_counts.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        ):
            max_sev = min(
                (i.severity for i in file_issues),
                key=lambda sv: severity_order.index(sv),
            )
            # Find matching FileSummary for lines added/removed
            matching_file = next((f for f in self.files if f.filename == filename), None)
            s.file_hotspots.append(FileSummary(
                filename=filename,
                lines_added=matching_file.lines_added if matching_file else 0,
                lines_removed=matching_file.lines_removed if matching_file else 0,
                issue_count=len(file_issues),
                max_severity=max_sev,
            ))

        # Fix time estimate
        s.estimated_fix_time_minutes = sum(
            FIX_TIME_MINUTES.get(i.severity, 0) for i in self.issues
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=indent)

    def save(self, path: Path) -> Path:
        """Write JSON to a file, creating parent dirs as needed."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "StructuredReview":
        """Load a StructuredReview from a JSON file."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Converter: PR-Agent YAML dict → StructuredReview
# ---------------------------------------------------------------------------

def convert_pr_agent_output(
    yaml_data: dict,
    *,
    commit_sha: str | None = None,
    branch: str | None = None,
    title: str = "",
    raw_response: str | None = None,
) -> StructuredReview:
    """Convert PR-Agent's parsed YAML review dict into a StructuredReview.

    This handles both the *new* extended schema (with pillar/category/pattern/
    severity) and the *legacy* PR-Agent schema (with issue_header/issue_content
    only), falling back to sensible defaults for missing fields.
    """
    if not isinstance(yaml_data, dict):
        yaml_data = {}
    review_data = yaml_data.get("review", {})
    issues: list[ReviewIssue] = []

    # --- Parse issues (new format: review.issues or legacy: review.key_issues_to_review) ---
    raw_issues = review_data.get("issues", review_data.get("key_issues_to_review", []))
    if isinstance(raw_issues, list):
        for raw in raw_issues:
            if not isinstance(raw, dict):
                continue
            try:
                # Auto-tag issues based on category
                category_val = raw.get("category", "Maintainability")
                tags = []
                if category_val == "Security":
                    tags.append("security")
                if category_val in ("Performance", "Scalability"):
                    tags.append("performance")
                if category_val in ("Maintainability", "Architecture", "Developer Experience"):
                    tags.append("maintainability")

                issues.append(ReviewIssue(
                    file=str(raw.get("file", raw.get("relevant_file", "unknown"))).strip(),
                    line_start=int(raw.get("line_start", raw.get("start_line", 0))),
                    line_end=int(raw.get("line_end", raw.get("end_line", 0))),
                    pillar=raw.get("pillar", "Technical Debt"),
                    category=category_val,
                    pattern=raw.get("pattern", "General"),
                    severity=raw.get("severity", "medium"),
                    title=str(raw.get("title", raw.get("issue_header", "Issue"))).strip(),
                    message=str(raw.get("message", raw.get("issue_content", ""))).strip(),
                    suggestion=raw.get("suggestion"),
                    code_snippet=raw.get("code_snippet"),
                    diff_hunk=raw.get("diff_hunk"),
                    function_name=raw.get("function_name"),
                    context_lines=raw.get("context_lines"),
                    fix_confidence=int(raw.get("fix_confidence", 50)),
                    tags=tags,
                ))
            except Exception:
                continue  # skip malformed issues

    # --- Parse security findings ---
    security_findings: list[SecurityFinding] = []
    raw_security = review_data.get("security_findings", [])
    if isinstance(raw_security, list):
        for raw in raw_security:
            if not isinstance(raw, dict):
                continue
            try:
                security_findings.append(SecurityFinding(
                    file=str(raw.get("file", "unknown")).strip(),
                    line_start=int(raw.get("line_start", 0)),
                    line_end=int(raw.get("line_end", 0)),
                    pattern=raw.get("pattern", "General"),
                    severity=raw.get("severity", "high"),
                    title=str(raw.get("title", "Security Issue")).strip(),
                    message=str(raw.get("message", "")).strip(),
                    suggestion=raw.get("suggestion"),
                ))
            except Exception:
                continue

    # Also convert legacy security_concerns string into a finding.
    security_str = review_data.get("security_concerns", "")
    if isinstance(security_str, str) and security_str.strip().lower() not in ("no", "none", ""):
        security_findings.append(SecurityFinding(
            file="(general)",
            line_start=0,
            line_end=0,
            pattern="General Security",
            severity=Severity.HIGH,
            title="Security Concern",
            message=security_str.strip(),
        ))

    review = StructuredReview(
        commit_sha=commit_sha,
        branch=branch,
        title=title,
        issues=issues,
        security_findings=security_findings,
        raw_llm_response=raw_response,
    )
    review.summary.prose_summary = str(review_data.get("summary", ""))
    review.summary.risk_score = int(review_data.get("risk_score", 0))
    review.compute_summary()
    return review
