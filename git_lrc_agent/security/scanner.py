"""Pre-LLM security scanner.

Runs regex patterns against staged diff content to detect secrets and
vulnerabilities BEFORE the LLM review.  Results are merged with the
LLM findings, with deduplication.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pr_agent.algo.types import FilePatchInfo

from git_lrc_agent.output.structured_output import ReviewIssue, SecurityFinding, Severity
from git_lrc_agent.security.patterns import ALL_PATTERNS, SecretPattern


# Files/extensions to always skip in the security scanner.
_SKIP_EXTENSIONS = frozenset({
    ".lock", ".sum", ".min.js", ".min.css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".tar", ".gz",
})

# Paths to skip (test fixtures, snapshots, etc.).
_SKIP_PATH_PATTERNS = (
    re.compile(r"(?:^|/)(?:test_?data|fixtures|__snapshots__|vendor|node_modules)/"),
    re.compile(r"\.test\.[a-z]+$"),
    re.compile(r"_test\.go$"),
)


def scan_diff_files(
    diff_files: list[FilePatchInfo],
    *,
    patterns: list[SecretPattern] | None = None,
) -> list[ReviewIssue]:
    """Scan all staged diff files for secrets and vulnerabilities.

    Parameters
    ----------
    diff_files
        List of ``FilePatchInfo`` objects from the git provider.
    patterns
        Custom patterns to use.  Defaults to ``ALL_PATTERNS``.

    Returns
    -------
    list[ReviewIssue]
        Issues found by regex matching, ready to merge with LLM findings.
    """
    if patterns is None:
        patterns = ALL_PATTERNS

    issues: list[ReviewIssue] = []

    for file_info in diff_files:
        filename = file_info.filename
        patch = file_info.patch

        # Skip irrelevant files.
        if _should_skip(filename):
            continue

        if not patch:
            continue

        # Scan only added lines (lines starting with '+').
        added_lines = _extract_added_lines(patch)

        for line_no, line_content in added_lines:
            for pattern in patterns:
                match = pattern.regex.search(line_content)
                if match:
                    matched_text = match.group("match") if "match" in match.groupdict() else match.group(0)
                    # Redact the actual secret in the message.
                    redacted = _redact(matched_text)

                    issues.append(ReviewIssue(
                        file=filename,
                        line_start=line_no,
                        line_end=line_no,
                        pillar="Breaches",
                        category="Security",
                        pattern=pattern.category,
                        severity=pattern.severity,
                        title=f"{pattern.name} detected",
                        message=(
                            f"{pattern.description}\n"
                            f"Found: `{redacted}` at line {line_no}."
                        ),
                        suggestion=(
                            "Move this value to an environment variable or "
                            "secrets manager. Never commit credentials to "
                            "version control."
                        ),
                        code_snippet=line_content.strip()[:200],
                    ))

    return issues


def merge_with_llm_findings(
    scanner_issues: list[ReviewIssue],
    llm_issues: list[ReviewIssue],
) -> list[ReviewIssue]:
    """Merge scanner findings with LLM findings, deduplicating.

    Deduplication is based on file + line range + similar title.
    Scanner findings take priority (higher confidence).
    """
    merged = list(scanner_issues)  # Scanner findings first.
    scanner_keys = {
        (i.file, i.line_start, i.line_end)
        for i in scanner_issues
    }

    for llm_issue in llm_issues:
        key = (llm_issue.file, llm_issue.line_start, llm_issue.line_end)
        if key not in scanner_keys:
            merged.append(llm_issue)

    return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_skip(filename: str) -> bool:
    """Check if a file should be skipped based on extension or path."""
    ext = Path(filename).suffix.lower()
    if ext in _SKIP_EXTENSIONS:
        return True
    for pat in _SKIP_PATH_PATTERNS:
        if pat.search(filename):
            return True
    return False


def _extract_added_lines(patch: str) -> list[tuple[int, str]]:
    """Extract added lines from a unified diff patch with line numbers.

    Returns a list of (line_number, line_content) tuples.
    """
    results = []
    current_line = 0

    for raw_line in patch.splitlines():
        # Parse hunk headers: @@ -a,b +c,d @@
        if raw_line.startswith("@@"):
            match = re.search(r"\+(\d+)", raw_line)
            if match:
                current_line = int(match.group(1)) - 1  # Will be incremented
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current_line += 1
            results.append((current_line, raw_line[1:]))  # Strip the leading '+'
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            pass  # Removed lines don't increment new-file line count
        else:
            current_line += 1  # Context line

    return results


def _redact(value: str, show_chars: int = 4) -> str:
    """Partially redact a secret value for safe display.

    Shows the first ``show_chars`` characters and replaces the rest
    with asterisks.
    """
    if len(value) <= show_chars:
        return "*" * len(value)
    return value[:show_chars] + "*" * min(len(value) - show_chars, 20)
