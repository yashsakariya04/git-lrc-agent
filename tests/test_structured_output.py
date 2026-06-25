"""Tests for the structured output models and converter."""

import json
from datetime import datetime, timezone

import pytest
from git_lrc_agent.output.structured_output import (
    ReviewIssue,
    ReviewSummary,
    SecurityFinding,
    StructuredReview,
    FileSummary,
    Severity,
    Pillar,
    convert_pr_agent_output,
    SEVERITY_WEIGHTS,
)


class TestReviewIssue:
    def test_auto_id_generation(self):
        issue = ReviewIssue(
            file="test.py", line_start=10, line_end=15,
            pillar="Outages", category="Reliability", pattern="Error Handling",
            severity="high", title="Missing error handling", message="No try-except.",
        )
        assert len(issue.id) == 12
        assert issue.id.isalnum()

    def test_deterministic_id(self):
        """Same inputs should produce the same ID."""
        kwargs = dict(
            file="test.py", line_start=10, line_end=15,
            pillar="Outages", category="Reliability", pattern="Error Handling",
            severity="high", title="Missing error handling", message="No try-except.",
        )
        a = ReviewIssue(**kwargs)
        b = ReviewIssue(**kwargs)
        assert a.id == b.id

    def test_explicit_id_preserved(self):
        issue = ReviewIssue(
            id="custom123",
            file="test.py", line_start=1, line_end=1,
            pillar="Outages", category="Reliability", pattern="Error Handling",
            severity="info", title="Test", message="Test",
        )
        assert issue.id == "custom123"


class TestStructuredReview:
    def _make_review(self) -> StructuredReview:
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=5,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="critical", title="Critical bug", message="Crash risk.",
            ),
            ReviewIssue(
                file="a.py", line_start=10, line_end=12,
                pillar="Breaches", category="Security", pattern="Secrets Management",
                severity="high", title="Leaked key", message="API key in code.",
            ),
            ReviewIssue(
                file="b.py", line_start=20, line_end=25,
                pillar="Technical Debt", category="Maintainability", pattern="Code Complexity",
                severity="medium", title="Complex function", message="Too many branches.",
            ),
        ]
        review = StructuredReview(
            issues=issues,
            files=[
                FileSummary(filename="a.py", lines_added=50, lines_removed=10),
                FileSummary(filename="b.py", lines_added=20, lines_removed=5),
            ],
        )
        review.compute_summary()
        return review

    def test_risk_score_computation(self):
        review = self._make_review()
        # critical=25, high=15, medium=5 → total=45
        assert review.summary.risk_score == 45

    def test_risk_score_capped_at_100(self):
        issues = [
            ReviewIssue(
                file="x.py", line_start=1, line_end=1,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="critical", title=f"Issue {i}", message=".",
            )
            for i in range(10)  # 10 × 25 = 250, should cap at 100
        ]
        review = StructuredReview(issues=issues)
        review.compute_summary()
        assert review.summary.risk_score == 100

    def test_summary_counts(self):
        review = self._make_review()
        s = review.summary
        assert s.total_issues == 3
        assert s.issues_by_pillar["Outages"] == 1
        assert s.issues_by_severity["critical"] == 1
        assert s.issues_by_category["Reliability"] == 1

    def test_top_issues_ordered_by_severity(self):
        review = self._make_review()
        top = review.summary.top_issues
        assert top[0].severity == Severity.CRITICAL
        assert top[1].severity == Severity.HIGH
        # All 3 issues should be included (max_issues_to_show defaults to 50)
        assert len(top) == 3

    def test_file_hotspots(self):
        review = self._make_review()
        hotspots = review.summary.file_hotspots
        assert hotspots[0].filename == "a.py"  # 2 issues
        assert hotspots[0].issue_count == 2

    def test_serialization_roundtrip(self):
        review = self._make_review()
        json_str = review.to_json()
        parsed = json.loads(json_str)
        assert parsed["summary"]["total_issues"] == 3
        assert parsed["summary"]["max_issues_to_show"] == 50
        assert "issues_by_line" in parsed["summary"]

    def test_fix_time_estimate(self):
        review = self._make_review()
        # critical=120, high=60, medium=30 → 210
        assert review.summary.estimated_fix_time_minutes == 210


