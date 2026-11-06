from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VulnTicket:
    """A normalized view of a Jira security-bug ticket."""

    key: str
    summary: str
    description: str
    labels: tuple[str, ...] = ()
    repo: str | None = None
    priority: str = "Unknown"

    @property
    def text(self) -> str:
        return f"{self.summary}\n{self.description}"

    @classmethod
    def from_jira_payload(cls, payload: dict) -> "VulnTicket":
        """Build from the Jira Automation 'send web request' client_payload shape.

        Expected shape (see docs/jira-automation-rule.md):
            {"issue_key": "SEC-1", "summary": "...", "description": "...",
             "labels": ["sec-ai-fix"], "repo": "owner/name", "priority": "Highest"}
        `priority` is fetched from Jira's own Priority field by the CI
        workflow (not user-editable free text), so the MR report's
        "Severity" line is deterministic, not something the agent guesses.
        """
        return cls(
            key=payload["issue_key"],
            summary=payload.get("summary", ""),
            description=payload.get("description", ""),
            labels=tuple(payload.get("labels", ())),
            repo=payload.get("repo"),
            priority=payload.get("priority") or "Unknown",
        )


@dataclass(frozen=True)
class ReviewComment:
    """A single CodeRabbit (or equivalent) review comment on an open MR."""

    body: str
    file_path: str | None = None
    line: int | None = None
    author: str = "coderabbitai"


@dataclass(frozen=True)
class Decision:
    """The routing decision for a review comment, before Claude acts on it."""

    path: str  # "fix" or "defend"
    reason: str
    candidate_fp_patterns: tuple[str, ...] = field(default_factory=tuple)
    requires_evidence: bool = False
