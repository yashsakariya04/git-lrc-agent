"""Unit tests for Project Health Metrics implementation."""

import os
import sqlite3
import pytest
from pathlib import Path

from git_lrc_agent.metrics.models import HealthRating, ProjectHealthMetrics
from git_lrc_agent.metrics.calculator import MetricsCalculator
from git_lrc_agent.metrics.db import MetricsDB
from git_lrc_agent.output.structured_output import (
    ReviewIssue,
    StructuredReview,
    FileSummary,
    Severity,
)


@pytest.fixture
def temp_repo(tmp_path) -> Path:
    """Fixture to set up a mock git repository path."""
    repo = tmp_path / "mock-repo"
    repo.mkdir()
    return repo


class TestHealthModels:
    def test_health_rating_enum(self):
        assert HealthRating.A == "A"
        assert HealthRating.E == "E"

    def test_health_metrics_dataclass(self):
        metrics = ProjectHealthMetrics(
            bugs_count=2,
            vulnerabilities_count=0,
            code_smells_count=4,
            security_rating=HealthRating.A,
            maintainability_rating=HealthRating.B,
            reliability_rating=HealthRating.B,
            lines_of_code=150,
            technical_debt_minutes=90,
            open_issues_count=6,
            overall_health_score=82.5,
            quality_gates_status="PASS",
        )
        assert metrics.bugs_count == 2
        assert metrics.quality_status == "EXCELLENT"

        metrics.overall_health_score = 55.0
        assert metrics.quality_status == "ACCEPTABLE"


class TestMetricsCalculator:
    def _create_mock_review(self, issues: list[ReviewIssue], files: list[FileSummary] = None) -> StructuredReview:
        review = StructuredReview(
            issues=issues,
            files=files or [],
        )
        review.compute_summary()
        return review

    def test_issue_counting(self):
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=2,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="medium", title="Bug 1", message="."
            ),
            ReviewIssue(
                file="a.py", line_start=3, line_end=4,
                pillar="Outages", category="Correctness", pattern="Logic Errors",
                severity="high", title="Bug 2", message="."
            ),
            ReviewIssue(
                file="b.py", line_start=5, line_end=6,
                pillar="Breaches", category="Security", pattern="Secrets",
                severity="critical", title="Vuln 1", message="."
            ),
            ReviewIssue(
                file="c.py", line_start=10, line_end=12,
                pillar="Technical Debt", category="Maintainability", pattern="Complexity",
                severity="low", title="Smell 1", message="."
            ),
        ]
        review = self._create_mock_review(issues)
        calc = MetricsCalculator(review)

        assert calc._count_bugs() == 2
        assert calc._count_vulnerabilities() == 1
        assert calc._count_code_smells() == 1

    def test_security_rating_critical(self):
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=1,
                pillar="Breaches", category="Security", pattern="Secrets",
                severity="critical", title="Critical Vuln", message="."
            )
        ]
        review = self._create_mock_review(issues)
        calc = MetricsCalculator(review)
        assert calc._calculate_security_rating() == HealthRating.E

    def test_security_rating_multiple_high(self):
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=1,
                pillar="Breaches", category="Security", pattern="Secrets",
                severity="high", title="Vuln 1", message="."
            ),
            ReviewIssue(
                file="b.py", line_start=2, line_end=2,
                pillar="Breaches", category="Security", pattern="Secrets",
                severity="high", title="Vuln 2", message="."
            ),
        ]
        review = self._create_mock_review(issues)
        calc = MetricsCalculator(review)
        assert calc._calculate_security_rating() == HealthRating.D

    def test_maintainability_rating(self):
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=1,
                pillar="Technical Debt", category="Maintainability", pattern="Refactoring",
                severity="medium", title="Smell", message="."
            ),
            ReviewIssue(
                file="b.py", line_start=2, line_end=2,
                pillar="Outages", category="Correctness", pattern="Logic",
                severity="low", title="Not a smell", message="."
            ),
        ]
        review = self._create_mock_review(issues)
        calc = MetricsCalculator(review)
        # 1 smell out of 2 issues = 50% smell ratio -> D
        assert calc._calculate_maintainability_rating() == HealthRating.D

    def test_reliability_rating(self):
        # 3 bugs, 0 critical/high
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=1,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="medium", title="Bug 1", message="."
            ),
            ReviewIssue(
                file="b.py", line_start=2, line_end=2,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="low", title="Bug 2", message="."
            ),
            ReviewIssue(
                file="c.py", line_start=3, line_end=3,
                pillar="Outages", category="Reliability", pattern="Error Handling",
                severity="low", title="Bug 3", message="."
            ),
        ]
        review = self._create_mock_review(issues)
        calc = MetricsCalculator(review)
        # bugs count > 2, critical_high = 0 -> Rating C
        assert calc._calculate_reliability_rating() == HealthRating.C

    def test_calculate_loc(self):
        files = [
            FileSummary(filename="a.py", lines_added=50, lines_removed=10),
            FileSummary(filename="b.py", lines_added=120, lines_removed=25),
        ]
        review = self._create_mock_review(issues=[], files=files)
        calc = MetricsCalculator(review)
        assert calc._calculate_loc() == 170

    def test_evaluate_quality_gates_pass(self):
        review = self._create_mock_review([])
        calc = MetricsCalculator(review)
        assert calc._evaluate_quality_gates() == "PASS"

    def test_evaluate_quality_gates_fail_vulnerabilities(self):
        # 3 vulnerabilities exceeds limit of 2
        issues = [
            ReviewIssue(
                file="a.py", line_start=1, line_end=1,
                pillar="Breaches", category="Security", pattern="Secrets",
                severity="medium", title=f"Vuln {i}", message="."
            )
            for i in range(3)
        ]
        review = self._create_mock_review(issues)
        calc = MetricsCalculator(review)
        assert calc._evaluate_quality_gates() == "FAIL"


