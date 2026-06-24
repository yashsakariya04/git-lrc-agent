"""git-lrc CLI — local commit-time AI code review.

Usage::

    git-lrc review              # review staged changes
    git-lrc review --security   # security-focused review
    git-lrc vouch               # mark commit as personally reviewed
    git-lrc skip                # skip review for this commit
    git-lrc setup               # install pre-commit hooks
    git-lrc uninstall           # remove pre-commit hooks
    git-lrc history             # show recent review history
    git-lrc dashboard           # open the web dashboard for the latest review
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``git-lrc`` command."""
    # Ensure terminal stdout/stderr supports UTF-8 to prevent charmap encoding errors on Windows
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8')
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        prog="git-lrc",
        description="Free, micro AI code reviews that run on commit.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- review ---
    p_review = sub.add_parser("review", help="Review staged changes")
    p_review.add_argument("--security", action="store_true",
                          help="Run a security-focused review")
    p_review.add_argument("--model", type=str, default=None,
                          help="Override LLM model (e.g. ollama/codellama)")
    p_review.add_argument("--extra-instructions", type=str, default="",
                          help="Additional instructions for the reviewer")
    p_review.add_argument("--no-dashboard", action="store_true",
                          help="Skip opening the web dashboard")
    p_review.add_argument("--json", action="store_true", dest="json_output",
                          help="Print structured JSON to stdout")

    # --- vouch ---
    p_vouch = sub.add_parser("vouch", help="Vouch: mark commit as personally reviewed")

    # --- skip ---
    p_skip = sub.add_parser("skip", help="Skip review for this commit")

    # --- setup ---
    p_setup = sub.add_parser("setup", help="Install pre-commit hooks")
    p_setup.add_argument("--global", action="store_true", dest="global_hook",
                         help="Install hooks globally")

    # --- uninstall ---
    p_uninstall = sub.add_parser("uninstall", help="Remove pre-commit hooks")
    p_uninstall.add_argument("--global", action="store_true", dest="global_hook",
                             help="Uninstall global hooks")

    # --- history ---
    p_history = sub.add_parser("history", help="Show recent review history")
    p_history.add_argument("-n", type=int, default=10,
                           help="Number of reviews to show")

    # --- dashboard ---
    p_dashboard = sub.add_parser("dashboard", help="Open web dashboard for the latest review")

    args = parser.parse_args(argv)

    try:
        if args.command == "review":
            return _cmd_review(args)
        elif args.command == "vouch":
            return _cmd_vouch(args)
        elif args.command == "skip":
            return _cmd_skip(args)
        elif args.command == "setup":
            return _cmd_setup(args)
        elif args.command == "uninstall":
            return _cmd_uninstall(args)
        elif args.command == "history":
            return _cmd_history(args)
        elif args.command == "dashboard":
            return _cmd_dashboard(args)
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        print("\n⏹  Cancelled.")
        return 130
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def _cmd_review(args) -> int:
    """Run AI review on staged changes."""
    from git_lrc_agent.reviewer import run_review_sync

    review = run_review_sync(
        extra_instructions=args.extra_instructions,
        model=args.model,
        security_mode=args.security,
    )

    if args.json_output:
        print(review.to_json())
        return 0

    # Print summary to terminal.
    _print_review_summary(review)

    # Launch dashboard unless disabled.
    if not args.no_dashboard and review.summary.total_issues > 0:
        _launch_dashboard(review)

    return 0


def _cmd_vouch(args) -> int:
    """Mark commit as personally reviewed (no AI review)."""
    from git_lrc_agent.output.structured_output import StructuredReview
    from git_lrc_agent.git.staged_diff_provider import StagedDiffProvider

    provider = StagedDiffProvider()
    review = StructuredReview(
        status="vouched",
        commit_sha=str(provider.repo.head.commit.hexsha) if provider.repo.head.is_valid() else None,
        branch=provider.get_pr_branch(),
        title=provider.pr.title,
    )

    reviews_dir = provider.repo_path / ".git" / "lrc" / "reviews"
    review.save(reviews_dir / f"{review.id}.json")
    print("✋ Vouched — you take personal responsibility for this commit.")
    return 0


def _cmd_skip(args) -> int:
    """Skip review entirely."""
    from git_lrc_agent.output.structured_output import StructuredReview
    from git_lrc_agent.git.staged_diff_provider import StagedDiffProvider

    provider = StagedDiffProvider()
    review = StructuredReview(
        status="skipped",
        commit_sha=str(provider.repo.head.commit.hexsha) if provider.repo.head.is_valid() else None,
        branch=provider.get_pr_branch(),
        title=provider.pr.title,
    )

    reviews_dir = provider.repo_path / ".git" / "lrc" / "reviews"
    review.save(reviews_dir / f"{review.id}.json")
    print("⏭  Skipped — no review recorded for this commit.")
    return 0


