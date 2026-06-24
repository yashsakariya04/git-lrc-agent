"""Complete issue taxonomy: 3 pillars, 10 categories, 100+ failure patterns.

This module defines the canonical risk taxonomy used by git-lrc-agent.
Every issue identified during review is mapped to exactly one
(pillar → category → pattern) triple.

The taxonomy is modelled after git-lrc's classification system:
  • Outages   — things that crash, corrupt, or slow down production
  • Breaches  — things that leak data or violate regulations
  • Technical Debt — things that make the codebase harder/costlier to maintain
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pattern:
    """A single failure pattern within a category."""
    name: str
    description: str = ""
    keywords: tuple[str, ...] = ()  # used by the keyword classifier fallback


@dataclass(frozen=True)
class Category:
    """A risk category containing multiple patterns."""
    name: str
    patterns: tuple[Pattern, ...]

    @property
    def pattern_names(self) -> list[str]:
        return [p.name for p in self.patterns]


@dataclass(frozen=True)
class PillarDef:
    """Top-level risk pillar."""
    name: str
    categories: tuple[Category, ...]

    @property
    def category_names(self) -> list[str]:
        return [c.name for c in self.categories]


# ---------------------------------------------------------------------------
# Full taxonomy definition
# ---------------------------------------------------------------------------

OUTAGES = PillarDef(
    name="Outages",
    categories=(
        Category("Reliability", (
            Pattern("Error Handling", keywords=("exception", "error", "catch", "try", "throw", "raise", "fail", "crash")),
            Pattern("Fault Tolerance", keywords=("fallback", "circuit breaker", "graceful", "degrade")),
            Pattern("Retry Logic", keywords=("retry", "backoff", "attempt", "retries")),
            Pattern("Timeout Management", keywords=("timeout", "deadline", "ttl", "expire")),
            Pattern("Resilience Patterns", keywords=("bulkhead", "resilience", "recovery")),
            Pattern("Availability Risks", keywords=("availability", "uptime", "downtime", "outage")),
            Pattern("Data Integrity", keywords=("integrity", "corrupt", "consistency", "transaction")),
            Pattern("Race Conditions", keywords=("race", "concurrent", "atomic", "lock", "mutex", "thread-safe")),
            Pattern("Resource Cleanup", keywords=("close", "cleanup", "dispose", "finally", "leak", "resource")),
            Pattern("Failure Recovery", keywords=("recover", "rollback", "compensat", "undo")),
        )),
        Category("Correctness", (
            Pattern("Logic Errors", keywords=("logic", "incorrect", "wrong", "bug", "off-by-one")),
            Pattern("Edge Cases", keywords=("edge case", "boundary", "corner case", "empty", "zero", "null")),
            Pattern("Data Validation", keywords=("validat", "sanitiz", "check", "verify", "assert")),
            Pattern("State Management", keywords=("state", "stale", "inconsistent", "synchroni")),
            Pattern("Concurrency Bugs", keywords=("deadlock", "race condition", "thread", "concurrent")),
            Pattern("Business Rule Violations", keywords=("business rule", "invariant", "constraint", "domain")),
            Pattern("Numerical Accuracy", keywords=("precision", "rounding", "overflow", "underflow", "float")),
            Pattern("Null Handling", keywords=("null", "none", "nil", "undefined", "optional", "nullable")),
            Pattern("Type Safety", keywords=("type", "cast", "coerce", "any", "dynamic")),
            Pattern("API Contract Violations", keywords=("contract", "interface", "schema", "breaking change")),
        )),
        Category("Performance", (
            Pattern("Database Efficiency", keywords=("query", "n+1", "index", "slow query", "database", "sql")),
            Pattern("Algorithmic Complexity", keywords=("complexity", "O(n", "quadratic", "exponential", "nested loop")),
            Pattern("Memory Usage", keywords=("memory", "heap", "allocation", "gc", "oom")),
            Pattern("CPU Utilization", keywords=("cpu", "compute", "spin", "busy wait", "blocking")),
            Pattern("Network Efficiency", keywords=("network", "latency", "round trip", "bandwidth", "payload")),
            Pattern("Caching", keywords=("cache", "memoiz", "ttl", "invalidat")),
            Pattern("Concurrency", keywords=("parallel", "async", "await", "thread pool", "worker")),
            Pattern("Resource Contention", keywords=("contention", "bottleneck", "starvation", "throttl")),
            Pattern("Rendering Performance", keywords=("render", "repaint", "reflow", "dom", "virtual")),
            Pattern("Startup Performance", keywords=("startup", "boot", "init", "cold start", "warm")),
        )),
        Category("Scalability", (
            Pattern("Horizontal Scaling", keywords=("horizontal", "shard", "partition", "replicate")),
            Pattern("Vertical Scaling", keywords=("vertical", "memory limit", "cpu limit", "resize")),
            Pattern("Distributed Systems", keywords=("distributed", "consensus", "eventual", "CAP")),
            Pattern("Load Balancing", keywords=("load balanc", "sticky session", "round robin")),
            Pattern("Capacity Planning", keywords=("capacity", "growth", "forecast", "headroom")),
            Pattern("Bottleneck Risks", keywords=("bottleneck", "single point", "chokepoint")),
            Pattern("Concurrency Limits", keywords=("max connection", "pool size", "limit", "semaphore")),
            Pattern("Service Growth Constraints", keywords=("monolith", "coupling", "service boundary")),
            Pattern("Database Scaling", keywords=("read replica", "write scale", "connection pool")),
            Pattern("Queue Backpressure", keywords=("queue", "backpressure", "overflow", "buffer")),
        )),
    ),
)

BREACHES = PillarDef(
    name="Breaches",
    categories=(
        Category("Security", (
            Pattern("Authentication", keywords=("auth", "login", "password", "credential", "token", "jwt")),
            Pattern("Authorization", keywords=("authz", "permission", "role", "access control", "rbac", "acl")),
            Pattern("Secrets Management", keywords=("secret", "api key", "api_key", "private key", "hardcoded")),
            Pattern("Input Validation", keywords=("injection", "sanitiz", "escap", "xss", "input")),
            Pattern("Injection Vulnerabilities", keywords=("sql inject", "command inject", "template inject", "ldap")),
            Pattern("Cryptography", keywords=("crypto", "encrypt", "decrypt", "hash", "salt", "hmac", "tls")),
            Pattern("Dependency Vulnerabilities", keywords=("cve", "vulnerability", "outdated", "dependency")),
            Pattern("Data Exposure", keywords=("expose", "leak", "log sensitive", "pii", "personal data")),
            Pattern("Session Management", keywords=("session", "cookie", "csrf", "token expir")),
            Pattern("Security Logging & Auditing", keywords=("audit", "security log", "monitor", "alert")),
        )),
        Category("Compliance & Governance", (
            Pattern("Privacy", keywords=("privacy", "gdpr", "ccpa", "consent", "data subject")),
            Pattern("Regulatory Compliance", keywords=("regulat", "complian", "hipaa", "sox", "pci")),
            Pattern("Auditability", keywords=("audit trail", "audit log", "traceab")),
            Pattern("Data Retention", keywords=("retention", "ttl", "expir", "purge", "delete policy")),
            Pattern("Data Residency", keywords=("residency", "region", "sovereign", "cross-border")),
            Pattern("Licensing", keywords=("license", "copyright", "gpl", "mit", "apache", "proprietary")),
            Pattern("Policy Enforcement", keywords=("policy", "enforce", "gate", "guardrail")),
            Pattern("Access Controls", keywords=("access control", "least privilege", "deny by default")),
            Pattern("Change Management", keywords=("change manage", "approval", "review gate")),
            Pattern("Governance Standards", keywords=("governance", "standard", "framework", "best practice")),
        )),
    ),
)

TECHNICAL_DEBT = PillarDef(
    name="Technical Debt",
    categories=(
        Category("Maintainability", (
            Pattern("Code Complexity", keywords=("complex", "cyclomatic", "nested", "deep")),
            Pattern("Readability", keywords=("readab", "unclear", "confus", "magic number")),
            Pattern("Documentation", keywords=("document", "docstring", "comment", "jsdoc", "readme")),
            Pattern("Code Duplication", keywords=("duplicat", "copy-paste", "dry", "repeat")),
            Pattern("Dead Code", keywords=("dead code", "unused", "unreachable", "deprecat")),
            Pattern("Naming Quality", keywords=("naming", "variable name", "misleading name")),
            Pattern("Testability", keywords=("testab", "mock", "stub", "inject", "decouple")),
            Pattern("Technical Debt", keywords=("tech debt", "todo", "fixme", "hack", "workaround")),
            Pattern("Refactoring Opportunities", keywords=("refactor", "simplif", "extract", "inline")),
            Pattern("Configuration Management", keywords=("config", "hardcoded", "env var", "setting")),
            Pattern("UI/UX", keywords=("ui", "ux", "usability", "accessibility")),
            Pattern("Accessibility", keywords=("a11y", "aria", "screen reader", "wcag")),
        )),
        Category("Architecture", (
            Pattern("Separation of Concerns", keywords=("separation", "concern", "responsibility")),
            Pattern("Modularity", keywords=("modular", "component", "encapsulat")),
            Pattern("Coupling", keywords=("coupling", "coupled", "tight", "loose")),
            Pattern("Cohesion", keywords=("cohesion", "cohesive", "scattered")),
            Pattern("Layering Violations", keywords=("layer", "violat", "bypass", "leaky abstraction")),
            Pattern("Dependency Management", keywords=("dependency", "import", "require", "circular")),
            Pattern("Service Boundaries", keywords=("service", "boundary", "api surface", "contract")),
            Pattern("Domain Modeling", keywords=("domain", "model", "entity", "value object")),
            Pattern("API Design", keywords=("api design", "endpoint", "rest", "graphql")),
            Pattern("Extensibility", keywords=("extensib", "plugin", "hook", "interface")),
        )),
        Category("Developer Experience", (
            Pattern("Testing", keywords=("test", "unit test", "integration test", "coverage")),
            Pattern("CI/CD", keywords=("ci", "cd", "pipeline", "build", "deploy")),
            Pattern("Build System", keywords=("build", "webpack", "vite", "makefile", "gradle")),
            Pattern("Local Development", keywords=("local dev", "docker compose", "dev server")),
            Pattern("Debuggability", keywords=("debug", "trace", "inspect", "breakpoint")),
            Pattern("Observability", keywords=("observ", "metric", "log", "tracing", "monitor")),
            Pattern("Deployment Process", keywords=("deploy", "rollout", "canary", "blue-green")),
            Pattern("Automation", keywords=("automat", "script", "tool", "makefile")),
            Pattern("Developer Tooling", keywords=("tooling", "lint", "format", "editor")),
            Pattern("Documentation Quality", keywords=("docs quality", "stale docs", "readme")),
            Pattern("UI/UX", keywords=("developer ui", "cli ux", "console")),
            Pattern("Accessibility", keywords=("a11y", "assistive", "screen reader")),
        )),
        Category("Cost", (
            Pattern("Cloud Resource Waste", keywords=("cloud", "resource", "waste", "idle", "unused")),
            Pattern("Infrastructure Overprovisioning", keywords=("overprovision", "oversized", "right-siz")),
            Pattern("Storage Optimization", keywords=("storage", "disk", "blob", "s3", "cleanup")),
            Pattern("Database Cost Optimization", keywords=("database cost", "rds", "dynamo", "read unit")),
            Pattern("Excessive API Usage", keywords=("api usage", "rate limit", "quota", "billing")),
            Pattern("Third-Party Service Costs", keywords=("third-party", "saas", "subscription", "vendor")),
            Pattern("Redundant Computation", keywords=("redundant", "duplicate compute", "recalculat")),
            Pattern("LLM Token Consumption", keywords=("token", "llm cost", "prompt length", "gpt")),
            Pattern("Caching Opportunities", keywords=("cache miss", "uncached", "recompute")),
            Pattern("Data Transfer Costs", keywords=("egress", "transfer cost", "bandwidth", "cdn")),
        )),
    ),
)

# Ordered list of all pillars.
ALL_PILLARS: tuple[PillarDef, ...] = (OUTAGES, BREACHES, TECHNICAL_DEBT)

# Flat lookup helpers.
PILLAR_BY_NAME: dict[str, PillarDef] = {p.name: p for p in ALL_PILLARS}

CATEGORY_BY_NAME: dict[str, tuple[PillarDef, Category]] = {}
for _pillar in ALL_PILLARS:
    for _cat in _pillar.categories:
        CATEGORY_BY_NAME[_cat.name] = (_pillar, _cat)

PATTERN_BY_NAME: dict[str, tuple[PillarDef, Category, Pattern]] = {}
for _pillar in ALL_PILLARS:
    for _cat in _pillar.categories:
        for _pat in _cat.patterns:
            PATTERN_BY_NAME[_pat.name] = (_pillar, _cat, _pat)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_valid_categories() -> list[str]:
    """Return all valid category names."""
    return list(CATEGORY_BY_NAME.keys())


def get_valid_patterns() -> list[str]:
    """Return all valid pattern names."""
    return list(PATTERN_BY_NAME.keys())


def validate_classification(
    pillar: str,
    category: str,
    pattern: str,
) -> tuple[str, str, str]:
    """Validate and normalise a (pillar, category, pattern) triple.

    Returns the corrected triple. Falls back to 'Technical Debt /
    Maintainability / General' if the input is completely invalid.
    """
    # Normalise pillar
    if pillar not in PILLAR_BY_NAME:
        pillar = "Technical Debt"

    # Normalise category — must belong to the pillar
    pillar_def = PILLAR_BY_NAME[pillar]
    if category not in [c.name for c in pillar_def.categories]:
        # Try to find the category in any pillar
        if category in CATEGORY_BY_NAME:
            correct_pillar, _ = CATEGORY_BY_NAME[category]
            pillar = correct_pillar.name
        else:
            category = pillar_def.categories[0].name

    # Normalise pattern — must belong to the category
    cat_def = next(c for c in PILLAR_BY_NAME[pillar].categories if c.name == category)
    if pattern not in cat_def.pattern_names:
        # Try to find the pattern in any category
        if pattern in PATTERN_BY_NAME:
            correct_pillar, correct_cat, _ = PATTERN_BY_NAME[pattern]
            pillar = correct_pillar.name
            category = correct_cat.name
        else:
            pattern = cat_def.patterns[0].name

    return pillar, category, pattern


def get_compact_taxonomy_for_prompt() -> str:
    """Return a compressed taxonomy string for embedding in LLM prompts.

    Only includes pillar → category → pattern names (no descriptions or
    keywords), to minimise token usage.
    """
    lines = []
    for pillar in ALL_PILLARS:
        lines.append(f"## {pillar.name}")
        for cat in pillar.categories:
            patterns = ", ".join(p.name for p in cat.patterns)
            lines.append(f"  {cat.name}: {patterns}")
    return "\n".join(lines)
