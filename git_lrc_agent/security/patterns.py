"""Regex patterns for pre-LLM secret and vulnerability detection.

These patterns are run against staged diff content BEFORE sending to the
LLM.  Matches are flagged immediately without needing an API call, making
them both faster and more reliable than LLM-only detection.

Pattern sources:
  - gitleaks (https://github.com/gitleaks/gitleaks)
  - truffleHog patterns
  - OWASP cheat sheets
  - Common CVE patterns
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SecretPattern:
    """A compiled regex pattern for detecting secrets or vulnerabilities."""
    name: str
    regex: re.Pattern
    severity: str = "critical"
    category: str = "Secrets Management"
    description: str = ""


# ---------------------------------------------------------------------------
# Secret / credential patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[SecretPattern] = [
    SecretPattern(
        name="AWS Access Key",
        regex=re.compile(r"(?:^|[^A-Za-z0-9])(?P<match>AKIA[0-9A-Z]{16})(?:[^A-Za-z0-9]|$)"),
        description="AWS access key ID (AKIA prefix).",
    ),
    SecretPattern(
        name="AWS Secret Key",
        regex=re.compile(r"""(?i)(?:aws|amazon).{0,30}(?:secret|key).{0,10}['\"](?P<match>[A-Za-z0-9/+=]{40})['\"]"""),
        description="AWS secret access key.",
    ),
    SecretPattern(
        name="GitHub Token",
        regex=re.compile(r"(?P<match>gh[ps]_[A-Za-z0-9_]{36,})"),
        description="GitHub personal access token or service token.",
    ),
    SecretPattern(
        name="GitHub Fine-Grained Token",
        regex=re.compile(r"(?P<match>github_pat_[A-Za-z0-9_]{22,})"),
        description="GitHub fine-grained personal access token.",
    ),
    SecretPattern(
        name="GitLab Token",
        regex=re.compile(r"(?P<match>glpat-[A-Za-z0-9\-_]{20,})"),
        description="GitLab personal/project access token.",
    ),
    SecretPattern(
        name="Slack Bot Token",
        regex=re.compile(r"(?P<match>xoxb-[0-9]{10,}-[0-9]{10,}-[A-Za-z0-9]{24,})"),
        description="Slack bot token.",
    ),
    SecretPattern(
        name="Slack Webhook URL",
        regex=re.compile(r"(?P<match>https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[A-Za-z0-9]{24,})"),
        description="Slack incoming webhook URL.",
    ),
    SecretPattern(
        name="Google API Key",
        regex=re.compile(r"(?P<match>AIza[0-9A-Za-z\-_]{35})"),
        description="Google API key.",
    ),
    SecretPattern(
        name="Google OAuth Token",
        regex=re.compile(r"(?P<match>ya29\.[0-9A-Za-z\-_]+)"),
        description="Google OAuth 2.0 access token.",
    ),
    SecretPattern(
        name="Stripe Secret Key",
        regex=re.compile(r"(?P<match>sk_live_[0-9a-zA-Z]{24,})"),
        description="Stripe live secret key.",
    ),
    SecretPattern(
        name="Stripe Publishable Key",
        regex=re.compile(r"(?P<match>pk_live_[0-9a-zA-Z]{24,})"),
        severity="high",
        description="Stripe live publishable key.",
    ),
    SecretPattern(
        name="Twilio API Key",
        regex=re.compile(r"(?P<match>SK[0-9a-fA-F]{32})"),
        description="Twilio API key.",
    ),
    SecretPattern(
        name="SendGrid API Key",
        regex=re.compile(r"(?P<match>SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43})"),
        description="SendGrid API key.",
    ),
    SecretPattern(
        name="Heroku API Key",
        regex=re.compile(r"""(?i)heroku.{0,20}(?:api[_-]?key|token).{0,10}['\"](?P<match>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})['\"]"""),
        description="Heroku API key (UUID format).",
    ),
    SecretPattern(
        name="Private Key (PEM)",
        regex=re.compile(r"(?P<match>-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----)"),
        description="Private key in PEM format.",
    ),
    SecretPattern(
        name="JWT Token",
        regex=re.compile(r"(?P<match>eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"),
        severity="high",
        description="JSON Web Token (may contain claims).",
    ),
    SecretPattern(
        name="Generic Password Assignment",
        regex=re.compile(r"""(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"](?P<match>[^'\"]{8,})['\"]"""),
        severity="high",
        category="Secrets Management",
        description="Hardcoded password assignment.",
    ),
    SecretPattern(
        name="Generic API Key Assignment",
        regex=re.compile(r"""(?i)(?:api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*['\"](?P<match>[A-Za-z0-9\-_]{16,})['\"]"""),
        severity="high",
        description="Hardcoded API key or secret.",
    ),
    SecretPattern(
        name="Connection String",
        regex=re.compile(r"""(?i)(?:connection[_-]?string|database[_-]?url|db[_-]?url)\s*[:=]\s*['\"](?P<match>[^'\"]{20,})['\"]"""),
        severity="high",
        category="Secrets Management",
        description="Hardcoded database connection string.",
    ),
    SecretPattern(
        name="Basic Auth in URL",
        regex=re.compile(r"(?P<match>https?://[A-Za-z0-9._%+-]+:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)"),
        severity="high",
        description="Credentials embedded in URL.",
    ),
]


