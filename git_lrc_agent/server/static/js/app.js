/**
 * git-lrc Dashboard — Main Application Script
 *
 * Single-file application that fetches review data from the FastAPI
 * backend and renders the file tree, diff viewer, inline comments,
 * summary deck, and issue navigator.
 */

// ═══════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════

const state = {
    review: null,
    files: [],
    issues: [],
    filteredIssues: [],
    currentFileIndex: -1,
    currentIssueIndex: -1,
    filters: {
        severity: new Set(["critical", "high", "medium", "low", "info"]),
        pillar: new Set(["Outages", "Breaches", "Technical Debt"]),
    },
};

// ═══════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", async () => {
    try {
        const [reviewRes, filesRes, allIssuesRes] = await Promise.all([
            fetch("/api/review").then(r => r.json()),
            fetch("/api/files").then(r => r.json()),
            fetch("/api/issues/all?sort_by=severity").then(r => r.json()),
        ]);

        state.review = reviewRes;
        state.files = filesRes;
        // Use all issues from the new endpoint (not limited to top_issues)
        state.issues = allIssuesRes || reviewRes.issues || [];
        state.filteredIssues = [...state.issues];

        renderFileTree();
        renderSummary();
        renderSeverityChart();
        renderCategoryChart();
        renderTopIssues();
        renderProseSummary();
        updateRiskMeter();
        updateFilterCounts();
        updateIssuePosition();

        // Select the first file with issues, or the first file.
        const firstWithIssues = state.files.findIndex(f => f.issue_count > 0);
        if (firstWithIssues >= 0) selectFile(firstWithIssues);
        else if (state.files.length > 0) selectFile(0);

        bindEvents();
    } catch (err) {
        console.error("Failed to load review data:", err);
        document.getElementById("diff-container").innerHTML =
            `<p class="empty-state">⚠ Failed to load review data.<br>${err.message}</p>`;
    }
});

// ═══════════════════════════════════════════════════════════
// Event binding
// ═══════════════════════════════════════════════════════════

function bindEvents() {
    // Navigation buttons.
    document.getElementById("btn-prev-issue").addEventListener("click", () => navigateIssue(-1));
    document.getElementById("btn-next-issue").addEventListener("click", () => navigateIssue(1));

    // Action buttons.
    document.getElementById("btn-commit").addEventListener("click", () => postDecision("commit"));
    document.getElementById("btn-skip").addEventListener("click", () => postDecision("skip"));
    document.getElementById("btn-copy-issues").addEventListener("click", copyIssues);

    // Filter checkboxes.
    document.querySelectorAll("[data-filter]").forEach(cb => {
        cb.addEventListener("change", () => {
            const filterType = cb.dataset.filter;
            const value = cb.value;
            if (cb.checked) state.filters[filterType].add(value);
            else state.filters[filterType].delete(value);
            applyFilters();
        });
    });

    // Keyboard shortcuts.
    document.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
        switch (e.key) {
            case "n": navigateIssue(1); break;
            case "p": navigateIssue(-1); break;
            case "j": navigateFile(1); break;
            case "k": navigateFile(-1); break;
            case "c": if (!e.ctrlKey && !e.metaKey) copyIssues(); break;
            case "Escape": break;
        }
    });
}

// ═══════════════════════════════════════════════════════════
// File tree
// ═══════════════════════════════════════════════════════════

function renderFileTree() {
    const ul = document.getElementById("file-tree");
    ul.innerHTML = "";

    state.files.forEach((file, idx) => {
        const li = document.createElement("li");
        li.dataset.index = idx;
        li.addEventListener("click", () => selectFile(idx));

        // Issue badge.
        const badge = document.createElement("span");
        badge.className = `file-issue-badge sev-${file.max_severity || "clean"}`;
        badge.textContent = file.issue_count || "✓";

        // File name.
        const name = document.createElement("span");
        name.className = "file-name";
        name.textContent = file.filename.split("/").pop();
        name.title = file.filename;

        // Stats.
        const stats = document.createElement("span");
        stats.className = "file-stats";
        stats.textContent = `+${file.lines_added} -${file.lines_removed}`;

        li.append(badge, name, stats);
        ul.appendChild(li);
    });

    document.getElementById("file-count").textContent = state.files.length;
}

