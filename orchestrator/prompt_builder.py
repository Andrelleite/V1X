"""Builds the single instruction string handed to whichever headless coding
agent runs it (Gemini CLI first, Claude Code as fallback — see runners.py).

Claude Code auto-loads CLAUDE.md from the repo root on its own; Gemini CLI
has the equivalent convention for a file named GEMINI.md, which here is
just a pointer back to CLAUDE.md (see ../GEMINI.md). Rather than depend on
either CLI's auto-load behavior, every instruction explicitly tells the
agent to read CLAUDE.md itself first — that way the pipeline's actual
behavior doesn't depend on which backend happened to run it. These
instructions still only point at the specific ticket/comment and the
specific cheat sheets to read, not the whole knowledge base (see
security/knowledge/README.md's token-discipline rule).
"""
from __future__ import annotations

from .knowledge import cheatsheet_paths, classify
from .models import Decision, ReviewComment, VulnTicket


def category_line(ticket_text: str) -> str:
    """The deterministic OWASP classification line, shared between the
    agent instruction and report.py's MR-description header (so the
    header doesn't depend on the agent restating the category correctly).
    """
    categories = classify(ticket_text)
    return ", ".join(f"{c.code} ({c.name})" for c in categories) or (
        "unclassified"
    )


def primary_category_keyword(ticket_text: str) -> str:
    """A plain-English search term for the ticket's top-matched category
    (e.g. "Injection", "Server-Side Request Forgery") — used by
    context.py as the search keyword against Jira/Confluence/GitLab.
    Falls back to the ticket's first few words when unclassified."""
    categories = classify(ticket_text)
    if categories:
        return categories[0].name
    return " ".join(ticket_text.split()[:4])


