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

=== SECURITY & QUALITY GUIDELINES ===
Be extremely thorough and scan for EVERY potential issue in the new code diff. Do NOT limit your findings. Ensure you detect:
1. Security Vulnerabilities:
   - Hardcoded secrets, API keys, passwords, connection strings (e.g. GROQ_API_KEY, OpenAI, HuggingFace, DB passwords/credentials).
   - Insecure operations (e.g., verify=False disabling SSL verification, request/socket operations without timeouts).
   - Sensitive data leaks (e.g. logging credentials, API keys, or sensitive environment variables to stdout or log files).
   - Unsafe serialization/deserialization (e.g. pickle.load, yaml.load without a Loader).
   - Use of cryptographically weak hashes (e.g. MD5 or SHA1) for security-related or file integrity operations.
2. Code Quality & Bugs:
   - Exception handling flaws (e.g. bare except clauses swallowing errors).
   - Zero division risks (e.g. check denominators before division).
   - Dictionary lookup risks (e.g. check key existence or use get() to avoid KeyError).
   - Concurrency issues (e.g. non-thread-safe singletons, race conditions, lacking synchronization/locks).
   - Resource leaks (e.g. unclosed file handles, sockets, database connections).
   - Infinite loops or unbounded memory growth (e.g. infinite loops in chunking/text splitting, caches without size limits or TTL/stale eviction checks).
   - Mutable default arguments (e.g. dict/list as default values in functions).
   - Improper logging configuration (e.g. configuring the root logger at the module level).

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
    max_tokens_per_chunk: int = 1000,
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
    max_tokens_per_chunk
        Maximum tokens per batch chunk to avoid LLM rate/token limits.

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

    # 2. Split diff files into chunks to avoid token overflow.
    chunks = _chunk_diff_by_files(provider, max_tokens=max_tokens_per_chunk)
    print(f"📦 Split into {len(chunks)} batch(es) for {model or 'default'} model")

    # 3. Run security scanner ONCE on all files
    all_diff_files = provider.get_diff_files()
    from git_lrc_agent.security.scanner import scan_diff_files
    scanner_issues = scan_diff_files(all_diff_files)
    print(f"🛡️  Security scan: {len(scanner_issues)} issue(s) found")

    # 4. Process each chunk
    all_llm_issues = []
    for i, chunk_files in enumerate(chunks, 1):
        print(f"\n⏳ Processing batch {i}/{len(chunks)} ({len(chunk_files)} file(s))...")
        chunk_issues = await _review_chunk(
            provider,
            chunk_files,
            extra_instructions,
            model,
            security_mode,
        )
        all_llm_issues.extend(chunk_issues)

    # 5. Merge scanner + LLM findings
    from git_lrc_agent.security.scanner import merge_with_llm_findings
    merged_issues = merge_with_llm_findings(scanner_issues, all_llm_issues)

    # 6. Create final review
    review = StructuredReview(
        status="reviewed",
        commit_sha=_get_head_sha(provider),
        branch=provider.get_pr_branch(),
        title=provider.pr.title,
        issues=merged_issues,
    )

    review.files = [
        FileSummary(
            filename=f.filename,
            lines_added=max(0, f.num_plus_lines),
            lines_removed=max(0, f.num_minus_lines),
            patch=f.patch,
        )
        for f in all_diff_files
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


async def _review_chunk(
    provider: StagedDiffProvider,
    chunk_files: list,
    extra_instructions: str,
    model: str | None,
    security_mode: bool,
) -> list[ReviewIssue]:
    """Review a single batch of files."""
    from pr_agent.config_loader import get_settings
    from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler
    from pr_agent.tools.pr_reviewer import PRReviewer
    from git_lrc_agent.output.structured_output import convert_pr_agent_output

    orig_diff_files = provider.diff_files
    orig_pr_diff_files = provider.pr.diff_files
    
    try:
        provider.diff_files = chunk_files
        provider.pr.diff_files = chunk_files

        # Configure PR-Agent settings.
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
        get_settings().set("pr_reviewer.num_max_findings", 15)

        ai_handler = LiteLLMAIHandler()

        pseudo_url = str(provider.repo_path)

        reviewer = PRReviewer.__new__(PRReviewer)
        reviewer.git_provider = provider
        reviewer.ai_handler = ai_handler
        reviewer.args = []
        reviewer.pr_url = pseudo_url
        reviewer.is_answer = False
        reviewer.is_auto = False

        reviewer.incremental = reviewer.parse_incremental(reviewer.args)

        from pr_agent.git_providers.git_provider import get_main_pr_language
        reviewer.main_language = get_main_pr_language(
            provider.get_languages(), provider.get_files()
        )
        reviewer.ai_handler.main_pr_language = reviewer.main_language

        reviewer.patches_diff = None
        reviewer.prediction = None

        reviewer.pr_description, reviewer.pr_description_files = (
            provider.get_pr_description(split_changes_walkthrough=True)
        )

        reviewer.vars = {
            "title": provider.pr.title,
            "branch": provider.get_pr_branch(),
            "description": reviewer.pr_description,
            "language": reviewer.main_language,
            "diff": "",
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

        from pr_agent.algo.token_handler import TokenHandler

        system_prompt = get_settings().pr_review_prompt.system

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
            "    fix_confidence: int = Field(description=\"Your confidence in the suggested fix as a percentage from 0 to 100.\")\n"
            "    pillar: str = Field(description=\"One of 'Outages', 'Breaches', 'Technical Debt'\")\n"
            "    category: str = Field(description=\"One of the risk categories, e.g., 'Security', 'Reliability', 'Performance', etc.\")\n"
            "    pattern: str = Field(description=\"Specific failure pattern\")\n"
            "    severity: str = Field(description=\"One of 'critical', 'high', 'medium', 'low', 'info'\")\n"
            "    code_snippet: str = Field(description=\"The exact problematic code extracted from the diff\")\n"
            "    function_name: str = Field(description=\"Name of the affected function/method if applicable\")"
        )

        if old_class_def in system_prompt:
            system_prompt = system_prompt.replace(old_class_def, new_class_def)
        else:
            normalized_old = old_class_def.replace("\r\n", "\n").strip()
            normalized_system = system_prompt.replace("\r\n", "\n")
            if normalized_old in normalized_system:
                system_prompt = normalized_system.replace(normalized_old, new_class_def.replace("\r\n", "\n"))
            else:
                system_prompt += "\n\nInject the 'suggestion' and 'fix_confidence' fields into every item in the 'key_issues_to_review' list."

        get_settings().set("pr_review_prompt.system", system_prompt)

        reviewer.token_handler = TokenHandler(
            provider.pr,
            reviewer.vars,
            system_prompt,
            get_settings().pr_review_prompt.user
        )

        raw_response = ""
        for attempt in range(1, 4):
            await reviewer.run()
            raw_response = getattr(reviewer, "prediction", "") or ""
            if raw_response:
                break
            
            if attempt < 3:
                print(f"⚠️  Batch processing failed or rate limited. Retrying in 35 seconds (attempt {attempt}/3)...")
                await asyncio.sleep(35)

        if not raw_response:
            raise RuntimeError("Review prediction failed for a chunk — the LLM did not return any prediction content after retries. Check console logs above for API, Rate Limit, or other errors.")
            
        from pr_agent.algo.utils import load_yaml
        yaml_data = load_yaml(raw_response.strip()) if raw_response else {}

        chunk_review = convert_pr_agent_output(
            yaml_data,
            commit_sha=None,
            branch=provider.get_pr_branch(),
            title=provider.pr.title,
            raw_response=raw_response,
        )
        return chunk_review.issues

    except Exception as e:
        print(f"❌ Error processing chunk: {e}", file=sys.stderr)
        raise e
    finally:
        provider.diff_files = orig_diff_files
        provider.pr.diff_files = orig_pr_diff_files

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
