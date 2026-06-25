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

    // Tab toggles.
    const tabReview = document.getElementById("tab-review");
    const tabHealth = document.getElementById("tab-health");
    const contentReview = document.getElementById("tab-content-review");
    const contentHealth = document.getElementById("tab-content-health");

    if (tabReview && tabHealth && contentReview && contentHealth) {
        tabReview.addEventListener("click", () => {
            tabReview.classList.add("active");
            tabHealth.classList.remove("active");
            contentReview.classList.add("active-tab");
            contentHealth.classList.remove("active-tab");
        });

        tabHealth.addEventListener("click", () => {
            tabHealth.classList.add("active");
            tabReview.classList.remove("active");
            contentHealth.classList.add("active-tab");
            contentReview.classList.remove("active-tab");
            loadHealthMetrics();
        });
    }
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

function selectFile(index, preserveIssueIndex = false) {
    state.currentFileIndex = index;
    if (!preserveIssueIndex) {
        const file = state.files[index];
        const firstIssueIdx = state.filteredIssues.findIndex(i => i.file === file.filename);
        state.currentIssueIndex = firstIssueIdx;
    }

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
        ? `<div class="inline-comment-suggestion">
            <div class="suggestion-header">💡 Suggestion:</div>
            <pre class="suggestion-code">${escapeHtml(issue.suggestion)}</pre>
           </div>`
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
                <div class="confidence-fill" style="width:${confidence}%;background-color:${confColor}"></div>
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
        selectFile(fileIdx, true);
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

// ═══════════════════════════════════════════════════════════
// Project Health Dashboard Renderer
// ═══════════════════════════════════════════════════════════

async function loadHealthMetrics() {
    try {
        const [metricsRes, historyRes] = await Promise.all([
            fetch("/api/metrics").then(r => r.json()),
            fetch("/api/metrics/history").then(r => r.json()),
        ]);

        renderHealthDashboard(metricsRes.metrics, metricsRes.trend);
        renderTrendChart(historyRes);
    } catch (err) {
        console.error("Failed to load health metrics:", err);
    }
}

function renderHealthDashboard(m, t) {
    // 1. Overall Health Score Circle Gauge
    const score = m.overall_score || 0;
    const textEl = document.getElementById("health-score-text");
    const fillEl = document.getElementById("health-gauge-fill");
    const descEl = document.getElementById("health-status-desc");

    if (textEl) textEl.textContent = `${score}%`;
    if (fillEl) {
        const circ = 251.3; // 2 * PI * r = 2 * 3.14159 * 40
        const offset = circ - (score / 100) * circ;
        fillEl.style.strokeDasharray = circ;
        fillEl.style.strokeDashoffset = offset;
        
        let color = "var(--accent-success)";
        if (score < 50) color = "var(--sev-critical)";
        else if (score < 75) color = "var(--accent-warning)";
        fillEl.style.stroke = color;
    }
    if (descEl) {
        descEl.textContent = m.quality_status || "UNKNOWN";
        descEl.className = "health-status-desc status-" + (m.quality_status || "ACCEPTABLE").toLowerCase();
    }

    // 2. Gate Status Banner
    const banner = document.getElementById("gate-status-banner");
    const gateIcon = document.getElementById("gate-icon");
    const gateTitle = document.getElementById("gate-title");
    const gateMsg = document.getElementById("gate-message");

    if (banner) {
        banner.className = `gate-status-banner gate-${m.quality_gates}`;
        if (m.quality_gates === "PASS") {
            if (gateIcon) gateIcon.textContent = "🛡️";
            if (gateTitle) gateTitle.textContent = "Quality Gate Passed";
            if (gateMsg) gateMsg.textContent = "All health metrics meet the configured target thresholds.";
        } else if (m.quality_gates === "WARN") {
            if (gateIcon) gateIcon.textContent = "⚠️";
            if (gateTitle) gateTitle.textContent = "Quality Gate Warning";
            if (gateMsg) gateMsg.textContent = "Some metrics are warning. Consider resolving smells and bugs.";
        } else {
            if (gateIcon) gateIcon.textContent = "🚨";
            if (gateTitle) gateTitle.textContent = "Quality Gate Failed";
            if (gateMsg) gateMsg.textContent = "Critical security vulnerabilities or bugs exceed failure limits.";
        }
    }

    // 3. Ratings
    const secEl = document.getElementById("rating-security");
    const relEl = document.getElementById("rating-reliability");
    const maintEl = document.getElementById("rating-maintainability");

    if (secEl) {
        secEl.textContent = m.security_rating;
        secEl.className = `rating-badge rating-${m.security_rating}`;
    }
    if (relEl) {
        relEl.textContent = m.reliability_rating;
        relEl.className = `rating-badge rating-${m.reliability_rating}`;
    }
    if (maintEl) {
        maintEl.textContent = m.maintainability_rating;
        maintEl.className = `rating-badge rating-${m.maintainability_rating}`;
    }

    // 4. Quantitative Metrics
    const bugsEl = document.getElementById("metrics-bugs");
    const vulnsEl = document.getElementById("metrics-vulns");
    const smellsEl = document.getElementById("metrics-smells");
    const locEl = document.getElementById("metrics-loc");
    const debtEl = document.getElementById("metrics-debt");
    const openEl = document.getElementById("metrics-open");

    if (bugsEl) bugsEl.textContent = m.bugs;
    if (vulnsEl) vulnsEl.textContent = m.vulnerabilities;
    if (smellsEl) smellsEl.textContent = m.code_smells;
    if (locEl) locEl.textContent = m.loc;
    if (debtEl) debtEl.textContent = m.technical_debt;
    if (openEl) openEl.textContent = m.open_issues;

    // 5. Trends deltas
    const tBugs = document.getElementById("trend-bugs");
    const tVulns = document.getElementById("trend-vulns");

    if (tBugs) renderTrendDelta(tBugs, t.bugs_trend);
    if (tVulns) renderTrendDelta(tVulns, t.vulns_trend);
}

function renderTrendDelta(el, val) {
    if (val > 0) {
        el.textContent = `📈 +${val}`;
        el.className = "metric-trend trend-decline";
    } else if (val < 0) {
        el.textContent = `📉 ${val}`;
        el.className = "metric-trend trend-improve";
    } else {
        el.textContent = "➡️ 0";
        el.className = "metric-trend trend-neutral";
    }
}

function renderTrendChart(history) {
    const svg = document.getElementById("trend-chart-svg");
    if (!svg) return;
    svg.innerHTML = "";

    if (!history || history.length === 0) {
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", "300");
        text.setAttribute("y", "100");
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("fill", "var(--text-tertiary)");
        text.textContent = "Insufficient historical reviews to plot trend.";
        svg.appendChild(text);
        return;
    }

    const padding = { top: 20, right: 30, bottom: 30, left: 40 };
    const width = 600;
    const height = 200;
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;

    const pointsCount = history.length;

    const getX = (idx) => {
        if (pointsCount <= 1) return padding.left + chartWidth / 2;
        return padding.left + (idx / (pointsCount - 1)) * chartWidth;
    };

    const getY = (val) => {
        return padding.top + chartHeight - (val / 100) * chartHeight;
    };

    // Grid lines (y axis ticks)
    for (let i = 0; i <= 4; i++) {
        const yVal = i * 25;
        const y = getY(yVal);
        
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", padding.left);
        line.setAttribute("y1", y);
        line.setAttribute("x2", width - padding.right);
        line.setAttribute("y2", y);
        line.setAttribute("stroke", "var(--border-muted)");
        line.setAttribute("stroke-dasharray", "4,4");
        svg.appendChild(line);

        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", padding.left - 8);
        text.setAttribute("y", y + 4);
        text.setAttribute("text-anchor", "end");
        text.setAttribute("fill", "var(--text-tertiary)");
        text.setAttribute("font-size", "9px");
        text.textContent = `${yVal}%`;
        svg.appendChild(text);
    }

    let pathD = "";
    let areaD = `M ${getX(0)} ${padding.top + chartHeight}`;

    history.forEach((item, idx) => {
        const val = item.overall_health_score || 0;
        const x = getX(idx);
        const y = getY(val);

        if (idx === 0) {
            pathD += `M ${x} ${y}`;
            areaD += ` L ${x} ${y}`;
        } else {
            pathD += ` L ${x} ${y}`;
            areaD += ` L ${x} ${y}`;
        }
    });

    areaD += ` L ${getX(pointsCount - 1)} ${padding.top + chartHeight} Z`;

    if (pointsCount > 0) {
        const areaPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        areaPath.setAttribute("d", areaD);
        areaPath.setAttribute("fill", "url(#chart-area-grad)");
        svg.appendChild(areaPath);
    }

    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    const grad = document.createElementNS("http://www.w3.org/2000/svg", "linearGradient");
    grad.setAttribute("id", "chart-area-grad");
    grad.setAttribute("x1", "0");
    grad.setAttribute("y1", "0");
    grad.setAttribute("x2", "0");
    grad.setAttribute("y2", "1");
    
    const stop1 = document.createElementNS("http://www.w3.org/2000/svg", "stop");
    stop1.setAttribute("offset", "0%");
    stop1.setAttribute("stop-color", "var(--accent-primary)");
    stop1.setAttribute("stop-opacity", "0.25");
    
    const stop2 = document.createElementNS("http://www.w3.org/2000/svg", "stop");
    stop2.setAttribute("offset", "100%");
    stop2.setAttribute("stop-color", "var(--accent-primary)");
    stop2.setAttribute("stop-opacity", "0.0");
    
    grad.appendChild(stop1);
    grad.appendChild(stop2);
    defs.appendChild(grad);
    svg.appendChild(defs);

    if (pointsCount > 0) {
        const linePath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        linePath.setAttribute("d", pathD);
        linePath.setAttribute("fill", "none");
        linePath.setAttribute("stroke", "var(--accent-primary)");
        linePath.setAttribute("stroke-width", "2");
        svg.appendChild(linePath);
    }

    history.forEach((item, idx) => {
        const val = item.overall_health_score || 0;
        const x = getX(idx);
        const y = getY(val);

        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", x);
        circle.setAttribute("cy", y);
        circle.setAttribute("r", "4");
        circle.setAttribute("fill", "var(--bg-secondary)");
        circle.setAttribute("stroke", "var(--accent-primary)");
        circle.setAttribute("stroke-width", "2");

        const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
        const dateStr = item.timestamp ? new Date(item.timestamp).toLocaleDateString() : "";
        title.textContent = `Review: ${item.review_id}\nDate: ${dateStr}\nScore: ${val.toFixed(1)}%\nGates: ${item.quality_gates_status}`;
        circle.appendChild(title);

        svg.appendChild(circle);

        if (idx === 0 || idx === pointsCount - 1 || pointsCount <= 5 || idx % Math.ceil(pointsCount / 5) === 0) {
            const labelText = document.createElementNS("http://www.w3.org/2000/svg", "text");
            labelText.setAttribute("x", x);
            labelText.setAttribute("y", padding.top + chartHeight + 15);
            labelText.setAttribute("text-anchor", "middle");
            labelText.setAttribute("fill", "var(--text-tertiary)");
            labelText.setAttribute("font-size", "8px");
            labelText.textContent = item.review_id.split("_").pop() || "";
            svg.appendChild(labelText);
        }
    });
}
