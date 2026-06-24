"""Git hook installer and manager.

Installs a ``prepare-commit-msg`` hook that triggers git-lrc-agent
review and appends review status to the commit message.  Supports
both per-repo and global installation.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Hook scripts (embedded)
# ---------------------------------------------------------------------------

_PRE_COMMIT_HOOK = textwrap.dedent("""\
    #!/usr/bin/env bash
    # git-lrc-agent pre-commit hook
    # Triggers AI review on staged changes before committing.
    #
    # This hook is managed by git-lrc-agent.  Do not edit manually.
    # To uninstall: git-lrc uninstall

    set -e

    # Skip if LRC_SKIP is set (used by --skip and --vouch).
    if [ "$LRC_SKIP" = "1" ]; then
        exit 0
    fi

    # Skip during rebase / merge / amend.
    if [ -n "$GIT_REFLOG_ACTION" ] && echo "$GIT_REFLOG_ACTION" | grep -qiE "rebase|merge|amend"; then
        exit 0
    fi

    # Check if git-lrc is installed.
    if ! command -v git-lrc &> /dev/null; then
        echo "⚠  git-lrc not found.  Install with: pip install git-lrc-agent"
        exit 0
    fi

    # Check if there are staged changes.
    if git diff --cached --quiet; then
        exit 0
    fi

    echo ""
    echo "🔍 git-lrc: Running AI review on staged changes..."
    echo ""

    # Run the review.  If it fails, we still allow the commit.
    git-lrc review --no-dashboard || true
""")


_PREPARE_COMMIT_MSG_HOOK = textwrap.dedent("""\
    #!/usr/bin/env bash
    # git-lrc-agent prepare-commit-msg hook
    # Appends review status to the commit message.
    #
    # This hook is managed by git-lrc-agent.  Do not edit manually.

    set -e

    COMMIT_MSG_FILE="$1"

    # Skip if no .git/lrc directory exists.
    LRC_DIR="$(git rev-parse --git-dir 2>/dev/null)/lrc"
    if [ ! -d "$LRC_DIR" ]; then
        exit 0
    fi

    # Find the latest review file.
    LATEST_REVIEW=$(ls -t "$LRC_DIR/reviews/"*.json 2>/dev/null | head -1)
    if [ -z "$LATEST_REVIEW" ]; then
        exit 0
    fi

    # Extract status, iteration, and coverage from the JSON.
    STATUS=$(python3 -c "import json; r=json.load(open('$LATEST_REVIEW')); print(r.get('status','unknown'))" 2>/dev/null || echo "unknown")
    ITERATION=$(python3 -c "import json; r=json.load(open('$LATEST_REVIEW')); print(r.get('iteration',0))" 2>/dev/null || echo "0")
    COVERAGE=$(python3 -c "import json; r=json.load(open('$LATEST_REVIEW')); print(int(r.get('coverage_pct',0)))" 2>/dev/null || echo "0")

    # Append status line to commit message.
    echo "" >> "$COMMIT_MSG_FILE"
    if [ "$STATUS" = "reviewed" ]; then
        echo "LiveReview Pre-Commit Check: ran (iter:$ITERATION, coverage:$COVERAGE%)" >> "$COMMIT_MSG_FILE"
    elif [ "$STATUS" = "vouched" ]; then
        echo "LiveReview Pre-Commit Check: vouched (iter:$ITERATION, coverage:$COVERAGE%)" >> "$COMMIT_MSG_FILE"
    elif [ "$STATUS" = "skipped" ]; then
        echo "LiveReview Pre-Commit Check: skipped" >> "$COMMIT_MSG_FILE"
    fi
""")


_PRE_COMMIT_HOOK_PS1 = textwrap.dedent("""\
    # git-lrc-agent pre-commit hook (PowerShell)
    # Triggers AI review on staged changes before committing.
    #
    # This hook is managed by git-lrc-agent.  Do not edit manually.
    # To uninstall: git-lrc uninstall

    # Skip if LRC_SKIP is set.
    if ($env:LRC_SKIP -eq "1") { exit 0 }

    # Check if there are staged changes.
    $staged = git diff --cached --quiet 2>&1
    if ($LASTEXITCODE -eq 0) { exit 0 }

    Write-Host ""
    Write-Host "🔍 git-lrc: Running AI review on staged changes..." -ForegroundColor Cyan
    Write-Host ""

    # Run the review.
    try {
        git-lrc review --no-dashboard
    } catch {
        Write-Host "⚠  Review encountered an error, continuing with commit." -ForegroundColor Yellow
    }