function selectFile(index) {
    state.currentFileIndex = index;
    state.currentIssueIndex = -1;

    // Highlight in tree.
    document.querySelectorAll("#file-tree li").forEach((li, i) => {
        li.classList.toggle("active", i === index);
    });

    const file = state.files[index];
    document.getElementById("current-file-name").textContent = file.filename;

    // Render the diff for this file.
    renderDiff(file.filename);
    updateIssuePosition();
}

function navigateFile(direction) {
    const newIndex = state.currentFileIndex + direction;
    if (newIndex >= 0 && newIndex < state.files.length) {
        selectFile(newIndex);
    }
}

// ═══════════════════════════════════════════════════════════
// Diff viewer
// ═══════════════════════════════════════════════════════════

function renderDiff(filename) {
    const container = document.getElementById("diff-container");

    const file = state.files.find(f => f.filename === filename);
    const fileIssues = state.filteredIssues.filter(i => i.file === filename);

    if (!file) {
        container.innerHTML = `<p class="empty-state">File not found.</p>`;
        return;
    }

    if (!file.patch) {
        renderIssuesOnlyFallback(fileIssues, container);
        return;
    }

    let html = `<table class="diff-table">`;
    const lines = file.patch.split("\n");
    
    let oldLineNum = 0;
    let newLineNum = 0;
    const renderedIssueIds = new Set();

    function getIssuesForLine(lineNum) {
        return fileIssues.filter(issue => {
            return issue.line_end === lineNum && !renderedIssueIds.has(issue.id);
        });
    }

    lines.forEach(line => {
        if (line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("--- ") || line.startsWith("+++ ")) {
            return;
        }

        if (line.startsWith("@@ ")) {
            const match = line.match(/^@@ -(\d+),?\d* \+(\d+),?\d* @@/);
            if (match) {
                oldLineNum = parseInt(match[1], 10);
                newLineNum = parseInt(match[2], 10);
            }
            html += `<tr class="diff-line-hunk">
                <td class="diff-line-num"></td>
                <td class="diff-line-num"></td>
                <td class="diff-line-content">${escapeHtml(line)}</td>
            </tr>`;
            return;
        }

        if (line.startsWith("-")) {
            html += `<tr class="diff-line-del">
                <td class="diff-line-num">${oldLineNum}</td>
                <td class="diff-line-num"></td>
                <td class="diff-line-content">${escapeHtml(line)}</td>
            </tr>`;
            oldLineNum++;
        } else if (line.startsWith("+")) {
            html += `<tr class="diff-line-add">
                <td class="diff-line-num"></td>
                <td class="diff-line-num">${newLineNum}</td>
                <td class="diff-line-content">${escapeHtml(line)}</td>
            </tr>`;
            
            const lineIssues = getIssuesForLine(newLineNum);
            lineIssues.forEach((issue, idx) => {
                renderedIssueIds.add(issue.id);
                html += `<tr>
                    <td colspan="3">${renderInlineComment(issue, idx)}</td>
                </tr>`;
            });
            
            newLineNum++;
        } else {
            const cleanLine = line.startsWith(" ") ? line.substring(1) : line;
            html += `<tr class="diff-line-context">
                <td class="diff-line-num">${oldLineNum}</td>
                <td class="diff-line-num">${newLineNum}</td>
                <td class="diff-line-content">${escapeHtml(cleanLine)}</td>
            </tr>`;
            
            const lineIssues = getIssuesForLine(newLineNum);
            lineIssues.forEach((issue, idx) => {
                renderedIssueIds.add(issue.id);
                html += `<tr>
                    <td colspan="3">${renderInlineComment(issue, idx)}</td>
                </tr>`;
            });

            oldLineNum++;
            newLineNum++;
        }
    });

    fileIssues.forEach((issue, idx) => {
        if (!renderedIssueIds.has(issue.id)) {
            html += `<tr class="diff-line-hunk">
                <td colspan="3">@@ Line ${issue.line_start}-${issue.line_end} (outside diff context) @@</td>
            </tr>
            <tr>
                <td colspan="3">${renderInlineComment(issue, idx)}</td>
            </tr>`;
        }
    });

    html += `</table>`;
    container.innerHTML = html;
}

