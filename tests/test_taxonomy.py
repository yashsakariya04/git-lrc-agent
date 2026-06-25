"""Tests for the taxonomy module."""

import pytest
from git_lrc_agent.taxonomy.taxonomy import (
    ALL_PILLARS,
    CATEGORY_BY_NAME,
    PATTERN_BY_NAME,
    PILLAR_BY_NAME,
    validate_classification,
    get_compact_taxonomy_for_prompt,
    get_valid_categories,
    get_valid_patterns,
)


class TestTaxonomyStructure:
    """Verify the taxonomy is complete and well-formed."""

    def test_three_pillars(self):
        assert len(ALL_PILLARS) == 3
        names = {p.name for p in ALL_PILLARS}
        assert names == {"Outages", "Breaches", "Technical Debt"}

    def test_ten_categories(self):
        assert len(CATEGORY_BY_NAME) == 10
        expected = {
            "Reliability", "Correctness", "Performance", "Scalability",
            "Security", "Compliance & Governance",
            "Maintainability", "Architecture", "Developer Experience", "Cost",
        }
        assert set(CATEGORY_BY_NAME.keys()) == expected

    def test_at_least_100_patterns(self):
        total = sum(
            len(cat.patterns)
            for pillar in ALL_PILLARS
            for cat in pillar.categories
        )
        assert total >= 100, f"Expected 100+ patterns, got {total}"

    def test_every_pattern_has_keywords(self):
        for pillar in ALL_PILLARS:
            for cat in pillar.categories:
                for pat in cat.patterns:
                    assert len(pat.keywords) > 0, f"{pillar.name}/{cat.name}/{pat.name} has no keywords"

    def test_pillar_category_mapping(self):
        """Outages should contain Reliability, not Security."""
        pillar, cat = CATEGORY_BY_NAME["Reliability"]
        assert pillar.name == "Outages"

        pillar, cat = CATEGORY_BY_NAME["Security"]
        assert pillar.name == "Breaches"

        pillar, cat = CATEGORY_BY_NAME["Cost"]
        assert pillar.name == "Technical Debt"


class TestValidateClassification:
    """Test the validate_classification normaliser."""

    def test_valid_triple(self):
        result = validate_classification("Outages", "Reliability", "Error Handling")
        assert result == ("Outages", "Reliability", "Error Handling")

    def test_invalid_pillar_falls_back(self):
        pillar, cat, pat = validate_classification("InvalidPillar", "Reliability", "Error Handling")
        # Should correct pillar to match category's actual pillar.
        assert pillar == "Outages"
        assert cat == "Reliability"

    def test_invalid_category_falls_back_to_first(self):
        pillar, cat, pat = validate_classification("Outages", "NonexistentCategory", "Error Handling")
        # Should fall back to first category of Outages.
        assert pillar == "Outages"
        assert cat == "Reliability"  # first category of Outages

    def test_mismatched_category_pillar_corrected(self):
        pillar, cat, pat = validate_classification("Outages", "Security", "Authentication")
        # Security belongs to Breaches, so pillar should be corrected.
        assert pillar == "Breaches"
        assert cat == "Security"

    def test_pattern_lookup_corrects_chain(self):
        pillar, cat, pat = validate_classification("Technical Debt", "Cost", "Error Handling")
        # Error Handling belongs to Reliability → Outages.
        assert pillar == "Outages"
        assert cat == "Reliability"
        assert pat == "Error Handling"


class TestCompactTaxonomy:
    """Test the prompt-ready taxonomy string."""

    def test_contains_all_pillars(self):
        text = get_compact_taxonomy_for_prompt()
        assert "## Outages" in text
        assert "## Breaches" in text
        assert "## Technical Debt" in text

    def test_contains_categories(self):
        text = get_compact_taxonomy_for_prompt()
        assert "Reliability:" in text
        assert "Security:" in text
        assert "Cost:" in text

    def test_contains_patterns(self):
        text = get_compact_taxonomy_for_prompt()
        assert "Error Handling" in text
        assert "Secrets Management" in text


class TestHelpers:
    def test_get_valid_categories(self):
        cats = get_valid_categories()
        assert len(cats) == 10
        assert "Security" in cats

    def test_get_valid_patterns(self):
        pats = get_valid_patterns()
        assert len(pats) >= 100
        assert "Error Handling" in pats


class TestKeywordClassifierPrecision:
    """Tests for the word-boundary keyword matching fix (Priority 4)."""

    def test_auth_not_matching_author(self):
        """'auth' should NOT match 'author' (false positive fix)."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        score = _compute_keyword_score("the author wrote this", ("auth",))
        assert score == 0

    def test_auth_matching_standalone(self):
        """'auth' should match when it's a standalone word."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        score = _compute_keyword_score("auth token is missing", ("auth",))
        assert score == 1

    def test_inject_not_matching_injection_partially(self):
        """'inject' should match 'inject' but behave correctly with boundaries."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        score = _compute_keyword_score("sql inject vulnerability", ("inject",))
        assert score == 1

    def test_multiple_keywords(self):
        """Multiple keyword matches should accumulate score."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        score = _compute_keyword_score(
            "sql inject and password leak detected",
            ("inject", "password", "leak"),
        )
        assert score == 3

    def test_no_match_returns_zero(self):
        """No keyword matches should return 0."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        score = _compute_keyword_score("completely unrelated text", ("inject", "auth"))
        assert score == 0

    def test_single_underscore_partial_rounds_up(self):
        """A single underscore variation (0.5) should round up to 1 via math.ceil."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        # 'sql_inject' has underscore → partial match against 'sqlinject' in text
        score = _compute_keyword_score("sqlinject attack", ("sql_inject",))
        assert score == 1  # ceil(0.5) = 1, not int(0.5) = 0

    def test_multiple_underscore_partials_accumulate(self):
        """Multiple underscore partials should accumulate before ceiling."""
        from git_lrc_agent.taxonomy.classifier import _compute_keyword_score
        # Two underscore keywords, each matching partially → 0.5 + 0.5 = 1.0
        score = _compute_keyword_score(
            "sqlinject and commandinject detected",
            ("sql_inject", "command_inject"),
        )
        assert score == 1  # ceil(1.0) = 1


class TestMaxSeverityTypeSafety:
    """Verify max_severity is properly typed in file hotspots (Issue #1)."""

    def test_file_hotspot_max_severity_is_enum(self):
        """max_severity should be a Severity enum, not a raw string."""
        from git_lrc_agent.output.structured_output import (
            ReviewIssue, StructuredReview, FileSummary, Severity,
        )
        review = StructuredReview(
            issues=[
                ReviewIssue(
                    file="a.py", line_start=1, line_end=5,
                    pillar="Outages", category="Reliability", pattern="Error Handling",
                    severity="critical", title="Bug", message="Crash.",
                ),
            ],
            files=[FileSummary(filename="a.py", lines_added=10, lines_removed=2)],
        )
        review.compute_summary()

        hotspot = review.summary.file_hotspots[0]
        assert isinstance(hotspot.max_severity, Severity)
        assert hotspot.max_severity == Severity.CRITICAL
        assert hotspot.max_severity.value == "critical"

    def test_file_hotspot_none_severity_safe(self):
        """FileSummary with max_severity=None should not raise."""
        from git_lrc_agent.output.structured_output import FileSummary
        fs = FileSummary(filename="x.py", max_severity=None)
        # Guard: value access should be safe with a None check
        result = fs.max_severity.value if fs.max_severity else "info"
        assert result == "info"

