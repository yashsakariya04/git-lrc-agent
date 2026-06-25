"""Orchestrator that wraps PR-Agent's review engine with taxonomy + structured output.

This module is the primary entry point for running a review.  It:

1. Collects the staged diff via ``StagedDiffProvider``
2. Injects the custom taxonomy-aware prompt into PR-Agent's settings
3. Runs the ``PRReviewer`` engine
4. Parses the YAML output into the structured ``StructuredReview`` model
5. Applies the post-LLM classifier + severity adjuster
6. Saves the result to ``.git/lrc/reviews/``

Usage::

    from git_lrc_agent.reviewer import run_review
    review = await run_review()
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from git_lrc_agent.git.staged_diff_provider import StagedDiffProvider
from git_lrc_agent.output.structured_output import (
    FileSummary,
    StructuredReview,
    convert_pr_agent_output,
)
from git_lrc_agent.taxonomy.classifier import classify_issues
from git_lrc_agent.taxonomy.severity import adjust_severity
from git_lrc_agent.taxonomy.taxonomy import get_compact_taxonomy_for_prompt


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (1 token ≈ 4 characters).

    This is a heuristic suitable for budget warnings and chunking
    decisions, but NOT for hard token limits — real tokenizer counts
    will vary by model.
    """
    return len(text) // 4


def _chunk_diff_by_files(provider: StagedDiffProvider, max_tokens: int = 8000) -> list[list]:
    """Split diff files into chunks to avoid token overflow.

    Parameters
    ----------
    provider
        The staged diff provider.
    max_tokens
        Maximum tokens per chunk (~30K tokens = ~120KB of text).

    Returns
    -------
    List of file groups, each group's diff should fit within max_tokens.
    """
    files = provider.get_diff_files()
    chunks: list[list] = []
    current_chunk: list = []
    current_tokens = 0

    for file_info in files:
        file_tokens = _estimate_tokens(file_info.patch or "")

        if file_tokens > max_tokens:
            # Single oversized file — flush current chunk and process alone
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = 0
            chunks.append([file_info])
        elif current_tokens + file_tokens > max_tokens:
            # Adding this file exceeds limit — start a new chunk
            chunks.append(current_chunk)
            current_chunk = [file_info]
            current_tokens = file_tokens
        else:
            current_chunk.append(file_info)
            current_tokens += file_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [[]]


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

_TAXONOMY_PROMPT_EXTRA = """
=== ISSUE CLASSIFICATION ===
For every issue you find, you MUST classify it using this taxonomy:

{taxonomy}

For each issue, provide ALL of these fields:
- file: path to the affected file
- line_start: first line number (1-indexed)
- line_end: last line number (1-indexed)
- pillar: one of "Outages", "Breaches", "Technical Debt"
- category: one of the 10 categories listed above
- pattern: one of the specific patterns listed above
- severity: one of "critical", "high", "medium", "low", "info"
- title: short human-readable title (max 10 words)
- message: detailed explanation of why this is a problem (2-3 sentences)
- suggestion: REQUIRED — provide a concrete fix with code example if possible
- code_snippet: the exact problematic code extracted from the diff
- function_name: name of the affected function/method if applicable
- fix_confidence: your confidence in the suggested fix as a percentage (0-100)

=== IMPORTANT: CODE SUGGESTIONS ===
✅ ALWAYS provide a suggestion with a code example
✅ For each critical/high issue, provide the EXACT fix
✅ Include line numbers in explanations
✅ Group related issues together
✅ For security issues, explain the attack vector

Example format for suggestion:
  Before: password = request.args.get('pass')
  After:  password = request.args.get('pass')
          validate_password_strength(password)

Output all issues under `review.issues` as a YAML list (no max limit).
"""


def _build_extra_instructions() -> str:
    """Build the extra_instructions string to inject taxonomy into the prompt."""
    taxonomy_str = get_compact_taxonomy_for_prompt()
    return _TAXONOMY_PROMPT_EXTRA.format(taxonomy=taxonomy_str)


# ---------------------------------------------------------------------------
# Review runner
# ---------------------------------------------------------------------------

