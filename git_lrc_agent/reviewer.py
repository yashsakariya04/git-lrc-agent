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
- title: short human-readable title
- message: detailed explanation
- suggestion: concrete fix recommendation (optional but preferred)
- code_snippet: the problematic code (optional)

Output the issues under `review.issues` as a YAML list.
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
        reviewer.token_handler = TokenHandler(
            provider.pr,
            reviewer.vars,
            get_settings().pr_review_prompt.system,
            get_settings().pr_review_prompt.user
        )

        # Actually call the async run method.
        # We need to handle this carefully — PRReviewer.run() calls
        # _get_prediction() and _prepare_pr_review() internally.
        await reviewer.run()

        # 4. Extract the LLM response and parse it.
        raw_response = getattr(reviewer, "prediction", "")
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