function renderIssuesOnlyFallback(fileIssues, container) {
    let html = `<table class="diff-table">`;
    if (fileIssues.length > 0) {
        fileIssues.forEach((issue, idx) => {
            html += `<tr class="diff-line-hunk"><td class="diff-line-num"></td><td class="diff-line-content">@@ Lines ${issue.line_start}-${issue.line_end} @@</td></tr>`;
            if (issue.code_snippet) {
                issue.code_snippet.split("\n").forEach((line, lineIdx) => {
                    const lineNum = issue.line_start + lineIdx;
                    html += `<tr class="diff-line-add"><td class="diff-line-num">${lineNum}</td><td class="diff-line-content">${escapeHtml(line)}</td></tr>`;
                });
            } else if (issue.context_lines && issue.context_lines.length > 0) {
                issue.context_lines.forEach((line, lineIdx) => {
                    const lineNum = issue.line_start + lineIdx;
                    html += `<tr class="diff-line-add"><td class="diff-line-num">${lineNum}</td><td class="diff-line-content">${escapeHtml(line)}</td></tr>`;
                });
            } else {
                for (let ln = issue.line_start; ln <= issue.line_end; ln++) {
                    html += `<tr class="diff-line-highlight"><td class="diff-line-num">${ln}</td><td class="diff-line-content">...</td></tr>`;
                }
            }
            html += `<tr><td colspan="2">${renderInlineComment(issue, idx)}</td></tr>`;
        });
    } else {
        html += `<tr><td colspan="2" class="empty-state" style="padding:40px">✅ No issues found in this file.</td></tr>`;
    }
    html += `</table>`;
    container.innerHTML = html;
}

