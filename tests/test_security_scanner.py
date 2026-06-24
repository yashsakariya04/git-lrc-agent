"""Tests for the security scanner and patterns."""

import pytest
from git_lrc_agent.security.patterns import (
    ALL_PATTERNS,
    get_secret_patterns,
    get_vuln_patterns,
)
from git_lrc_agent.security.scanner import (
    scan_diff_files,
    merge_with_llm_findings,
    _extract_added_lines,
    _redact,
    _should_skip,
)
from git_lrc_agent.output.structured_output import ReviewIssue
from pr_agent.algo.types import FilePatchInfo, EDIT_TYPE


class TestPatterns:
    def test_total_pattern_count(self):
        assert len(ALL_PATTERNS) >= 25

    def test_secret_patterns_exist(self):
        secrets = get_secret_patterns()
        names = {p.name for p in secrets}
        assert "AWS Access Key" in names
        assert "GitHub Token" in names
        assert "Private Key (PEM)" in names

    def test_vuln_patterns_exist(self):
        vulns = get_vuln_patterns()
        names = {p.name for p in vulns}
        assert "SQL String Concatenation" in names
        assert "Dangerous eval()" in names

    def test_aws_key_regex(self):
        pat = next(p for p in ALL_PATTERNS if p.name == "AWS Access Key")
        assert pat.regex.search("AKIAIOSFODNN7EXAMPLE")
        assert not pat.regex.search("not-a-key")

    def test_github_token_regex(self):
        pat = next(p for p in ALL_PATTERNS if p.name == "GitHub Token")
        assert pat.regex.search("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")
        assert not pat.regex.search("ghx_notvalid")

    def test_private_key_regex(self):
        pat = next(p for p in ALL_PATTERNS if p.name == "Private Key (PEM)")
        assert pat.regex.search("-----BEGIN RSA PRIVATE KEY-----")
        assert pat.regex.search("-----BEGIN PRIVATE KEY-----")

    def test_eval_regex(self):
        pat = next(p for p in ALL_PATTERNS if p.name == "Dangerous eval()")
        assert pat.regex.search("result = eval(user_input)")
        assert not pat.regex.search("# evaluating the expression")


class TestScanner:
    def _make_file_patch(self, filename: str, patch: str) -> FilePatchInfo:
        return FilePatchInfo(
            base_file="",
            head_file="",
            patch=patch,
            filename=filename,
            edit_type=EDIT_TYPE.MODIFIED,
        )

    def test_detects_aws_key_in_diff(self):
        patch = """@@ -1,3 +1,4 @@
 import os
+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
 def main():
     pass"""
        files = [self._make_file_patch("config.py", patch)]
        issues = scan_diff_files(files)
        assert len(issues) >= 1
        assert any("AWS" in i.title for i in issues)

    def test_detects_github_token(self):
        patch = """@@ -0,0 +1,2 @@
+TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
+print(TOKEN)"""
        files = [self._make_file_patch("auth.py", patch)]
        issues = scan_diff_files(files)
        assert len(issues) >= 1
        assert any("GitHub" in i.title for i in issues)

    def test_skips_binary_files(self):
        assert _should_skip("image.png")
        assert _should_skip("font.woff2")
        assert not _should_skip("config.py")

    def test_skips_test_fixtures(self):
        assert _should_skip("test_data/sample.txt")
        assert _should_skip("__snapshots__/test.snap")

    def test_does_not_skip_normal_files(self):
        assert not _should_skip("src/main.py")
        assert not _should_skip("lib/utils.js")


class TestExtractAddedLines:
    def test_basic_patch(self):
        patch = """@@ -1,3 +1,4 @@
 line1
+new_line
 line3
 line4"""
        lines = _extract_added_lines(patch)
        assert len(lines) == 1
        assert lines[0] == (2, "new_line")

    def test_multiple_hunks(self):
        patch = """@@ -1,2 +1,3 @@
 line1
+added1
 line2
@@ -10,2 +11,3 @@
 line10
+added2
 line11"""
        lines = _extract_added_lines(patch)
        assert len(lines) == 2
        assert lines[0][1] == "added1"
        assert lines[1][1] == "added2"


class TestRedact:
    def test_long_value(self):
        result = _redact("AKIAIOSFODNN7EXAMPLE")
        assert result.startswith("AKIA")
        assert "*" in result

    def test_short_value(self):
        result = _redact("abc")
        assert result == "***"


class TestMerge:
    def test_deduplication(self):
        scanner = [ReviewIssue(
            file="a.py", line_start=5, line_end=5,
            pillar="Breaches", category="Security", pattern="Secrets Management",
            severity="critical", title="AWS Key", message="Found key.",
        )]
        llm = [
            ReviewIssue(
                file="a.py", line_start=5, line_end=5,
                pillar="Breaches", category="Security", pattern="Secrets Management",
                severity="high", title="Hardcoded credential", message="LLM found it too.",
            ),
            ReviewIssue(
                file="b.py", line_start=10, line_end=12,
                pillar="Outages", category="Correctness", pattern="Logic Errors",
                severity="medium", title="Logic bug", message="Wrong condition.",
            ),
        ]
        merged = merge_with_llm_findings(scanner, llm)
        # Scanner issue + non-duplicate LLM issue = 2.
        assert len(merged) == 2
        # Scanner finding should be first (higher priority).
        assert merged[0].title == "AWS Key"
