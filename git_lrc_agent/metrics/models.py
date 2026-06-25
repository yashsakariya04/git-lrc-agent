"""Data models for Project Health Metrics.

Defines ratings and health structures used by metrics calculators,
storage database, and API endpoints.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class HealthRating(str, Enum):
    """Health rating from A (Excellent) to E (Critical)."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


@dataclass
class ProjectHealthMetrics:
    """SonarQube-style project health metrics."""
    
    # Issue counts
    bugs_count: int
    vulnerabilities_count: int
    code_smells_count: int
    
    # Ratings (A-E scale)
    security_rating: HealthRating
    maintainability_rating: HealthRating
    reliability_rating: HealthRating
    
    # Quantitative metrics
    lines_of_code: int
    technical_debt_minutes: int
    open_issues_count: int  # Persistent across reviews
    
    # Calculated metrics
    overall_health_score: float  # 0-100
    quality_gates_status: str  # "PASS" / "WARN" / "FAIL"
    
    @property
    def quality_status(self) -> str:
        """Text status mapping for overall health score."""
        if self.overall_health_score >= 80:
            return "EXCELLENT"
        elif self.overall_health_score >= 60:
            return "GOOD"
        elif self.overall_health_score >= 40:
            return "ACCEPTABLE"
        else:
            return "CRITICAL"


@dataclass
class MetricsTrend:
    """Track metrics over time."""
    timestamp: str
    metrics: ProjectHealthMetrics
    change_from_previous: Optional[dict] = None  # What changed (e.g. bugs count delta)
