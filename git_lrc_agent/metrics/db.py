"""Metrics SQLite Database storage and tracker.

Persists project health metrics inside the repository's `.git/lrc/metrics.db`
database, enabling historical tracking and trend computations.
"""

from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ProjectHealthMetrics, HealthRating


class MetricsDB:
    """SQLite manager for storing and retrieving project metrics."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)
        self.lrc_dir = self.repo_path / ".git" / "lrc"
        self.lrc_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.lrc_dir / "metrics.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialise database schema and indices."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id TEXT UNIQUE,
                    timestamp DATETIME,
                    bugs_count INTEGER,
                    vulnerabilities_count INTEGER,
                    code_smells_count INTEGER,
                    security_rating TEXT,
                    reliability_rating TEXT,
                    maintainability_rating TEXT,
                    lines_of_code INTEGER,
                    technical_debt_minutes INTEGER,
                    open_issues_count INTEGER,
                    overall_health_score FLOAT,
                    quality_gates_status TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON metrics_history(timestamp DESC)
            """)
            conn.commit()

    def save_metrics(self, review_id: str, metrics: ProjectHealthMetrics) -> None:
        """Insert or update metrics for a review."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO metrics_history (
                    review_id, timestamp, bugs_count, vulnerabilities_count, 
                    code_smells_count, security_rating, reliability_rating, 
                    maintainability_rating, lines_of_code, technical_debt_minutes, 
                    open_issues_count, overall_health_score, quality_gates_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                review_id,
                datetime.now(timezone.utc).isoformat(),
                metrics.bugs_count,
                metrics.vulnerabilities_count,
                metrics.code_smells_count,
                metrics.security_rating.value,
                metrics.reliability_rating.value,
                metrics.maintainability_rating.value,
                metrics.lines_of_code,
                metrics.technical_debt_minutes,
                metrics.open_issues_count,
                metrics.overall_health_score,
                metrics.quality_gates_status,
            ))
            conn.commit()

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve metrics history sorted by timestamp ascending."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT review_id, timestamp, bugs_count, vulnerabilities_count, 
                       code_smells_count, security_rating, reliability_rating, 
                       maintainability_rating, lines_of_code, technical_debt_minutes, 
                       open_issues_count, overall_health_score, quality_gates_status
                FROM metrics_history
                ORDER BY timestamp ASC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_trend(self) -> Optional[Dict[str, Any]]:
        """Calculate trend comparison between latest and previous reviews."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT bugs_count, vulnerabilities_count, overall_health_score
                FROM metrics_history
                ORDER BY timestamp DESC
                LIMIT 2
            """)
            rows = [dict(row) for row in cursor.fetchall()]

        if len(rows) < 2:
            return {
                "bugs_trend": 0,
                "vulns_trend": 0,
                "score_trend": 0.0,
            }

        latest = rows[0]
        previous = rows[1]

        return {
            "bugs_trend": latest["bugs_count"] - previous["bugs_count"],
            "vulns_trend": latest["vulnerabilities_count"] - previous["vulnerabilities_count"],
            "score_trend": round(latest["overall_health_score"] - previous["overall_health_score"], 2),
        }