def build_fix_instruction(ticket: VulnTicket, related_context: str = "") -> str:
    categories = classify(ticket.text)
    sheets = cheatsheet_paths(categories)

    cat_line = category_line(ticket.text) if categories else (
        "unclassified — read security/knowledge/owasp-top10-2021.md and "
        "classify it yourself before patching"
    )
    sheets_block = "\n".join(f"- {s}" for s in sheets) or (
        "(no specific cheat sheet auto-matched — classify first, then open "
        "the matching file under security/knowledge/cheatsheets/)"
    )
    context_block = related_context or (
        "(not gathered for this run — proceeding from the ticket alone)"
    )

    return (
        "Before anything else, read CLAUDE.md in the repo root in full — it "
        "has the complete process you must follow for this task.\n\n"
        f"Jira ticket {ticket.key}: {ticket.summary}\n\n"
        f"Description:\n{ticket.description}\n\n"
        f"Likely OWASP category: {cat_line}\n"
        f"Relevant cheat sheet(s) to read before patching:\n{sheets_block}\n\n"
        "Related context found in other company systems (Jira, Confluence, "
        "this repo's own commit history) — this is a best-effort search, "
        "not guaranteed complete; weigh it accordingly, and also search the "
        "target repo's own git log/blame yourself if it would help (that's "
        "a normal git command, not a disallowed tool):\n"
        f"{context_block}\n\n"
        "Follow the Phase 2(a) decision tree in CLAUDE.md: analyze the root "
        "cause, write a surgical patch (small blast radius — do not touch "
        "unrelated code), update/add a test if a suite already covers this "
        "module. You are already on the correct branch. Stage and commit "
        "your changes yourself (git add + git commit) — the pipeline "
        "handles pushing and opening the MR after you finish; do not "
        "attempt to push or open a PR/MR yourself.\n\n"
        "Do NOT attempt to run the test suite, start a server, or run "
        "any command other than git add/git commit — this checkout has no "
        "dependencies installed (no node_modules/pip install/etc.) and no "
        "network access to run anything against, and you have no "
        "permission to run other commands in this environment, so trying "
        "will only block on an approval that can never come. If a test "
        "suite already covers this code, update the test file(s) by "
        "editing them directly, but report in TESTS below that you could "
        "not execute them — do not ask whether to run anything.\n\n"
        "End your response with EXACTLY this block, filled in (this is "
        "parsed by a script into the MR description — keep every field to "
        "plain text with no markdown inside the block except SUMMARY, "
        "which may run several sentences since it's the main explanation; "
        "emit the literal delimiter lines exactly as shown):\n\n"
        "===FIX_REPORT===\n"
        "CONFIDENCE: <integer 0-100 — your honest confidence this fix is "
        "correct and complete>\n"
        "BLAST_RADIUS: <LOW, MEDIUM, or HIGH — risk this change breaks "
        "something else>\n"
        "AFFECTED_FILES: <comma-separated list of every file you changed "
        "or that directly calls the changed code>\n"
        "CODE_LANGUAGE: <the fenced-code-block language for the snippets "
        "below, e.g. typescript, python, go — whatever the file actually is>\n"
        "SUMMARY: <explain this like you're walking a developer who knows "
        "the codebase but isn't a security specialist through it: (1) what "
        "could an attacker actually DO here, in plain terms, not just the "
        "vulnerability class name; (2) why does the original code allow "
        "that — the specific mechanism, not just 'it was vulnerable'; (3) "
        "what exactly you changed and why that specific change closes it. "
        "Technical and precise, but explain the reasoning — don't just "
        "assert conclusions.>\n"
        "BLAST_RADIUS_DETAILS: <what else calls the changed code, whether "
        "legitimate behavior is preserved, and anything you could not "
        "verify (e.g. couldn't run the test suite)>\n"
        "TESTS: <whether a test suite already covered this code, what you "
        "added or updated, and whether you actually ran it>\n"
        "===VULNERABLE_CODE===\n"
        "<the exact original vulnerable snippet (just the relevant lines, "
        "not the whole file), with its real indentation preserved. Raw "
        "code only, no ``` fences, no commentary on these lines.>\n"
        "===END_VULNERABLE_CODE===\n"
        "===FIXED_CODE===\n"
        "<the same snippet after your fix, same scope as above. Raw code "
        "only, no ``` fences, no commentary on these lines.>\n"
        "===END_FIXED_CODE===\n"
        "===ARCHITECTURE_DIAGRAM===\n"
        "<a Mermaid flowchart (flowchart TD) showing the vulnerable "
        "component, what calls it, and what it calls/touches (e.g. a "
        "database table, another module) — base this on what you actually "
        "read in the codebase, not a generic template. Raw Mermaid syntax "
        "only, no ``` code fences, no extra prose on these lines.>\n"
        "===END_ARCHITECTURE_DIAGRAM===\n"
        "===END_FIX_REPORT==="
    )


def build_review_instruction(comment: ReviewComment, decision: Decision) -> str:
    location = comment.file_path or "the MR"
    if comment.line:
        location += f":{comment.line}"

    if decision.path == "defend":
        patterns = ", ".join(decision.candidate_fp_patterns) or "none named"
        guidance = (
            f"This comment matches possible false-positive pattern(s) ({patterns}) "
            "from security/knowledge/false-positive-patterns.md. Only reply with "
            "'FALSE POSITIVE DEFENSE:' if you can cite concrete evidence in THIS "
            "repository (an actual file/line/control). If you cannot find that "
            "evidence, fix the issue instead (Path A) rather than asserting a "
            "false positive without proof."
        )
    else:
        guidance = (
            "No false-positive pattern was detected automatically for this "
            "comment — default to fixing it (Path A) unless you find clear, "
            "citable evidence in this repo that it's a false positive."
        )

    return (
        "Before anything else, read CLAUDE.md in the repo root in full — it "
        "has the complete process you must follow for this task.\n\n"
        f"CodeRabbit review comment on {location}:\n\n\"{comment.body}\"\n\n"
        f"{guidance}\n\n"
        "Follow the Phase 2(b) decision tree in CLAUDE.md: Path A, fix and "
        "reply starting 'FIXED:'; Path B, defend and reply starting "
        "'FALSE POSITIVE DEFENSE:', citing evidence."
    )
