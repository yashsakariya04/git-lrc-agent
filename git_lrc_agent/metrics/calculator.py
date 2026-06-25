"""Metrics Calculator engine.

Calculates SonarQube-style quality ratings, bug counts, vulnerabilities,
code smells, Lines of Code changed, and evaluates quality gates.
"""

from typing import List, Optional
import os
import tomllib
from pathlib import Path

from .models import ProjectHealthMetrics, HealthRating
from git_lrc_agent.output.structured_output import StructuredReview, ReviewIssue, Severity


class MetricsCalculator:
    """Calculate SonarQube-style health metrics from a StructuredReview."""

    def __init__(self, review: StructuredReview, repo_path: Optional[Path] = None):
        self.review = review
        self.issues = review.issues
        self.repo_path = repo_path
        self.config = self._load_quality_gates_config()

    def _load_quality_gates_config(self) -> dict:
        """Load quality gates config from quality_gates.toml if present, else use defaults."""
        defaults = {
            "quality_gates": {
                "max_critical_issues": 0,
                "max_vulnerabilities": 2,
                "max_bugs": 5,
                "max_code_smells": 15,
                "min_security_rating": "B",
                "min_reliability_rating": "B",
                "min_maintainability_rating": "C",
                "min_overall_score": 50.0,
            }
        }
        if not self.repo_path:
            return defaults

        config_path = self.repo_path / ".git" / "lrc" / "quality_gates.toml"
        if not config_path.exists():
            config_path = self.repo_path / "quality_gates.toml"

        if config_path.exists():
            try:
                with open(config_path, "rb") as f:
                    return tomllib.load(f)
            except Exception:
                pass
        return defaults

    def calculate_metrics(self, review_history: List[StructuredReview] = None) -> ProjectHealthMetrics:
        """Main entry point - calculate all health metrics."""
        return ProjectHealthMetrics(
            bugs_count=self._count_bugs(),
            vulnerabilities_count=self._count_vulnerabilities(),
            code_smells_count=self._count_code_smells(),
            security_rating=self._calculate_security_rating(),
            maintainability_rating=self._calculate_maintainability_rating(),
            reliability_rating=self._calculate_reliability_rating(),
            lines_of_code=self._calculate_loc(),
            technical_debt_minutes=self.review.summary.estimated_fix_time_minutes,
            open_issues_count=self._calculate_open_issues(review_history),
            overall_health_score=self._calculate_overall_score(),
            quality_gates_status=self._evaluate_quality_gates(),
        )

    def _count_bugs(self) -> int:
        """Count issues in Reliability or Correctness categories."""
        return sum(1 for issue in self.issues 
                   if issue.category in ("Reliability", "Correctness"))

    def _count_vulnerabilities(self) -> int:
        """Count security-related issues."""
        return sum(1 for issue in self.issues 
                   if issue.pillar == "Breaches" or issue.category == "Security" or "security" in issue.tags)

    def _count_code_smells(self) -> int:
        """Count maintainability & architectural/complexity issues."""
        return sum(1 for issue in self.issues 
                   if issue.category in ("Maintainability", "Architecture", "Code Complexity"))

    def _group_by_severity(self, issues_list: List[ReviewIssue]) -> dict[str, int]:
        """Helper to group issues by severity."""
        counts = {}
        for issue in issues_list:
            sev = issue.severity.value.upper()
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    def _calculate_security_rating(self) -> HealthRating:
        """Security Rating calculation rules.

        A = No vulnerabilities
        B = Low severity vulnerabilities only
        C = Medium severity + max 1 high
        D = Multiple high vulnerabilities
        E = Critical vulnerabilities
        """
        vulns = [i for i in self.issues if i.pillar == "Breaches" or i.category == "Security" or "security" in i.tags]
        if not vulns:
            return HealthRating.A

        vulns_by_severity = self._group_by_severity(vulns)
        critical = vulns_by_severity.get("CRITICAL", 0)
        high = vulns_by_severity.get("HIGH", 0)
        medium = vulns_by_severity.get("MEDIUM", 0)

        if critical > 0:
            return HealthRating.E
        elif high >= 2:
            return HealthRating.D
        elif high == 1:
            return HealthRating.C
        elif medium > 0:
            return HealthRating.B
        else:
            return HealthRating.A

    def _calculate_maintainability_rating(self) -> HealthRating:
        """Maintainability Rating calculation based on ratio of code smells to total issues."""
        code_smells = self._count_code_smells()
        total_issues = len(self.issues) or 1
        smell_ratio = (code_smells / total_issues) * 100

        if smell_ratio <= 5:
            return HealthRating.A
        elif smell_ratio <= 15:
            return HealthRating.B
        elif smell_ratio <= 30:
            return HealthRating.C
        elif smell_ratio <= 50:
            return HealthRating.D
        else:
            return HealthRating.E

    def _calculate_reliability_rating(self) -> HealthRating:
        """Reliability Rating calculation based on bug count and severity."""
        bugs = self._count_bugs()
        if bugs == 0:
            return HealthRating.A

        critical_high = sum(1 for i in self.issues 
                            if i.severity.value.upper() in ("CRITICAL", "HIGH"))

        if bugs <= 2 and critical_high == 0:
            return HealthRating.B
        elif bugs <= 5 and critical_high <= 1:
            return HealthRating.C
        elif bugs <= 10:
            return HealthRating.D
        else:
            return HealthRating.E

    def _calculate_loc(self) -> int:
        """Calculate total lines of code changed (added)."""
        if not self.review.files:
            return 0
        return sum(f.lines_added for f in self.review.files if f.lines_added)

    def _calculate_open_issues(self, review_history: List[StructuredReview] = None) -> int:
        """Calculate currently open issues."""
        # Active open issues are simply the count of issues in the current review.
        return len(self.issues)

    def _calculate_overall_score(self) -> float:
        """Weighted health score from 0.0 to 100.0."""
        rating_to_score = {
            HealthRating.A: 100.0,
            HealthRating.B: 80.0,
            HealthRating.C: 60.0,
            HealthRating.D: 40.0,
            HealthRating.E: 20.0,
        }

        sec_score = rating_to_score[self._calculate_security_rating()] * 0.30
        rel_score = rating_to_score[self._calculate_reliability_rating()] * 0.30
        maint_score = rating_to_score[self._calculate_maintainability_rating()] * 0.25

        # Issue density score
        density_score = max(0.0, (1.0 - len(self.issues) / 50.0) * 100.0) * 0.15

        return sec_score + rel_score + maint_score + density_score

    def _evaluate_quality_gates(self) -> str:
        """Evaluate if the review passes quality gates configuration."""
        gates = self.config.get("quality_gates", {})
        
        # Max issue counts
        critical_issues = sum(1 for i in self.issues if i.severity.value.upper() == "CRITICAL")
        vulnerabilities = self._count_vulnerabilities()
        bugs = self._count_bugs()
        code_smells = self._count_code_smells()

        # Ratings
        sec_rating = self._calculate_security_rating()
        rel_rating = self._calculate_reliability_rating()
        maint_rating = self._calculate_maintainability_rating()
        overall_score = self._calculate_overall_score()

        # Threshold rules
        fail_conditions = [
            critical_issues > gates.get("max_critical_issues", 0),
            vulnerabilities > gates.get("max_vulnerabilities", 2),
            bugs > gates.get("max_bugs", 5),
            code_smells > gates.get("max_code_smells", 15),
            sec_rating > HealthRating(gates.get("min_security_rating", "B")),
            rel_rating > HealthRating(gates.get("min_reliability_rating", "B")),
            maint_rating > HealthRating(gates.get("min_maintainability_rating", "C")),
            overall_score < gates.get("min_overall_score", 50.0),
        ]

        if any(fail_conditions):
            return "FAIL"

        # Warning threshold rules
        warn_conditions = [
            len(self.issues) > 10,
            overall_score < 75.0,
        ]
        if any(warn_conditions):
            return "WARN"

        return "PASS"