function renderInlineComment(issue, idx) {
    const suggestion = issue.suggestion
        ? `<div class="inline-comment-suggestion"><strong>💡 Suggestion:</strong><br>${escapeHtml(issue.suggestion)}</div>`
        : "";

    // Function name display
    const funcName = issue.function_name
        ? `<span class="inline-comment-func">⚡ <code>${escapeHtml(issue.function_name)}()</code></span>`
        : "";

    // Fix confidence bar
    const confidence = issue.fix_confidence != null ? issue.fix_confidence : 50;
    const confColor = confidence >= 80 ? "var(--accent-success)"
        : confidence >= 50 ? "var(--accent-warning)"
        : "var(--sev-critical)";
    const confidenceBar = `
        <div class="inline-comment-confidence">
            <span class="confidence-label">Fix confidence:</span>
            <div class="confidence-track">
                <div class="confidence-fill" style="width:${confidence}%;background:${confColor}"></div>
            </div>
            <span class="confidence-value" style="color:${confColor}">${confidence}%</span>
        </div>
    `;

    // Tags display
    const tags = (issue.tags && issue.tags.length > 0)
        ? `<div class="inline-comment-tags">${issue.tags.map(t => `<span class="issue-tag tag-${t}">${t}</span>`).join("")}</div>`
        : "";

    return `
        <div class="inline-comment" data-issue-index="${idx}" id="issue-${issue.id}">
            <div class="inline-comment-header">
                <span class="severity-badge ${issue.severity}">${issue.severity}</span>
                <span class="category-tag">${issue.category} → ${issue.pattern}</span>
                <span class="inline-comment-title">${escapeHtml(issue.title)}</span>
                ${funcName}
            </div>
            <div class="inline-comment-body">
                <p>${escapeHtml(issue.message)}</p>
                ${tags}
                ${suggestion}
                ${confidenceBar}
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════
// Issue navigator
// ═══════════════════════════════════════════════════════════

function navigateIssue(direction) {
    if (state.filteredIssues.length === 0) return;

    state.currentIssueIndex += direction;
    if (state.currentIssueIndex < 0) state.currentIssueIndex = state.filteredIssues.length - 1;
    if (state.currentIssueIndex >= state.filteredIssues.length) state.currentIssueIndex = 0;

    const issue = state.filteredIssues[state.currentIssueIndex];

    // Find and select the file containing this issue.
    const fileIdx = state.files.findIndex(f => f.filename === issue.file);
    if (fileIdx >= 0 && fileIdx !== state.currentFileIndex) {
        selectFile(fileIdx);
    }

    // Scroll to the issue card.
    const card = document.getElementById(`issue-${issue.id}`);
    if (card) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.style.outline = `2px solid ${getComputedStyle(document.documentElement).getPropertyValue("--accent-primary")}`;
        setTimeout(() => card.style.outline = "none", 2000);
    }

    updateIssuePosition();
}

function updateIssuePosition() {
    const total = state.filteredIssues.length;
    const current = state.currentIssueIndex >= 0 ? state.currentIssueIndex + 1 : 0;
    document.getElementById("issue-position").textContent = `${current} of ${total}`;
}

// ═══════════════════════════════════════════════════════════
// Summary deck
// ═══════════════════════════════════════════════════════════

function renderSummary() {
    const s = state.review.summary || {};
    document.getElementById("stat-total-issues").textContent = s.total_issues || 0;
    document.getElementById("stat-files").textContent = state.files.length;

    const mins = s.estimated_fix_time_minutes || 0;
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    document.getElementById("stat-fix-time").textContent = hours > 0 ? `${hours}h ${remMins}m` : `${remMins}m`;
}

function updateRiskMeter() {
    const score = state.review.summary?.risk_score || 0;
    const fill = document.getElementById("risk-bar-fill");
    const value = document.getElementById("risk-value");

    fill.style.width = `${score}%`;
    fill.className = "risk-bar-fill";
    if (score >= 75) fill.classList.add("risk-critical");
    else if (score >= 50) fill.classList.add("risk-high");
    else if (score >= 25) fill.classList.add("risk-medium");

    value.textContent = score;
    value.style.color = score >= 75 ? "var(--sev-critical)"
        : score >= 50 ? "var(--sev-high)"
        : score >= 25 ? "var(--sev-medium)"
        : "var(--accent-success)";
}

function renderSeverityChart() {
    const counts = state.review.summary?.issues_by_severity || {};
    const total = state.review.summary?.total_issues || 0;
    const max = Math.max(1, ...Object.values(counts));
    const container = document.getElementById("severity-chart");

    const sevOrder = ["critical", "high", "medium", "low", "info"];
    const colors = {
        critical: "var(--sev-critical)", high: "var(--sev-high)",
        medium: "var(--sev-medium)", low: "var(--sev-low)", info: "var(--sev-info)",
    };

    container.innerHTML = sevOrder.map(sev => {
        const count = counts[sev] || 0;
        const pct = (count / max) * 100;
        const pctOfTotal = total > 0 ? ((count / total) * 100).toFixed(0) : 0;
        return `<div class="sev-row">
            <span class="sev-label">${sev}</span>
            <div class="sev-bar-track"><div class="sev-bar-fill" style="width:${pct}%;background:${colors[sev]}"></div></div>
            <span class="sev-count">${count}</span>
        </div>`;
    }).join("");
}

function renderCategoryChart() {
    const counts = state.review.summary?.issues_by_category || {};
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const container = document.getElementById("category-chart");

    container.innerHTML = sorted.map(([name, count]) =>
        `<div class="cat-row"><span class="cat-name">${name}</span><span class="cat-count">${count}</span></div>`
    ).join("");
}

function renderTopIssues() {
    const topIssues = state.review.summary?.top_issues || [];
    const container = document.getElementById("top-issues");
    const icons = { critical: "🔴", high: "🟠", medium: "🟡", low: "🔵", info: "⚪" };

    // Show more issues than before (up to 15)
    const displayIssues = topIssues.slice(0, 15);

    container.innerHTML = displayIssues.map(issue => {
        const confidence = issue.fix_confidence != null ? issue.fix_confidence : 50;
        const confColor = confidence >= 80 ? "var(--accent-success)"
            : confidence >= 50 ? "var(--accent-warning)"
            : "var(--sev-critical)";
        const suggestionPreview = issue.suggestion
            ? `<div class="top-issue-suggestion">💡 ${escapeHtml(issue.suggestion.substring(0, 60))}${issue.suggestion.length > 60 ? "..." : ""}</div>`
            : "";
        const tagsHtml = (issue.tags && issue.tags.length > 0)
            ? `<div class="top-issue-tags">${issue.tags.map(t => `<span class="issue-tag-sm tag-${t}">${t}</span>`).join("")}</div>`
            : "";

        return `<div class="top-issue" onclick="jumpToIssue('${issue.id}')">
            <div class="top-issue-title">${icons[issue.severity] || ""} ${escapeHtml(issue.title)}</div>
            <div class="top-issue-file">${issue.file}:${issue.line_start}</div>
            ${suggestionPreview}
            ${tagsHtml}
        </div>`;
    }).join("") || "<p class='empty-state'>No critical issues found.</p>";
}

function renderProseSummary() {
    const prose = state.review.summary?.prose_summary || "";
    document.getElementById("prose-summary").textContent = prose || "No summary available.";
}

// ═══════════════════════════════════════════════════════════
// Filters
// ═══════════════════════════════════════════════════════════

function applyFilters() {
    state.filteredIssues = state.issues.filter(issue =>
        state.filters.severity.has(issue.severity) &&
        state.filters.pillar.has(issue.pillar)
    );
    state.currentIssueIndex = -1;

    // Re-render the current file's diff.
    if (state.currentFileIndex >= 0) {
        renderDiff(state.files[state.currentFileIndex].filename);
    }
    updateIssuePosition();
    updateFilterCounts();
}

function updateFilterCounts() {
    const sevCounts = {};
    const pillarCounts = {};
    state.issues.forEach(i => {
        sevCounts[i.severity] = (sevCounts[i.severity] || 0) + 1;
        pillarCounts[i.pillar] = (pillarCounts[i.pillar] || 0) + 1;
    });

    document.querySelectorAll("[data-count-severity]").forEach(el => {
        el.textContent = sevCounts[el.dataset.countSeverity] || 0;
    });
    document.querySelectorAll("[data-count-pillar]").forEach(el => {
        el.textContent = pillarCounts[el.dataset.countPillar] || 0;
    });
}

// ═══════════════════════════════════════════════════════════
// Actions
// ═══════════════════════════════════════════════════════════

async function postDecision(decision) {
    try {
        await fetch("/api/decision", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ decision }),
        });
        document.body.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:16px">
                <h1 style="font-size:2rem">${decision === "commit" ? "✅ Committed" : "⏭ Skipped"}</h1>
                <p style="color:var(--text-secondary)">You can close this tab.</p>
            </div>
        `;
    } catch (err) {
        alert("Failed to submit decision: " + err.message);
    }
}