class TestEnhancedFeatures:
    """Tests for Priority 1 enhancements: new fields, configurable limits, line map."""

    def test_review_issue_new_fields_defaults(self):
        """New fields should have safe defaults."""
        issue = ReviewIssue(
            file="test.py", line_start=1, line_end=1,
            pillar="Outages", category="Reliability", pattern="Error Handling",
            severity="info", title="Test", message="Test",
        )
        assert issue.function_name is None
        assert issue.context_lines is None
        assert issue.fix_confidence == 50
        assert issue.tags == []

    def test_review_issue_new_fields_populated(self):
        """New fields should be settable."""
        issue = ReviewIssue(
            file="test.py", line_start=1, line_end=5,
            pillar="Breaches", category="Security", pattern="Authentication",
            severity="high", title="Weak auth", message="No password validation.",
            function_name="login",
            context_lines=["def login():", "  password = input()"],
            fix_confidence=85,
            tags=["security"],
        )
        assert issue.function_name == "login"
        assert len(issue.context_lines) == 2
        assert issue.fix_confidence == 85
        assert "security" in issue.tags

    def test_file_summary_patch_serialization(self):
        """FileSummary patch field should serialize and deserialize correctly."""
        fs = FileSummary(filename="a.py", patch="diff content")
        assert fs.patch == "diff content"
        
        review = StructuredReview(
            files=[fs],
            issues=[]
        )
        json_str = review.to_json()
        deserialized = StructuredReview.model_validate_json(json_str)
        assert deserialized.files[0].patch == "diff content"

    def test_max_issues_to_show_configurable(self):
        """ReviewSummary.max_issues_to_show should be configurable."""
        summary = ReviewSummary(max_issues_to_show=10)
        assert summary.max_issues_to_show == 10

    def test_compute_summary_respects_max_issues(self):
        """compute_summary() should limit top_issues to max_issues."""
        issues = [
            ReviewIssue(
                file="x.py", line_start=i, line_end=i,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="medium", title=f"Issue {i}", message=".",
            )
            for i in range(10)
        ]
        review = StructuredReview(issues=issues)
        review.compute_summary(max_issues=5)
        assert len(review.summary.top_issues) == 5
        assert review.summary.total_issues == 10

    def test_compute_summary_default_shows_all(self):
        """With default max_issues_to_show=50, all issues under 50 should appear."""
        issues = [
            ReviewIssue(
                file="x.py", line_start=i, line_end=i,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="low", title=f"Issue {i}", message=".",
            )
            for i in range(20)
        ]
        review = StructuredReview(issues=issues)
        review.compute_summary()
        assert len(review.summary.top_issues) == 20

    def test_issues_by_line_map(self):
        """compute_summary() should build a file:line -> [issue_ids] map."""
        issues = [
            ReviewIssue(
                file="a.py", line_start=10, line_end=15,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="high", title="Issue A", message=".",
            ),
            ReviewIssue(
                file="a.py", line_start=10, line_end=12,
                pillar="Breaches", category="Security", pattern="Secrets Management",
                severity="critical", title="Issue B", message=".",
            ),
            ReviewIssue(
                file="b.py", line_start=5, line_end=5,
                pillar="Technical Debt", category="Maintainability", pattern="Code Complexity",
                severity="low", title="Issue C", message=".",
            ),
        ]
        review = StructuredReview(issues=issues)
        review.compute_summary()

        line_map = review.summary.issues_by_line
        assert "a.py:10" in line_map
        assert len(line_map["a.py:10"]) == 2  # Both issues on same line
        assert "b.py:5" in line_map
        assert len(line_map["b.py:5"]) == 1

    def test_convert_pr_agent_auto_tags(self):
        """convert_pr_agent_output should auto-tag based on category."""
        yaml_data = {
            "review": {
                "issues": [
                    {
                        "file": "a.py", "line_start": 1, "line_end": 1,
                        "pillar": "Breaches", "category": "Security",
                        "pattern": "Authentication", "severity": "high",
                        "title": "Weak auth", "message": "Missing validation.",
                    },
                    {
                        "file": "b.py", "line_start": 1, "line_end": 1,
                        "pillar": "Outages", "category": "Performance",
                        "pattern": "N+1 Queries", "severity": "medium",
                        "title": "Slow query", "message": "N+1 detected.",
                    },
                    {
                        "file": "c.py", "line_start": 1, "line_end": 1,
                        "pillar": "Technical Debt", "category": "Maintainability",
                        "pattern": "Code Complexity", "severity": "low",
                        "title": "Complex", "message": "Too complex.",
                    },
                ]
            }
        }
        review = convert_pr_agent_output(yaml_data)
        assert "security" in review.issues[0].tags
        assert "performance" in review.issues[1].tags
        assert "maintainability" in review.issues[2].tags

    def test_convert_pr_agent_new_fields(self):
        """convert_pr_agent_output should pass through function_name and fix_confidence."""
        yaml_data = {
            "review": {
                "issues": [
                    {
                        "file": "a.py", "line_start": 1, "line_end": 5,
                        "pillar": "Outages", "category": "Reliability",
                        "pattern": "Error Handling", "severity": "high",
                        "title": "No try-except", "message": "Missing error handler.",
                        "function_name": "process_data",
                        "fix_confidence": 90,
                    }
                ]
            }
        }
        review = convert_pr_agent_output(yaml_data)
        assert review.issues[0].function_name == "process_data"
        assert review.issues[0].fix_confidence == 90


