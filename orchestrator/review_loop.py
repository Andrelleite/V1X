"""Deterministic pre-routing for CodeRabbit review comments.

This does NOT decide whether something really is a false positive — only
Claude, reading the actual code, can do that. It only flags which of the
named patterns in security/knowledge/false-positive-patterns.md the
comment's *wording* resembles, so the instruction we hand to Claude names
the right section to check and defaults safely to "fix" when nothing
matches or no evidence is available (same rule as CLAUDE.md Path A/B).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Decision, ReviewComment

_RESPONSE_START = "===REVIEW_RESPONSE==="
_RESPONSE_END = "===END_REVIEW_RESPONSE==="
_VALID_RESPONSE_PATHS = ("FIXED", "FALSE_POSITIVE_DEFENSE")
_FIELD_RE = re.compile(r"^([A-Z_]+):\s*(.*)$")

FP_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("already_mitigated_upstream", (
        "already validated", "already sanitized", "middleware already",
        "validated upstream", "handled upstream",
    )),
    ("not_attacker_reachable", (
        "not reachable", "hardcoded", "internal only", "not user-controlled",
        "not externally",
    )),
    ("context_mismatch", (
        "bearer token", "not cookie-based", "non-password checksum",
        "static markup", "wrong context",
    )),
    ("test_fixture_example", (
        "test fixture", "example code", "documentation example",
        ".env.example", "test-only",
    )),
    ("already_bounded_scope", (
        "admin-only", "feature-flagged", "internal network only",
        "restricted to",
    )),
    ("severity_mismatch", (
        "overstated severity", "low risk given", "severity seems high",
    )),
)


def candidate_patterns(comment_text: str) -> tuple[str, ...]:
    lowered = comment_text.lower()
    return tuple(
        name for name, terms in FP_PATTERNS
        if any(term in lowered for term in terms)
    )


def route(comment: ReviewComment, evidence: str | None = None) -> Decision:
    """`evidence`, when provided, is a short citation (file/line/control)
    that something upstream already produced — e.g. a prior Claude turn's
    own note. The CLI/CI wiring does not fabricate evidence; only Claude's
    own prior output should ever populate this.

    Pattern matching scans the comment's wording plus any cited evidence —
    the evidence text is usually where a pattern's language (e.g. "already
    validated upstream") actually shows up, not the reviewer's comment.
    """
    combined = comment.body if not evidence else f"{comment.body} {evidence}"
    patterns = candidate_patterns(combined)

    if not patterns:
        return Decision(path="fix", reason="no false-positive pattern matched")

    if evidence:
        return Decision(
            path="defend",
            reason=f"matched pattern(s) {patterns} with cited evidence: {evidence}",
            candidate_fp_patterns=patterns,
            requires_evidence=True,
        )

    return Decision(
        path="fix",
        reason=(
            f"pattern(s) {patterns} matched by wording, but no evidence was "
            "cited — defaulting to fix per false-positive-patterns.md"
        ),
        candidate_fp_patterns=patterns,
        requires_evidence=True,
    )


@dataclass(frozen=True)
class ReviewResponse:
    """What the agent decided to do about a review comment, parsed from
    its ===REVIEW_RESPONSE=== block (see prompt_builder.build_review_instruction).
    `message` is posted back verbatim as the reply on the review thread."""

    found: bool
    path: str | None = None  # "FIXED" | "FALSE_POSITIVE_DEFENSE"
    message: str = ""


def parse_review_response(text: str) -> ReviewResponse:
    s = text.find(_RESPONSE_START)
    e = text.find(_RESPONSE_END)
    if s == -1 or e == -1 or e < s:
        return ReviewResponse(found=False)
    block = text[s + len(_RESPONSE_START) : e]

    path: str | None = None
    message_words: list[str] = []
    current_key: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        match = _FIELD_RE.match(stripped)
        if match:
            current_key = match.group(1)
            if current_key == "PATH":
                path = match.group(2).strip().upper() or None
            elif current_key == "MESSAGE" and match.group(2):
                message_words.append(match.group(2))
            continue
        if current_key == "MESSAGE" and stripped:
            message_words.append(stripped)

    if path not in _VALID_RESPONSE_PATHS:
        path = None

    return ReviewResponse(found=path is not None, path=path, message=" ".join(message_words).strip())