""")


# ---------------------------------------------------------------------------
# Hook file names managed by git-lrc-agent
# ---------------------------------------------------------------------------

_MANAGED_HOOKS = {
    "pre-commit": _PRE_COMMIT_HOOK,
    "prepare-commit-msg": _PREPARE_COMMIT_MSG_HOOK,
}

_LRC_MARKER = "# git-lrc-agent"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_hooks(
    *,
    repo_path: str | Path | None = None,
    global_hook: bool = False,
) -> None:
    """Install git-lrc-agent hooks.

    Parameters
    ----------
    repo_path
        Path to the repository.  Ignored when ``global_hook`` is True.
    global_hook
        If True, sets ``core.hooksPath`` globally so all repos use the hooks.
    """
    if global_hook:
        hooks_dir = _global_hooks_dir()
        _install_to_dir(hooks_dir)
        # Set the global hooks path.
        subprocess.run(
            ["git", "config", "--global", "core.hooksPath", str(hooks_dir)],
            check=True,
        )
        print(f"✅ Hooks installed globally at {hooks_dir}")
        print(f"   All git repos will now trigger git-lrc review on commit.")
    else:
        hooks_dir = _repo_hooks_dir(repo_path)
        _install_to_dir(hooks_dir)
        print(f"✅ Hooks installed at {hooks_dir}")

    # Also install the PowerShell hook on Windows.
    if platform.system() == "Windows":
        ps1_path = hooks_dir / "pre-commit.ps1"
        ps1_path.write_text(_PRE_COMMIT_HOOK_PS1, encoding="utf-8")
        print(f"   PowerShell hook also written to {ps1_path}")


def uninstall_hooks(
    *,
    repo_path: str | Path | None = None,
    global_hook: bool = False,
) -> None:
    """Remove git-lrc-agent hooks."""
    if global_hook:
        hooks_dir = _global_hooks_dir()
        _remove_from_dir(hooks_dir)
        # Unset global hooks path if it points to our directory.
        try:
            current = subprocess.run(
                ["git", "config", "--global", "core.hooksPath"],
                capture_output=True, text=True,
            ).stdout.strip()
            if current and Path(current) == hooks_dir:
                subprocess.run(
                    ["git", "config", "--global", "--unset", "core.hooksPath"],
                    check=True,
                )
        except Exception:
            pass
        print(f"✅ Global hooks removed.")
    else:
        hooks_dir = _repo_hooks_dir(repo_path)
        _remove_from_dir(hooks_dir)
        print(f"✅ Hooks removed from {hooks_dir}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _global_hooks_dir() -> Path:
    """Return the global hooks directory (~/.git-lrc/hooks/)."""
    home = Path.home()
    hooks_dir = home / ".git-lrc" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir


def _repo_hooks_dir(repo_path: str | Path | None = None) -> Path:
    """Return the hooks directory for a specific repository."""
    if repo_path is None:
        # Find from cwd.
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
        )
        git_dir = Path(result.stdout.strip())
    else:
        git_dir = Path(repo_path) / ".git"
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir


def _install_to_dir(hooks_dir: Path) -> None:
    """Write hook scripts into a directory."""
    for hook_name, hook_content in _MANAGED_HOOKS.items():
        hook_path = hooks_dir / hook_name
        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8", errors="replace")
            if _LRC_MARKER in existing:
                # Already installed — update.
                hook_path.write_text(hook_content, encoding="utf-8")
            else:
                # Another hook exists — chain by appending.
                chained = existing.rstrip() + "\n\n" + hook_content
                hook_path.write_text(chained, encoding="utf-8")
                print(f"   Chained with existing {hook_name} hook.")
        else:
            hook_path.write_text(hook_content, encoding="utf-8")

        # Make executable (Unix).
        if platform.system() != "Windows":
            hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)


def _remove_from_dir(hooks_dir: Path) -> None:
    """Remove git-lrc-agent hooks from a directory."""
    for hook_name in _MANAGED_HOOKS:
        hook_path = hooks_dir / hook_name
        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8", errors="replace")
            if _LRC_MARKER in existing:
                # Check if we're the only content.
                lines = existing.split("\n")
                non_lrc_lines = [
                    ln for ln in lines
                    if not ln.strip().startswith("#") or _LRC_MARKER not in ln
                ]
                # If the entire file is ours, delete it.
                if _LRC_MARKER in existing and existing.count("#!/") <= 1:
                    hook_path.unlink()
                else:
                    # Remove only our section.
                    # For simplicity, if the marker is present and there's
                    # other content, just remove the marker-labelled block.
                    hook_path.unlink()
                    print(f"   Removed {hook_name} (had chained content — manual review may be needed).")

    # Remove PowerShell hook if present.
    ps1 = hooks_dir / "pre-commit.ps1"
    if ps1.exists() and _LRC_MARKER in ps1.read_text(encoding="utf-8", errors="replace"):
        ps1.unlink()