def _cmd_setup(args) -> int:
    """Install git hooks."""
    from git_lrc_agent.hooks.installer import install_hooks
    install_hooks(global_hook=args.global_hook)
    return 0


def _cmd_uninstall(args) -> int:
    """Remove git hooks."""
    from git_lrc_agent.hooks.installer import uninstall_hooks
    uninstall_hooks(global_hook=args.global_hook)
    return 0


def _cmd_history(args) -> int:
    """Show recent review history."""
    from git_lrc_agent.git.staged_diff_provider import StagedDiffProvider
    from git_lrc_agent.output.structured_output import StructuredReview

    try:
        provider = StagedDiffProvider()
    except FileNotFoundError:
        print("❌ Not in a git repository.")
        return 1

    reviews_dir = provider.repo_path / ".git" / "lrc" / "reviews"
    if not reviews_dir.exists():
        print("No review history found.")
        return 0

    review_files = sorted(reviews_dir.glob("*.json"), reverse=True)[:args.n]
    if not review_files:
        print("No review history found.")
        return 0

    # Severity colour indicators.
    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}

    print(f"{'Timestamp':<22} {'Status':<10} {'Issues':<8} {'Risk':<6} {'Branch'}")
    print("─" * 70)
    for rf in review_files:
        try:
            review = StructuredReview.load(rf)
            ts = review.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            status = review.status
            issues = review.summary.total_issues
            risk = review.summary.risk_score
            branch = review.branch or "?"
            print(f"{ts:<22} {status:<10} {issues:<8} {risk:<6} {branch}")
        except Exception:
            continue

    return 0


def _cmd_dashboard(args) -> int:
    """Open the web dashboard for the latest review."""
    from git_lrc_agent.git.staged_diff_provider import StagedDiffProvider

    try:
        provider = StagedDiffProvider()
    except FileNotFoundError:
        print("❌ Not in a git repository.")
        return 1

    reviews_dir = provider.repo_path / ".git" / "lrc" / "reviews"
    review_files = sorted(reviews_dir.glob("*.json"), reverse=True) if reviews_dir.exists() else []
    if not review_files:
        print("No reviews found. Run `git-lrc review` first.")
        return 1

    _launch_dashboard_from_file(review_files[0])
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_review_summary(review) -> None:
    """Print a compact terminal summary of the review."""
    s = review.summary
    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}

    print()
    print(f"╔══════════════════════════════════════════════╗")
    print(f"║  git-lrc Review Summary                      ║")
    print(f"╠══════════════════════════════════════════════╣")
    print(f"║  Issues: {s.total_issues:<5}  Risk Score: {s.risk_score}/100       ║")
    if s.estimated_fix_time_minutes > 0:
        hours = s.estimated_fix_time_minutes // 60
        mins = s.estimated_fix_time_minutes % 60
        time_str = f"{hours}h {mins}m" if hours else f"{mins}m"
        print(f"║  Est. fix time: {time_str:<30} ║")
    print(f"╠══════════════════════════════════════════════╣")

    # Severity breakdown.
    for sev_name in ("critical", "high", "medium", "low", "info"):
        count = s.issues_by_severity.get(sev_name, 0)
        if count > 0:
            icon = sev_icon.get(sev_name, "")
            print(f"║  {icon} {sev_name.capitalize():<12} {count:<28} ║")

    print(f"╚══════════════════════════════════════════════╝")

    # Top issues.
    if s.top_issues:
        print()
        print("Top issues:")
        for i, issue in enumerate(s.top_issues[:5], 1):
            icon = sev_icon.get(issue.severity.value, "")
            print(f"  {i}. {icon} [{issue.category}] {issue.title}")
            print(f"     {issue.file}:{issue.line_start}")
    print()


def _launch_dashboard(review) -> None:
    """Start the FastAPI dashboard server and open a browser."""
    try:
        from git_lrc_agent.server.app import start_dashboard
        start_dashboard(review)
    except ImportError:
        print("ℹ  Dashboard not yet available. Use `--json` for structured output.")
    except Exception as e:
        print(f"⚠  Could not launch dashboard: {e}")


def _launch_dashboard_from_file(review_path: Path) -> None:
    """Open the dashboard for a specific review JSON file."""
    try:
        from git_lrc_agent.output.structured_output import StructuredReview
        review = StructuredReview.load(review_path)
        _launch_dashboard(review)
    except Exception as e:
        print(f"⚠  Could not open dashboard: {e}")


if __name__ == "__main__":
    sys.exit(main())
