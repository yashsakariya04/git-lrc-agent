# 🔍 git-lrc-agent

**Free, local AI code reviews that run on every commit.**

git-lrc-agent wraps [PR-Agent](https://github.com/The-PR-Agent/pr-agent) to deliver commit-time AI code review with a rich web dashboard — no hosted service required. It intercepts `git commit`, reviews your staged changes with an LLM, classifies issues into a 104-pattern taxonomy, and opens a browser dashboard so you can review, commit, or skip.

```
git add .
git commit -m "feat: add payment flow"

🔍 git-lrc: Running AI review on staged changes...
📝 Reviewing 3 staged file(s)  (+142 / -23 lines)
✅ Review saved: .git/lrc/reviews/20260623T120000_abc12345.json
   7 issue(s) found  |  Risk score: 45/100
🌐 Dashboard: http://localhost:52431
```

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [CLI Commands](#cli-commands)
- [Dashboard Guide](#dashboard-guide)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Issue Taxonomy](#issue-taxonomy)
- [Security Scanner](#security-scanner)
- [Python API Reference](#python-api-reference)
- [How It Works](#how-it-works)
- [Troubleshooting](#troubleshooting)

---

## Installation

### Prerequisites

- **Python 3.10+**
- **Git** installed and available on PATH
- **An LLM API key** (OpenAI, Anthropic, or a local model via Ollama)

### Install from source

```bash
# Clone the repository
git clone <repo-url> git-lrc-agent
cd git-lrc-agent

# Install in development mode
pip install -e .

# Verify installation
git-lrc --help
```

### Install dependencies

```bash
# PR-Agent (the review engine)
pip install pr-agent

# Dashboard server
pip install fastapi uvicorn

# Git integration
pip install gitpython
```

### Configure your LLM

git-lrc-agent uses PR-Agent's LiteLLM backend, which supports **all major LLM providers**.

Create a `.pr_agent.toml` in your repository root (or `~/.pr_agent.toml` for global config):

```toml
# ─── Option A: OpenAI ─────────────────────────────────
[config]
model = "gpt-4o"

[openai]
key = "sk-..."

# ─── Option B: Anthropic (Claude) ─────────────────────
[config]
model = "anthropic/claude-sonnet-4-20250514"

[anthropic]
key = "sk-ant-..."

# ─── Option C: Local model via Ollama (offline) ───────
[config]
model = "ollama/codellama"

[ollama]
api_base = "http://localhost:11434"
```

> **Tip:** For offline/air-gapped use, install [Ollama](https://ollama.ai/) and pull a code-capable model: `ollama pull codellama`

---

## Quick Start

### 1. Install the hook (one time)

```bash
# Install for the current repository
git-lrc setup

# OR install globally (all repos)
git-lrc setup --global
```

### 2. Work normally

```bash
# Make changes, stage them
git add src/payment.py src/utils.py

# Commit — the hook triggers automatically
git commit -m "feat: add payment processing"
```

The review runs, the dashboard opens, and you decide:
- **✅ Commit** — proceed with the commit
- **⏭ Skip** — abort the commit

### 3. Manual review (without hook)

```bash
# Stage your changes
git add .

# Run review manually
git-lrc review
```

---

## Configuration

### `.pr_agent.toml` (LLM + review settings)

Place this file in your **repository root** or **home directory** (`~/.pr_agent.toml`).

```toml
[config]
model = "gpt-4o"                    # LLM model to use
git_provider = "local"              # Always "local" for git-lrc

[pr_reviewer]
extra_instructions = ""             # Additional review instructions
inline_code_comments = false        # Handled by dashboard, not git provider
num_code_suggestions = 3            # Number of code fix suggestions

[openai]
key = "sk-..."                      # Your API key
```

### Environment variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `LRC_SKIP` | Set to `1` to skip the hook | `LRC_SKIP=1 git commit` |

---

## CLI Commands

### `git-lrc review`

**Run an AI review on staged changes.**

```bash
git-lrc review                          # Standard review
git-lrc review --security               # Security-focused review
git-lrc review --model ollama/codellama # Use a specific model
git-lrc review --json                   # Output structured JSON to stdout
git-lrc review --no-dashboard           # Skip opening the browser
git-lrc review --extra-instructions "Focus on error handling"
```

| Flag | Description |
|------|-------------|
| `--security` | Runs a security-focused review with 30 regex pre-scans + security LLM prompt |
| `--model MODEL` | Override the LLM model (e.g., `ollama/codellama`, `anthropic/claude-sonnet-4-20250514`) |
| `--json` | Print the full structured review as JSON to stdout (useful for piping) |
| `--no-dashboard` | Don't open the web dashboard; print summary to terminal only |
| `--extra-instructions TEXT` | Append custom instructions to the review prompt |

**Output:**
```
📝 Reviewing 3 staged file(s)  (+142 / -23 lines)
✅ Review saved: .git/lrc/reviews/20260623T120000_abc12345.json
   7 issue(s) found  |  Risk score: 45/100

╔══════════════════════════════════════════════╗
║  git-lrc Review Summary                      ║
╠══════════════════════════════════════════════╣
║  Issues: 7      Risk Score: 45/100           ║
║  Est. fix time: 3h 30m                       ║
╠══════════════════════════════════════════════╣
║  🔴 Critical     1                           ║
║  🟠 High         2                           ║
║  🟡 Medium       3                           ║
║  🔵 Low          1                           ║
╚══════════════════════════════════════════════╝

Top issues:
  1. 🔴 [Security] Hardcoded API key in config.py
     config.py:12
  2. 🟠 [Reliability] Unhandled exception in payment flow
     payment.py:47
  3. 🟠 [Correctness] Off-by-one error in pagination
     utils.py:89
```

---

### `git-lrc setup`

**Install pre-commit hooks.**

```bash
git-lrc setup              # Current repository only
git-lrc setup --global     # All git repositories
```

This installs two hooks:
1. **`pre-commit`** — Triggers the AI review before every commit
2. **`prepare-commit-msg`** — Appends review status to the commit message

After setup, every `git commit` will automatically run a review.

**What gets added to commit messages:**
```
feat: add payment processing

LiveReview Pre-Commit Check: ran (iter:1, coverage:85%)
```

> **Note:** If you have existing pre-commit hooks (e.g., from Husky or pre-commit framework), git-lrc-agent **chains** with them — it appends to the existing hook file rather than overwriting.

---

### `git-lrc uninstall`

**Remove git-lrc hooks.**

```bash
git-lrc uninstall          # Current repository
git-lrc uninstall --global # Remove global hooks
```

---

### `git-lrc vouch`

**Mark commit as personally reviewed (no AI review).**

```bash
git-lrc vouch
# ✋ Vouched — you take personal responsibility for this commit.
```

Records a `"vouched"` status in `.git/lrc/reviews/` so the audit trail shows this commit was consciously approved without AI review.

---

### `git-lrc skip`

**Skip review for this commit.**

```bash
git-lrc skip
# ⏭ Skipped — no review recorded for this commit.
```

Records a `"skipped"` status. Use this when the hook fires but you want to commit without review.

**Alternative:** Set `LRC_SKIP=1` to bypass the hook entirely:
```bash
LRC_SKIP=1 git commit -m "quick fix"  # Unix
$env:LRC_SKIP="1"; git commit -m "quick fix"  # PowerShell
```

---

### `git-lrc history`

**Show recent review history.**

```bash
git-lrc history        # Last 10 reviews
git-lrc history -n 20  # Last 20 reviews
```

**Output:**
```
Timestamp              Status     Issues   Risk   Branch
──────────────────────────────────────────────────────────────────────────
2026-06-23 12:30:00    reviewed   7        45     feat/payment
2026-06-23 11:15:00    vouched    0        0      fix/typo
2026-06-23 10:00:00    reviewed   3        25     feat/auth
2026-06-22 16:45:00    skipped    0        0      chore/deps
```

---

### `git-lrc dashboard`

**Open the web dashboard for the most recent review.**

```bash
git-lrc dashboard
# 🌐 Dashboard: http://localhost:52431
```

If no reviews exist, it prompts you to run `git-lrc review` first.

---

## Dashboard Guide

The dashboard is a three-panel web application that opens automatically after each review.

```
┌─────────────────────────────────────────────────────────────────┐
│  🔍 git-lrc  v0.1.0    ████████░░ Risk: 45    📋 Copy  ⏭ ✅    │
├────────────┬───────────────────────────────────┬────────────────┤
│            │                                   │                │
│  FILES     │       DIFF + INLINE COMMENTS      │   SUMMARY      │
│            │                                   │                │
│  ▸ pay.py  │  @@ Lines 47-52 @@                │   7 Issues     │
│    🟠 2    │  + try:                           │   3 Files      │
│  ▸ utils   │  +     process()                  │   3h 30m fix   │
│    🟡 1    │  + except:                        │                │
│  ▸ config  │  +     pass  ← [HIGH: Error       │   ──────────   │
│    🔴 1    │         Handling] No logging...    │   Severity     │
│            │                                   │   🔴 Crit: 1   │
│  FILTERS   │  💡 Suggestion: Add specific      │   🟠 High: 2   │
│  ☑ 🔴 Crit │     exception handling and log... │   🟡 Med:  3   │
│  ☑ 🟠 High │                                   │   🔵 Low:  1   │
│  ☑ 🟡 Med  │                                   │                │
│  ☑ 🔵 Low  │    ◀  3 of 7  ▶                   │   Top Issues   │
│  ☑ ⚪ Info  │                                   │   1. 🔴 API key│
│            │                                   │   2. 🟠 Except │
│  PILLARS   │                                   │   3. 🟠 Off-by │
│  ☑ Outages │                                   │                │
│  ☑ Breach  │                                   │   Prose:       │
│  ☑ TechDbt │                                   │   This change  │
│            │                                   │   adds payment │
│            │                                   │   processing...│
├────────────┴───────────────────────────────────┴────────────────┤
```

### Left Panel — File Tree & Filters

- **File list**: Shows each changed file with a colour-coded issue badge
  - 🔴 = critical/high issues, 🟡 = medium, 🔵 = low, ✅ = clean
  - Shows `+added / -removed` line counts
- **Click a file** to view its diff and inline comments
- **Severity filters**: Uncheck a severity level to hide those issues
- **Pillar filters**: Filter by Outages / Breaches / Technical Debt

### Centre Panel — Diff Viewer

- **Hunk headers** show the line range being reviewed
- **Code lines** are colour-coded: green = added, red = removed
- **Inline comment cards** appear below the affected code:
  - **Severity badge** (CRITICAL / HIGH / MEDIUM / LOW / INFO)
  - **Category tag** (e.g., `Reliability → Error Handling`)
  - **Title** — short summary of the issue
  - **Message** — detailed explanation
  - **💡 Suggestion** — concrete fix recommendation

### Right Panel — Summary Deck

- **Stats cards**: Total issues, files changed, estimated fix time
- **Risk score**: 0–100 weighted gauge (critical=25pts, high=15, medium=5, low=2)
- **Severity chart**: Horizontal bar breakdown
- **Category chart**: Issue counts per category
- **Top issues**: The 3 most critical findings (clickable to navigate)
- **Prose summary**: LLM-generated natural language overview

### Action Buttons (Header Bar)

| Button | Action |
|--------|--------|
| **📋 Copy Issues** | Copy all filtered issues as markdown to clipboard |
| **⏭ Skip** | Abort the commit, close dashboard |
| **✅ Commit** | Proceed with the commit, close dashboard |

---

## Keyboard Shortcuts

All shortcuts work globally in the dashboard (disabled when typing in an input field).

| Key | Action |
|-----|--------|
| `n` | Next issue — scroll to next inline comment |
| `p` | Previous issue — scroll to previous comment |
| `j` | Next file — select next file in the tree |
| `k` | Previous file — select previous file in the tree |
| `c` | Copy all issues — markdown to clipboard |
| `Esc` | Close panels / modals |

The issue navigator shows your position: **"3 of 7"** — press `n`/`p` to cycle through all issues across all files.

---

## Issue Taxonomy

Every issue is classified into a **three-level hierarchy**: Pillar → Category → Pattern.

### Pillars

| Pillar | Focus | Example |
|--------|-------|---------|
| 🔴 **Outages** | Things that crash, corrupt, or slow production | Missing error handling |
| 🟠 **Breaches** | Things that leak data or violate regulations | Hardcoded API key |
| 🟡 **Technical Debt** | Things that make the codebase harder to maintain | Code duplication |

### Categories (10)

| Pillar | Categories |
|--------|------------|
| Outages | Reliability, Correctness, Performance, Scalability |
| Breaches | Security, Compliance & Governance |
| Technical Debt | Maintainability, Architecture, Developer Experience, Cost |

### Example Patterns (104 total)

| Category | Sample Patterns |
|----------|----------------|
| Reliability | Error Handling, Fault Tolerance, Retry Logic, Timeout Management, Race Conditions |
| Correctness | Logic Errors, Edge Cases, Data Validation, Null Handling, Type Safety |
| Performance | Database Efficiency, Algorithmic Complexity, Memory Usage, Caching |
| Security | Authentication, Authorization, Secrets Management, Injection Vulnerabilities |
| Maintainability | Code Complexity, Readability, Documentation, Dead Code, Naming Quality |
| Cost | Cloud Resource Waste, LLM Token Consumption, Data Transfer Costs |

### Severity Levels

| Level | Colour | Weight | Fix Time | Meaning |
|-------|--------|--------|----------|---------|
| 🔴 Critical | Red | 25 | ~2h | Production outage risk, data loss, security breach |
| 🟠 High | Orange | 15 | ~1h | Significant bug, vulnerability, performance hit |
| 🟡 Medium | Yellow | 5 | ~30m | Code quality issue with moderate impact |
| 🔵 Low | Blue | 2 | ~10m | Minor improvement opportunity |
| ⚪ Info | Grey | 0 | 0 | Observation, no action required |

**Automatic severity rules:**
- `Security` category issues are **never** lower than `high`
- `Secrets Management`, `Injection Vulnerabilities`, `Authentication` patterns → always `critical`
- `Reliability` and `Correctness` categories → floored at `medium`

---

## Security Scanner

git-lrc-agent includes a **pre-LLM regex scanner** that detects secrets and vulnerabilities **before** the LLM call. This is instant, offline, and zero-cost.

### What it detects

**Secrets (20 patterns):**

| Pattern | Example Match |
|---------|---------------|
| AWS Access Key | `AKIAIOSFODNN7EXAMPLE` |
| AWS Secret Key | `aws_secret_key = "wJalrX..."` |
| GitHub Token | `ghp_ABCDEF...` |
| GitLab Token | `glpat-...` |
| Slack Bot Token | `xoxb-...` |
| Google API Key | `AIzaSy...` |
| Stripe Secret Key | `sk_live_...` |
| Private Key (PEM) | `-----BEGIN RSA PRIVATE KEY-----` |
| JWT Token | `eyJhbG...` |
| Hardcoded Password | `password = "hunter2"` |
| Generic API Key | `api_key = "abc123..."` |
| Connection String | `database_url = "postgres://..."` |
| Basic Auth in URL | `https://user:pass@host.com` |

**Vulnerabilities (10 patterns):**

| Pattern | Example Match |
|---------|---------------|
| SQL String Concatenation | `cursor.execute(f"SELECT * FROM {table}")` |
| Dangerous eval() | `result = eval(user_input)` |
| Dangerous exec() | `exec(code_string)` |
| innerHTML Assignment | `element.innerHTML = data` |
| Shell Command Injection | `os.system(f"rm {filename}")` |
| Disabled TLS Verification | `verify=False` |
| Weak Hash Function | `md5(password)` |
| Insecure Random | `Math.random()` for tokens |

### How it works

1. **Pre-LLM pass**: Regex patterns scan only `+` lines (added code) from the staged diff
2. **LLM pass**: The full diff is sent to the LLM for deeper analysis
3. **Merge**: Findings from both passes are merged, with scanner findings taking priority (higher confidence)
4. **Deduplication**: If the LLM and scanner flag the same file:line, the scanner result is kept

**Matched secrets are automatically redacted** in the output: `AKIA************` (first 4 chars shown).

---

## Python API Reference

For programmatic use, you can import git-lrc-agent modules directly.

### Run a review

```python
import asyncio
from git_lrc_agent.reviewer import run_review

# Async
review = asyncio.run(run_review(
    repo_path="/path/to/repo",
    model="gpt-4o",
    security_mode=True,
    extra_instructions="Focus on error handling",
))

print(f"Found {review.summary.total_issues} issues")
print(f"Risk score: {review.summary.risk_score}/100")

# Or synchronous
from git_lrc_agent.reviewer import run_review_sync
review = run_review_sync()
```

### Work with structured output

```python
from git_lrc_agent.output.structured_output import (
    StructuredReview,
    ReviewIssue,
    convert_pr_agent_output,
)

# Load a saved review
review = StructuredReview.load(".git/lrc/reviews/20260623T120000_abc12345.json")

# Iterate over issues
for issue in review.issues:
    print(f"[{issue.severity.value}] {issue.file}:{issue.line_start}")
    print(f"  {issue.pillar} → {issue.category} → {issue.pattern}")
    print(f"  {issue.title}: {issue.message}")

# Access summary
print(f"Risk: {review.summary.risk_score}/100")
print(f"Fix time: {review.summary.estimated_fix_time_minutes} minutes")
print(f"Top issue: {review.summary.top_issues[0].title}")

# Export as JSON
json_str = review.to_json(indent=2)

# Convert from PR-Agent's raw YAML output
review = convert_pr_agent_output(yaml_dict, commit_sha="abc123")
```

### Use the taxonomy

```python
from git_lrc_agent.taxonomy.taxonomy import (
    ALL_PILLARS,
    CATEGORY_BY_NAME,
    validate_classification,
    get_compact_taxonomy_for_prompt,
)

# Validate and correct a classification
pillar, category, pattern = validate_classification(
    "Outages", "Security", "Error Handling"
)
# → ("Outages", "Reliability", "Error Handling")
# Auto-corrected: Security belongs to Breaches, Error Handling to Reliability

# Get prompt-ready taxonomy (for custom LLM prompts)
taxonomy_text = get_compact_taxonomy_for_prompt()
```

### Use the classifier

```python
from git_lrc_agent.taxonomy.classifier import classify_issue, classify_issues
from git_lrc_agent.taxonomy.severity import adjust_severity, normalise_severity

# Classify an issue with fallback keyword matching
issue = classify_issue(issue)

# Batch classify
issues = classify_issues(all_issues)

# Normalise severity strings
sev = normalise_severity("warning")  # → Severity.MEDIUM
sev = normalise_severity("critical")  # → Severity.CRITICAL

# Apply severity floor rules
issue = adjust_severity(issue)
# Security issues → floored at HIGH
# Secrets Management → always CRITICAL
```

### Use the security scanner

```python
from git_lrc_agent.security.scanner import scan_diff_files, merge_with_llm_findings
from git_lrc_agent.security.patterns import get_all_patterns

# Scan staged diffs
scanner_issues = scan_diff_files(diff_files)

# Merge with LLM findings (scanner takes priority)
all_issues = merge_with_llm_findings(scanner_issues, llm_issues)
```

### Use the review store

```python
from git_lrc_agent.state.store import ReviewStore

store = ReviewStore(repo_path="/path/to/repo")

# Save a review
store.save_review(review)

# Get latest review
latest = store.get_latest_review()

# Get history
history = store.get_review_history(limit=10)

# Compare two reviews
diff = store.compare_reviews("old_id", "new_id")
print(f"New issues: {len(diff['new_issues'])}")
print(f"Resolved: {len(diff['resolved_issues'])}")

# Prune old reviews
deleted = store.prune(max_age_days=30)
```

### Launch the dashboard programmatically

```python
from git_lrc_agent.server.app import start_dashboard

# Blocking — returns user decision ("commit" or "skip")
decision = start_dashboard(review, port=8080)
if decision == "commit":
    print("User approved!")

# Non-blocking
start_dashboard(review, block=False, open_browser=True)
```

### Install hooks programmatically

```python
from git_lrc_agent.hooks.installer import install_hooks, uninstall_hooks

install_hooks()                    # Current repo
install_hooks(global_hook=True)    # All repos
uninstall_hooks()                  # Remove from current repo
```

### Use the staged diff provider

```python
from git_lrc_agent.git.staged_diff_provider import StagedDiffProvider

provider = StagedDiffProvider()

# Get staged files
files = provider.get_diff_files()
for f in files:
    print(f"{f.filename}: +{f.num_plus_lines}/-{f.num_minus_lines}")

# Get stats
count = provider.get_staged_file_count()
added, removed = provider.get_total_lines_changed()
print(f"{count} files, +{added}/-{removed} lines")
```

---

## How It Works

### Architecture

```
git commit -m "..."
      │
      ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ pre-commit  │────▶│ git-lrc CLI      │────▶│ StagedDiff      │
│ hook        │     │ (Python)         │     │ Provider        │
│ (bash/ps1)  │     │                  │     │ (git diff       │
└─────────────┘     └───────┬──────────┘     │  --cached)      │
                            │                └────────┬────────┘
                    ┌───────▼──────────┐              │
                    │ Security Scanner │              │
                    │ (30 regex        │              │
                    │  patterns)       │              │
                    └───────┬──────────┘              │
                            │                         │
                    ┌───────▼─────────────────────────▼──┐
                    │         PR-Agent Engine             │
                    │  ┌─────────────────────────┐       │
                    │  │ Taxonomy Prompt (Jinja2) │       │
                    │  └────────────┬────────────┘       │
                    │               ▼                    │
                    │  ┌─────────────────────────┐       │
                    │  │ LiteLLM (GPT-4/Claude/  │       │
                    │  │ Ollama/LM Studio)        │       │
                    │  └────────────┬────────────┘       │
                    │               ▼                    │
                    │  ┌─────────────────────────┐       │
                    │  │ YAML → Structured JSON   │       │
                    │  │ + Taxonomy Classifier    │       │
                    │  │ + Severity Adjuster      │       │
                    │  └────────────┬────────────┘       │
                    └───────────────┼─────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │  .git/lrc/reviews/*.json      │
                    │  (persisted structured review) │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │  FastAPI Dashboard Server     │
                    │  http://localhost:{port}      │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │  Browser Dashboard            │
                    │  [Commit] [Skip]              │
                    └───────────────────────────────┘
```

### Data flow

1. **Hook fires** → `git-lrc review` runs
2. **StagedDiffProvider** collects `git diff --cached` as `FilePatchInfo` objects
3. **Security scanner** runs 30 regex patterns against `+` lines (pre-LLM, instant)
4. **Taxonomy prompt** is injected into PR-Agent's review template
5. **LLM** analyses the diff and returns YAML with pillar/category/pattern/severity per issue
6. **Classifier** validates LLM output against the 104-pattern taxonomy; falls back to keyword matching
7. **Severity adjuster** applies floor rules (Security → high, Secrets → critical)
8. **StructuredReview** is computed (risk score, fix time, top issues, file hotspots)
9. **JSON saved** to `.git/lrc/reviews/`
10. **Dashboard opens** — user reviews and clicks Commit or Skip
11. **Decision sent** → hook exits 0 (commit) or 1 (abort)

### File storage

```
.git/lrc/
├── reviews/
│   ├── 20260623T120000_abc12345.json    # Full structured review
│   ├── 20260623T113000_def67890.json
│   └── ...
├── state.json                            # Iteration counter, last review ID
├── review.md                             # Latest review as markdown
└── description.md                        # Latest PR description
```

---

## Troubleshooting

### "No staged changes to review"

You need to `git add` files before running `git-lrc review`:
```bash
git add src/my_file.py
git-lrc review
```

### "git-lrc not found"

Make sure the package is installed and on your PATH:
```bash
pip install -e .
which git-lrc  # Unix
where git-lrc  # Windows
```

### "LLM API error"

Check your API key configuration:
```bash
# Verify key is set
echo $OPENAI_API_KEY

# Or check .pr_agent.toml
cat .pr_agent.toml
```

### Hook isn't firing

Verify hooks are installed:
```bash
# Check if hook exists
cat .git/hooks/pre-commit

# Reinstall
git-lrc setup
```

### Dashboard doesn't open

The dashboard prints its URL to the terminal. If the browser doesn't open automatically, copy the URL manually:
```
🌐 Dashboard: http://localhost:52431
```

### Bypass the hook temporarily

```bash
# Skip for one commit
LRC_SKIP=1 git commit -m "quick fix"

# Or use git's --no-verify
git commit --no-verify -m "quick fix"
```

### Port conflict

The dashboard auto-selects a free port. If you need a specific port:
```python
from git_lrc_agent.server.app import start_dashboard
start_dashboard(review, port=9000)
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