async def run_review(
    repo_path: str | Path | None = None,
    *,
    extra_instructions: str = "",
    model: str | None = None,
    security_mode: bool = False,
) -> StructuredReview:
    """Run a full review on staged changes and return structured results.

    Parameters
    ----------
    repo_path
        Path to the git repository.  Defaults to cwd.
    extra_instructions
        Additional instructions appended to the prompt.
    model
        Override the LLM model (e.g. ``"ollama/codellama"``).
    security_mode
        If True, append security-focused prompt additions.

    Returns
    -------
    StructuredReview
        The fully classified and scored review.
    """
    # 1. Initialise the staged diff provider.
    provider = StagedDiffProvider(repo_path)
    staged_count = provider.get_staged_file_count()
    if staged_count == 0:
        print("ℹ  No staged changes to review.")
        return StructuredReview(status="skipped")

    lines_added, lines_removed = provider.get_total_lines_changed()
    print(f"📝 Reviewing {staged_count} staged file(s)  "
          f"(+{lines_added} / -{lines_removed} lines)")

    # Warn when diff is too large for reliable review
    diff_files = provider.get_diff_files()
    total_diff_text = "".join(f.patch or "" for f in diff_files)
    estimated_tokens = _estimate_tokens(total_diff_text)

    if estimated_tokens > 30000:
        print(f"⚠️  WARNING: Large diff ({estimated_tokens:,} tokens) — results may be incomplete")
        print(f"    Consider splitting into smaller commits")

    # 2. Configure PR-Agent settings.
    from pr_agent.config_loader import get_settings

    # Point PR-Agent at our staged diff provider.
    get_settings().set("CONFIG.git_provider", "local")
    get_settings().set("CONFIG.CLI_MODE", True)

    # Inject taxonomy into extra_instructions.
    taxonomy_instructions = _build_extra_instructions()
    combined_extra = taxonomy_instructions
    if extra_instructions:
        combined_extra += f"\n\n{extra_instructions}"
    get_settings().set("pr_reviewer.extra_instructions", combined_extra)

    # Optional: override model.
    if model:
        get_settings().set("config.model", model)

    # Disable inline comments (we handle rendering ourselves).
    get_settings().set("pr_reviewer.inline_code_comments", False)

    # Configure higher issue thresholds for detailed/advanced review.
    if get_settings().pr_reviewer.get("num_max_findings", 3) == 3:
        get_settings().set("pr_reviewer.num_max_findings", 20)

    # 3. Run PR-Agent's PRReviewer.
    from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler
    from pr_agent.tools.pr_reviewer import PRReviewer

    ai_handler = LiteLLMAIHandler()

    # Build a pseudo PR-URL for the reviewer (it needs one for initialisation).
    pseudo_url = str(provider.repo_path)

    try:
        reviewer = PRReviewer.__new__(PRReviewer)
        # Manually set the fields the reviewer needs, bypassing __init__
        # which expects a real PR URL and git provider factory lookup.
        reviewer.git_provider = provider
        reviewer.ai_handler = ai_handler
        reviewer.args = []
        reviewer.pr_url = pseudo_url
        reviewer.is_answer = False
        reviewer.is_auto = False

        # Initialize incremental (required for pr-agent >= 0.36)
        reviewer.incremental = reviewer.parse_incremental(reviewer.args)

        # Get main language
        from pr_agent.git_providers.git_provider import get_main_pr_language
        reviewer.main_language = get_main_pr_language(
            provider.get_languages(), provider.get_files()
        )
        reviewer.ai_handler.main_pr_language = reviewer.main_language

        reviewer.patches_diff = None
        reviewer.prediction = None

        # PR descriptions
        reviewer.pr_description, reviewer.pr_description_files = (
            provider.get_pr_description(split_changes_walkthrough=True)
        )

        # Populate vars dict (exactly matching pr_reviewer.py)
        reviewer.vars = {
            "title": provider.pr.title,
            "branch": provider.get_pr_branch(),
            "description": reviewer.pr_description,
            "language": reviewer.main_language,
            "diff": "",  # empty diff for initial calculation
            "num_pr_files": provider.get_num_of_files(),
            "num_max_findings": get_settings().pr_reviewer.num_max_findings,
            "require_score": get_settings().pr_reviewer.require_score_review,
            "require_tests": get_settings().pr_reviewer.require_tests_review,
            "require_estimate_effort_to_review": get_settings().pr_reviewer.require_estimate_effort_to_review,
            "require_estimate_contribution_time_cost": get_settings().pr_reviewer.require_estimate_contribution_time_cost,
            'require_can_be_split_review': get_settings().pr_reviewer.require_can_be_split_review,
            'require_security_review': get_settings().pr_reviewer.require_security_review,
            'require_todo_scan': get_settings().pr_reviewer.get("require_todo_scan", False),
            'question_str': "",
            'answer_str': "",
            "extra_instructions": get_settings().pr_reviewer.extra_instructions,
            "commit_messages_str": provider.get_commit_messages(),
            "custom_labels": "",
            "enable_custom_labels": get_settings().config.enable_custom_labels,
            "is_ai_metadata": get_settings().get("config.enable_ai_metadata", False),
            "related_tickets": get_settings().get('related_tickets', []),
            'duplicate_prompt_examples': get_settings().config.get('duplicate_prompt_examples', False),
            "date": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        }

        # Initialize TokenHandler
        from pr_agent.algo.token_handler import TokenHandler

        system_prompt = get_settings().pr_review_prompt.system

        # Enrich KeyIssuesComponentLink in Pydantic schema within the system prompt to enforce suggestion and fix_confidence fields
        old_class_def = (
            "class KeyIssuesComponentLink(BaseModel):\n"
            "    relevant_file: str = Field(description=\"The full file path of the relevant file\")\n"
            "    issue_header: str = Field(description=\"One or two word title for the issue. For example: 'Possible Bug', etc.\")\n"
            "    issue_content: str = Field(description=\"A short and concise description of the issue, why it matters, and the specific scenario or input that triggers it. Do not mention line numbers in this field.\")\n"
            "    start_line: int = Field(description=\"The start line that corresponds to this issue in the relevant file\")\n"
            "    end_line: int = Field(description=\"The end line that corresponds to this issue in the relevant file\")"
        )
        new_class_def = (
            "class KeyIssuesComponentLink(BaseModel):\n"
            "    relevant_file: str = Field(description=\"The full file path of the relevant file\")\n"
            "    issue_header: str = Field(description=\"One or two word title for the issue. For example: 'Possible Bug', etc.\")\n"
            "    issue_content: str = Field(description=\"A short and concise description of the issue, why it matters, and the specific scenario or input that triggers it. Do not mention line numbers in this field.\")\n"
            "    start_line: int = Field(description=\"The start line that corresponds to this issue in the relevant file\")\n"
            "    end_line: int = Field(description=\"The end line that corresponds to this issue in the relevant file\")\n"
            "    suggestion: str = Field(description=\"A concrete suggestion for a fix, including code examples if possible.\")\n"
            "    fix_confidence: int = Field(description=\"Your confidence in the suggested fix as a percentage from 0 to 100.\")"
        )

        if old_class_def in system_prompt:
            system_prompt = system_prompt.replace(old_class_def, new_class_def)
        else:
            # Fallback if whitespace/carriage returns differ slightly
            normalized_old = old_class_def.replace("\r\n", "\n").strip()
            normalized_system = system_prompt.replace("\r\n", "\n")
            if normalized_old in normalized_system:
                system_prompt = normalized_system.replace(normalized_old, new_class_def.replace("\r\n", "\n"))
            else:
                system_prompt += "\n\nInject the 'suggestion' and 'fix_confidence' fields into every item in the 'key_issues_to_review' list."

        reviewer.token_handler = TokenHandler(
            provider.pr,
            reviewer.vars,
            system_prompt,
            get_settings().pr_review_prompt.user
        )

        # Actually call the async run method.
        # We need to handle this carefully — PRReviewer.run() calls
        # _get_prediction() and _prepare_pr_review() internally.
        await reviewer.run()

        # 4. Extract the LLM response and parse it.
        raw_response = getattr(reviewer, "prediction", "") or ""
        from pr_agent.algo.utils import load_yaml
        yaml_data = load_yaml(raw_response.strip()) if raw_response else {}

    except Exception as e:
        print(f"⚠  Review engine error: {e}")
        # Return a minimal review with the error.
        return StructuredReview(
            status="reviewed",
            commit_sha=_get_head_sha(provider),
            branch=provider.get_pr_branch(),
            title=provider.pr.title,
        )

    # 5. Convert to structured format.
    review = convert_pr_agent_output(
        yaml_data,
        commit_sha=_get_head_sha(provider),
        branch=provider.get_pr_branch(),
        title=provider.pr.title,
        raw_response=raw_response,
    )

    # 6. Build FileSummary entries.
    review.files = [
        FileSummary(
            filename=f.filename,
            lines_added=max(0, f.num_plus_lines),
            lines_removed=max(0, f.num_minus_lines),
            patch=f.patch,
        )
        for f in provider.get_diff_files()
    ]

    # 7. Run post-LLM classifier + severity adjustment.
    review.issues = classify_issues(review.issues)
    for issue in review.issues:
        adjust_severity(issue)

    # 8. Recompute summary with corrected classifications.
    review.compute_summary()

    # 9. Save to .git/lrc/reviews/.
    reviews_dir = provider.repo_path / ".git" / "lrc" / "reviews"
    review_path = reviews_dir / f"{review.id}.json"
    review.save(review_path)
    print(f"✅ Review saved: {review_path}")
    print(f"   {review.summary.total_issues} issue(s) found  |  "
          f"Risk score: {review.summary.risk_score}/100")

    # 10. Calculate and save project health metrics.
    try:
        from git_lrc_agent.metrics.calculator import MetricsCalculator
        from git_lrc_agent.metrics.db import MetricsDB
        
        # Load review history to calculate open/persistent issues.
        history_reviews = []
        review_files = sorted(reviews_dir.glob("*.json"))
        for rf in review_files:
            if rf.name != f"{review.id}.json":
                try:
                    history_reviews.append(StructuredReview.load(rf))
                except Exception:
                    pass
        
        calculator = MetricsCalculator(review, repo_path=provider.repo_path)
        metrics = calculator.calculate_metrics(review_history=history_reviews)
        
        db = MetricsDB(provider.repo_path)
        db.save_metrics(review.id, metrics)
        print(f"📊 Project Health Metrics updated: Gates {metrics.quality_gates_status} | Overall Health: {metrics.overall_health_score:.1f}%")
    except Exception as e:
        print(f"⚠  Could not calculate or save metrics: {e}")

    return review


def _get_head_sha(provider: StagedDiffProvider) -> str | None:
    """Safely get the current HEAD sha."""
    try:
        return str(provider.repo.head.commit.hexsha)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Synchronous wrapper for CLI use
# ---------------------------------------------------------------------------

def run_review_sync(**kwargs) -> StructuredReview:
    """Synchronous wrapper around :func:`run_review`."""
    return asyncio.run(run_review(**kwargs))