class TestConvertPrAgentOutput:
    def test_new_format(self):
        yaml_data = {
            "review": {
                "summary": "Test review",
                "risk_score": 42,
                "issues": [
                    {
                        "file": "test.py",
                        "line_start": 5,
                        "line_end": 10,
                        "pillar": "Outages",
                        "category": "Correctness",
                        "pattern": "Logic Errors",
                        "severity": "high",
                        "title": "Wrong condition",
                        "message": "The if-condition is inverted.",
                        "suggestion": "Swap the condition.",
                    }
                ],
            }
        }
        review = convert_pr_agent_output(yaml_data, commit_sha="abc123")
        assert review.summary.total_issues == 1
        assert review.issues[0].category == "Correctness"
        assert review.commit_sha == "abc123"

    def test_legacy_format(self):
        yaml_data = {
            "review": {
                "key_issues_to_review": [
                    {
                        "relevant_file": "legacy.py",
                        "start_line": 1,
                        "end_line": 3,
                        "issue_header": "Possible Bug",
                        "issue_content": "Something is wrong.",
                    }
                ],
                "security_concerns": "No",
            }
        }
        review = convert_pr_agent_output(yaml_data)
        assert review.summary.total_issues == 1
        assert review.issues[0].title == "Possible Bug"
        # Defaults for missing fields.
        assert review.issues[0].pillar == "Technical Debt"
        assert review.issues[0].severity == Severity.MEDIUM

    def test_security_concerns_string(self):
        yaml_data = {
            "review": {
                "key_issues_to_review": [],
                "security_concerns": "Hardcoded API key found in config.py.",
            }
        }
        review = convert_pr_agent_output(yaml_data)
        assert len(review.security_findings) == 1
        assert review.security_findings[0].severity == Severity.HIGH

    def test_empty_review(self):
        review = convert_pr_agent_output({})
        assert review.summary.total_issues == 0

    def test_none_review(self):
        review = convert_pr_agent_output(None)
        assert review.summary.total_issues == 0


def test_fix_yaml_unquoted_colons():
    from pr_agent.algo.utils import fix_yaml_unquoted_colons
    bad_yaml = """
review:
  estimated_effort_to_review_[1-5]: 5
  key_issues_to_review:
    - relevant_file: src/scraper_integration.py
      issue_content: |
        Some description with colon: inside it.
  security_concerns: Sensitive information exposure: The WebScraper class has a hardcoded URL.
"""
    fixed = fix_yaml_unquoted_colons(bad_yaml)
    assert 'security_concerns: "Sensitive information exposure: The WebScraper class has a hardcoded URL."' in fixed
    assert "Some description with colon: inside it." in fixed