class TestMetricsDB:
    def test_db_initialization_and_save(self, temp_repo):
        db = MetricsDB(temp_repo)
        assert (temp_repo / ".git" / "lrc" / "metrics.db").exists()

        metrics = ProjectHealthMetrics(
            bugs_count=1,
            vulnerabilities_count=0,
            code_smells_count=3,
            security_rating=HealthRating.A,
            maintainability_rating=HealthRating.B,
            reliability_rating=HealthRating.B,
            lines_of_code=80,
            technical_debt_minutes=30,
            open_issues_count=4,
            overall_health_score=85.0,
            quality_gates_status="PASS",
        )

        db.save_metrics("review_v1", metrics)

        history = db.get_history(limit=5)
        assert len(history) == 1
        assert history[0]["review_id"] == "review_v1"
        assert history[0]["bugs_count"] == 1
        assert history[0]["overall_health_score"] == 85.0
        assert history[0]["quality_gates_status"] == "PASS"

    def test_db_trends_calculation(self, temp_repo):
        db = MetricsDB(temp_repo)

        m1 = ProjectHealthMetrics(
            bugs_count=5, vulnerabilities_count=2, code_smells_count=10,
            security_rating=HealthRating.C, maintainability_rating=HealthRating.C, reliability_rating=HealthRating.C,
            lines_of_code=100, technical_debt_minutes=60, open_issues_count=17, overall_health_score=60.0,
            quality_gates_status="WARN",
        )
        db.save_metrics("review_1", m1)

        # Let the DB record a second entry to compare trends
        m2 = ProjectHealthMetrics(
            bugs_count=2, vulnerabilities_count=1, code_smells_count=5,
            security_rating=HealthRating.B, maintainability_rating=HealthRating.B, reliability_rating=HealthRating.B,
            lines_of_code=150, technical_debt_minutes=30, open_issues_count=8, overall_health_score=80.0,
            quality_gates_status="PASS",
        )
        # Manually alter the SQLite timestamp so review_2 is sorted as latest
        db.save_metrics("review_2", m2)

        trend = db.get_trend()
        assert trend["bugs_trend"] == -3  # 2 - 5 = -3 (fewer bugs -> improving)
        assert trend["vulns_trend"] == -1  # 1 - 2 = -1 (fewer vulns -> improving)
        assert trend["score_trend"] == 20.0  # 80.0 - 60.0 = 20.0