function copyIssues() {
    const issues = state.filteredIssues;
    if (!issues.length) { alert("No issues to copy."); return; }

    const markdown = issues.map(i =>
        `### ${i.severity.toUpperCase()}: ${i.title}\n` +
        `**File:** ${i.file}:${i.line_start}\n` +
        `**Category:** ${i.category} → ${i.pattern}\n` +
        (i.function_name ? `**Function:** ${i.function_name}\n` : "") +
        (i.tags && i.tags.length ? `**Tags:** ${i.tags.join(", ")}\n` : "") +
        `**Fix Confidence:** ${i.fix_confidence != null ? i.fix_confidence : 50}%\n\n` +
        `${i.message}\n` +
        (i.suggestion ? `\n**Suggestion:** ${i.suggestion}\n` : "")
    ).join("\n---\n\n");

    navigator.clipboard.writeText(markdown).then(() => {
        const btn = document.getElementById("btn-copy-issues");
        btn.textContent = "✅ Copied!";
        setTimeout(() => btn.textContent = "📋 Copy Issues", 2000);
    });
}

function jumpToIssue(issueId) {
    const idx = state.filteredIssues.findIndex(i => i.id === issueId);
    if (idx >= 0) {
        state.currentIssueIndex = idx - 1; // Will be incremented by navigateIssue.
        navigateIssue(1);
    }
}

// ═══════════════════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════════════════

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
