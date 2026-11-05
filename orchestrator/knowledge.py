"""Maps a ticket's free text to OWASP Top 10 categories and the specific
cheat sheet files under security/knowledge/cheatsheets that apply.

This mirrors the triage table in security/knowledge/owasp-top10-2021.md —
keep the two in sync if you add a category or retune trigger terms.
"""
from __future__ import annotations

from dataclasses import dataclass

KNOWLEDGE_ROOT = "security/knowledge"


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    trigger_terms: tuple[str, ...]
    cheatsheets: tuple[str, ...]


CATEGORIES: tuple[Category, ...] = (
    Category(
        "A01", "Broken Access Control",
        ("idor", "insecure direct object reference", "privilege escalation",
         "forced browsing", "missing authorization", "any user can access",
         "broken access control"),
        ("access-control.md",),
    ),
    Category(
        "A02", "Cryptographic Failures",
        ("cleartext", "weak cipher", "md5", "sha1", "hardcoded key",
         "no tls", "weak tls", "ecb mode", "sensitive data exposure"),
        ("cryptography.md", "secrets-management.md"),
    ),
    Category(
        "A03", "Injection",
        ("sql injection", "sqli", "command injection", "os command",
         "ldap injection", "xpath injection", "nosql injection",
         "template injection", "ssti", "string concatenation into query",
         "xss", "cross-site scripting", "cross site scripting"),
        ("injection.md", "xss.md"),
    ),
    Category(
        "A04", "Insecure Design",
        ("business logic flaw", "missing rate limit", "no anti-automation",
         "race condition", "workflow can be skipped", "insecure design"),
        ("access-control.md",),
    ),
    Category(
        "A05", "Security Misconfiguration",
        ("debug mode enabled", "default credentials", "directory listing",
         "missing security headers", "verbose stack trace",
         "security misconfiguration", "permissive cors", "cors"),
        ("api-security.md",),
    ),
    Category(
        "A06", "Vulnerable and Outdated Components",
        ("cve-", "outdated dependency", "dependabot", "snyk", "vulnerable component",
         "outdated component"),
        (),  # version bump, not a cheat sheet fix
    ),
    Category(
        "A07", "Identification and Authentication Failures",
        ("weak password policy", "session fixation", "credential stuffing",
         "no mfa", "predictable session token", "authentication failure",
         "forgot password", "password reset"),
        ("authentication.md", "session-management.md"),
    ),
    Category(
        "A08", "Software and Data Integrity Failures",
        ("insecure deserialization", "unsigned artifact", "pickle",
         "yaml.load", "untrusted plugin", "deserialization"),
        ("deserialization.md",),
    ),
    Category(
        "A09", "Security Logging and Monitoring Failures",
        ("no audit log", "logs don't capture", "pii in logs",
         "no alerting", "logging and monitoring"),
        (),  # no dedicated cheat sheet yet
    ),
    Category(
        "A10", "Server-Side Request Forgery",
        ("ssrf", "server-side request forgery", "server fetches user-supplied url",
         "webhook url", "callback url", "metadata endpoint"),
        ("ssrf.md",),
    ),
    Category(
        "CSRF", "Cross-Site Request Forgery",
        ("csrf", "cross-site request forgery", "cross site request forgery",
         "state-changing get request", "missing csrf token"),
        ("csrf.md",),
    ),
    Category(
        "FILEUPLOAD", "Unrestricted File Upload",
        ("unrestricted file upload", "arbitrary file write", "zip slip",
         "path traversal", "file upload"),
        ("file-upload.md",),
    ),
    Category(
        "INPUTVAL", "Input Validation",
        ("mass assignment", "missing input validation", "unvalidated request body"),
        ("input-validation.md",),
    ),
)

_BY_CODE = {c.code: c for c in CATEGORIES}


def classify(text: str, limit: int = 2) -> list[Category]:
    """Rank categories by how many trigger terms appear in `text`.

    Returns up to `limit` categories, highest hit-count first. Ties keep the
    CATEGORIES declaration order (A01 before A10, etc.) for determinism.
    """
    lowered = text.lower()
    scored = [
        (sum(1 for term in cat.trigger_terms if term in lowered), i, cat)
        for i, cat in enumerate(CATEGORIES)
    ]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [cat for _, _, cat in scored[:limit]]


def cheatsheet_paths(categories: list[Category]) -> list[str]:
    """Flatten matched categories' cheat sheets into repo-relative paths,
    de-duplicated, preserving first-seen order."""
    seen: dict[str, None] = {}
    for cat in categories:
        for sheet in cat.cheatsheets:
            seen.setdefault(f"{KNOWLEDGE_ROOT}/cheatsheets/{sheet}", None)
    return list(seen)


def category_by_code(code: str) -> Category | None:
    return _BY_CODE.get(code)