# ---------------------------------------------------------------------------
# Vulnerability patterns
# ---------------------------------------------------------------------------

_VULN_PATTERNS: list[SecretPattern] = [
    SecretPattern(
        name="SQL String Concatenation",
        regex=re.compile(r"""(?i)(?:execute|query|cursor\.execute)\s*\(\s*(?:f['\"]|['\"].*?\s*\+|['\"].*?%\s*[(\[])"""),
        severity="high",
        category="Injection Vulnerabilities",
        description="Possible SQL injection via string concatenation/formatting.",
    ),
    SecretPattern(
        name="Dangerous eval()",
        regex=re.compile(r"""(?<!\w)eval\s*\("""),
        severity="high",
        category="Injection Vulnerabilities",
        description="Use of eval() — potential code injection.",
    ),
    SecretPattern(
        name="Dangerous exec()",
        regex=re.compile(r"""(?<!\w)exec\s*\("""),
        severity="high",
        category="Injection Vulnerabilities",
        description="Use of exec() — potential code injection.",
    ),
    SecretPattern(
        name="innerHTML Assignment",
        regex=re.compile(r"""\.innerHTML\s*=(?!=)"""),
        severity="medium",
        category="Input Validation",
        description="Direct innerHTML assignment — potential XSS.",
    ),
    SecretPattern(
        name="Shell Command Injection",
        regex=re.compile(r"""(?i)(?:os\.system|subprocess\.call|subprocess\.Popen|child_process\.exec)\s*\(.*(?:\+|f['\"]|format|%s)"""),
        severity="critical",
        category="Injection Vulnerabilities",
        description="Shell command constructed from user input.",
    ),
    SecretPattern(
        name="Disabled TLS Verification",
        regex=re.compile(r"""(?i)(?:verify\s*=\s*False|CERT_NONE|ssl[_.]verify\s*=\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]0)"""),
        severity="high",
        category="Cryptography",
        description="TLS/SSL certificate verification disabled.",
    ),
    SecretPattern(
        name="Weak Hash Function",
        regex=re.compile(r"""(?i)(?:md5|sha1)\s*\("""),
        severity="medium",
        category="Cryptography",
        description="Use of weak hash function (MD5/SHA1).",
    ),
    SecretPattern(
        name="Insecure Random",
        regex=re.compile(r"""(?:Math\.random|random\.random)\s*\("""),
        severity="medium",
        category="Cryptography",
        description="Use of non-cryptographic random for potentially sensitive operation.",
    ),
    SecretPattern(
        name="Hardcoded IP Address",
        regex=re.compile(r"""['\"](?P<match>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})['\"]"""),
        severity="low",
        category="Configuration Management",
        description="Hardcoded IP address — should use configuration.",
    ),
    SecretPattern(
        name="TODO/FIXME Security",
        regex=re.compile(r"""(?i)(?:TODO|FIXME|HACK)\s*:?\s*.*(?:security|auth|cred|secret|vuln|inject|xss|csrf)"""),
        severity="medium",
        category="Security Logging & Auditing",
        description="Security-related TODO/FIXME comment.",
    ),
]


# Combined list.
ALL_PATTERNS: list[SecretPattern] = _SECRET_PATTERNS + _VULN_PATTERNS


def get_secret_patterns() -> list[SecretPattern]:
    """Return all secret detection patterns."""
    return list(_SECRET_PATTERNS)


def get_vuln_patterns() -> list[SecretPattern]:
    """Return all vulnerability detection patterns."""
    return list(_VULN_PATTERNS)


def get_all_patterns() -> list[SecretPattern]:
    """Return all detection patterns (secrets + vulnerabilities)."""
    return list(ALL_PATTERNS)
