"""Parses the structured ===FIX_REPORT=== block the Fixer is instructed to
emit (see prompt_builder.build_fix_instruction), and renders it into a
rich MR/PR description: a deterministic "finding details" header (ticket,
severity, OWASP category — pulled from real data, not agent prose), a
text-based confidence meter and blast-radius badge, a Mermaid architecture
diagram, and the agent's own narrative. Plain markdown throughout, since
that's what GitLab/GitHub descriptions actually render — Mermaid code
blocks render natively on both, which is why that's the diagram format
used here rather than a generated image.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

REPORT_START = "===FIX_REPORT==="
REPORT_END = "===END_FIX_REPORT==="
DIAGRAM_START = "===ARCHITECTURE_DIAGRAM==="
DIAGRAM_END = "===END_ARCHITECTURE_DIAGRAM==="

_FIELD_RE = re.compile(r"^([A-Z_]+):\s*(.*)$")
_VALID_BLAST_RADIUS = ("LOW", "MEDIUM", "HIGH")

_BLAST_BADGE = {"LOW": "🟢 Low", "MEDIUM": "🟡 Medium", "HIGH": "🔴 High"}
_SEVERITY_BADGE = {
    "HIGHEST": "🔴 Highest",
    "HIGH": "🟠 High",
    "MEDIUM": "🟡 Medium",
    "LOW": "🟢 Low",
    "LOWEST": "🟢 Lowest",
}


@dataclass(frozen=True)
class FixReport:
    found: bool
    confidence: int | None = None
    blast_radius: str | None = None  # "LOW" | "MEDIUM" | "HIGH"
    affected_files: str = ""
    summary: str = ""
    blast_radius_details: str = ""
    tests: str = ""
    architecture_diagram: str = ""  # raw Mermaid source, no code fence


def _extract_delimited(text: str, start: str, end: str) -> tuple[str | None, str]:
    """Returns (block_content_or_None, text_with_block_removed)."""
    s = text.find(start)
    e = text.find(end)
    if s == -1 or e == -1 or e < s:
        return None, text
    content = text[s + len(start) : e].strip("\n")
    remainder = text[:s] + text[e + len(end) :]
    return content, remainder


def parse_fix_report(text: str) -> FixReport:
    """Extract the block between the ===FIX_REPORT=== delimiters. The
    nested architecture-diagram block is pulled out first (its raw
    newlines matter, unlike the other fields) and parsed separately;
    everything else is tolerant of the agent adding stray formatting
    around it — field lines are matched by a leading ALL_CAPS_KEY: prefix,
    with further lines before the next field folded into the same value.
    """
    outer, _ = _extract_delimited(text, REPORT_START, REPORT_END)
    if outer is None:
        return FixReport(found=False)

    diagram, outer_without_diagram = _extract_delimited(
        outer, DIAGRAM_START, DIAGRAM_END
    )

    fields: dict[str, list[str]] = {}
    current_key: str | None = None
    for line in outer_without_diagram.splitlines():
        stripped = line.strip()
        match = _FIELD_RE.match(stripped)
        if match:
            current_key = match.group(1)
            fields[current_key] = [match.group(2)]
        elif current_key and stripped:
            fields[current_key].append(stripped)

    def get(key: str) -> str:
        return " ".join(fields.get(key, [])).strip()

    confidence_raw = re.sub(r"[^\d]", "", get("CONFIDENCE"))
    confidence = int(confidence_raw) if confidence_raw else None
    if confidence is not None:
        confidence = max(0, min(100, confidence))

    blast_radius = get("BLAST_RADIUS").upper().strip() or None
    if blast_radius not in _VALID_BLAST_RADIUS:
        blast_radius = None

    return FixReport(
        found=True,
        confidence=confidence,
        blast_radius=blast_radius,
        affected_files=get("AFFECTED_FILES"),
        summary=get("SUMMARY"),
        blast_radius_details=get("BLAST_RADIUS_DETAILS"),
        tests=get("TESTS"),
        architecture_diagram=(diagram or "").strip(),
    )


def _confidence_meter(confidence: int | None) -> str:
    if confidence is None:
        return "⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️⬜️ **unknown**"
    filled = max(0, min(10, round(confidence / 10)))
    return f"{'🟩' * filled}{'⬜️' * (10 - filled)} **{confidence}%**"


def _severity_badge(priority: str) -> str:
    return _SEVERITY_BADGE.get(priority.strip().upper(), f"⚪ {priority}")


def _fallback_diagram(issue_key: str, affected_files: str) -> str:
    """Used when the agent's own diagram is missing/empty, so the MR
    always has *a* diagram, even if it's just the flat list of files it
    reported rather than real call relationships."""
    files = [f.strip() for f in affected_files.split(",") if f.strip()]
    if not files:
        files = ["(no files reported)"]
    lines = ["flowchart TD", f'  T["Jira {issue_key}"]']
    for i, f in enumerate(files):
        safe = f.replace('"', "'")
        lines.append(f'  T --> F{i}["{safe}"]')
    return "\n".join(lines)


def _cost_line(cost_usd: float | None, cost_note: str) -> str:
    if cost_usd is None:
        return f"_unavailable_ ({cost_note})" if cost_note else "_unavailable_"
    if cost_usd == 0:
        return f"$0.00 — {cost_note}"
    return f"~${cost_usd:.4f} _({cost_note})_"


def render_mr_description(
    ticket,
    owasp_category: str,
    report: FixReport,
    backend: str = "",
    issue_url: str = "",
    cost_usd: float | None = None,
    cost_note: str = "",
) -> str:
    """`ticket` is a VulnTicket (key/repo/priority come from it — real
    Jira/pipeline data, not agent prose). `owasp_category` is the
    deterministic classify() result the pipeline already computed, passed
    through so it doesn't depend on the agent restating it correctly.
    `cost_usd`/`cost_note` come from cost.py — a real figure for Claude
    when its JSON output reports one, an estimate from token counts for
    Gemini (which doesn't report a dollar figure at all), or $0 for a
    Claude Pro/Max subscription run (no marginal per-request cost).
    """
    backend_note = f" (backend: `{backend}`)" if backend else ""
    url = issue_url or ""
    ticket_link = f"[{ticket.key}]({url})" if url else ticket.key

    if not report.found:
        return (
            f"## 🛡️ AI Security Fix Report — {ticket_link}\n\n"
            "| Field | Value |\n|---|---|\n"
            f"| **Jira Ticket** | {ticket_link} |\n"
            f"| **Severity** | {_severity_badge(ticket.priority)} |\n"
            f"| **OWASP Category** | {owasp_category} |\n"
            f"| **Target Repo** | `{ticket.repo or 'unknown'}` |\n"
            f"| **Estimated Cost** | {_cost_line(cost_usd, cost_note)} |\n\n"
            "⚠️ **No structured fix report was found** — the agent's "
            "output didn't contain a parseable `===FIX_REPORT===` block"
            f"{backend_note}. Treat this MR's confidence as **unverified** "
            "and check the pipeline job log for the agent's full output "
            "before relying on it.\n"
        )

    blast_badge = _BLAST_BADGE.get(report.blast_radius or "", "⚪ Unknown")
    diagram = report.architecture_diagram or _fallback_diagram(
        ticket.key, report.affected_files
    )

    return f"""## 🛡️ AI Security Fix Report — {ticket_link}{backend_note}

| Field | Value |
|---|---|
| **Jira Ticket** | {ticket_link} |
| **Severity** | {_severity_badge(ticket.priority)} |
| **OWASP Category** | {owasp_category} |
| **Target Repo** | `{ticket.repo or 'unknown'}` |
| **Affected Files** | {report.affected_files or "_not reported_"} |
| **Estimated Cost** | {_cost_line(cost_usd, cost_note)} |

**Confidence:** {_confidence_meter(report.confidence)}
**Blast Radius:** {blast_badge}

---

### Impacted Architecture
```mermaid
{diagram}
```

### What this fixes
{report.summary or "_not provided by the agent_"}

### Blast radius assessment
{report.blast_radius_details or "_not provided by the agent_"}

### Test coverage
{report.tests or "_not provided by the agent_"}

---
*Generated by the AI AppSec pipeline for Jira ticket {ticket_link}. See `CLAUDE.md` (from the V1X project) for the process that produced this fix. Confidence, blast radius, and the diagram above are the agent's own self-assessment — not an independently verified guarantee.*
"""
