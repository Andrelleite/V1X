from orchestrator.models import VulnTicket
from orchestrator.report import parse_fix_report, render_mr_description

TICKET = VulnTicket(
    key="VD-14",
    summary="SQL Injection in login",
    description="...",
    repo="mumbo-jumbo/juice-shop-revamped",
    priority="Highest",
)

SAMPLE_OUTPUT = """
Some agent chatter before the report.

===FIX_REPORT===
CONFIDENCE: 85
BLAST_RADIUS: MEDIUM
EXPLOITABILITY: HIGH
AFFECTED_FILES: routes/login.ts, test/api/loginApiSpec.ts
CODE_LANGUAGE: typescript
SUMMARY: Parameterized the login query in routes/login.ts:34 using named
replacements instead of raw string interpolation.
BLAST_RADIUS_DETAILS: Only called by the /rest/user/login handler.
Legitimate logins are unaffected; several SQLi-based challenge tests now
intentionally fail since they tested the vulnerability itself.
EXPLOITABILITY_DETAILS: Reachable pre-auth at POST /rest/user/login with
no rate limiting or WAF in front of it — any anonymous attacker can send
the payload directly.
TESTS: Updated 5 tests in loginApiSpec.ts; did not run the suite (no
node_modules in this checkout).
===VULNERABLE_CODE===
models.sequelize.query(`SELECT * FROM Users WHERE email = '${email}'`)
===END_VULNERABLE_CODE===
===FIXED_CODE===
models.sequelize.query('SELECT * FROM Users WHERE email = :email', { replacements: { email } })
===END_FIXED_CODE===
===ARCHITECTURE_DIAGRAM===
flowchart TD
  A["routes/login.ts"] -->|parameterized query| B[(Users table)]
  C["test/api/loginApiSpec.ts"] -.verifies.-> A
===END_ARCHITECTURE_DIAGRAM===
===END_FIX_REPORT===

Trailing chatter after the report.
"""


def test_parse_fix_report_extracts_all_fields():
    report = parse_fix_report(SAMPLE_OUTPUT)
    assert report.found
    assert report.confidence == 85
    assert report.blast_radius == "MEDIUM"
    assert report.exploitability == "HIGH"
    assert report.affected_files == "routes/login.ts, test/api/loginApiSpec.ts"
    assert "Parameterized the login query" in report.summary
    assert "SQLi-based challenge tests" in report.blast_radius_details
    assert "no rate limiting or WAF" in report.exploitability_details
    assert "did not run the suite" in report.tests
    assert "flowchart TD" in report.architecture_diagram
    assert "Users table" in report.architecture_diagram
    assert report.code_language == "typescript"
    assert "WHERE email = '${email}'" in report.vulnerable_code
    assert "replacements: { email }" in report.fixed_code


def test_parse_fix_report_missing_block_returns_not_found():
    report = parse_fix_report("No report here, just an error message.")
    assert not report.found
    assert report.confidence is None
    assert report.blast_radius is None


def test_parse_fix_report_clamps_confidence_to_0_100():
    text = "===FIX_REPORT===\nCONFIDENCE: 150\nBLAST_RADIUS: LOW\n===END_FIX_REPORT==="
    report = parse_fix_report(text)
    assert report.confidence == 100


def test_parse_fix_report_rejects_invalid_blast_radius():
    text = "===FIX_REPORT===\nCONFIDENCE: 50\nBLAST_RADIUS: WHO_KNOWS\n===END_FIX_REPORT==="
    report = parse_fix_report(text)
    assert report.blast_radius is None


def test_parse_fix_report_rejects_invalid_exploitability():
    text = "===FIX_REPORT===\nCONFIDENCE: 50\nEXPLOITABILITY: WHO_KNOWS\n===END_FIX_REPORT==="
    report = parse_fix_report(text)
    assert report.exploitability is None


def test_render_mr_description_includes_meter_badge_and_diagram():
    report = parse_fix_report(SAMPLE_OUTPUT)
    description = render_mr_description(
        TICKET,
        "A03 (Injection)",
        report,
        backend="claude",
        issue_url="https://vixai.atlassian.net/browse/VD-14",
        cost_usd=0.0231,
        cost_note="reported directly by Claude Code",
    )
    assert "VD-14" in description
    assert "85%" in description
    assert "🟡 Medium" in description
    assert "**Exploitability:** 🔴 High" in description
    assert "### Exploitability assessment" in description
    assert "no rate limiting or WAF" in description
    assert "claude" in description
    assert "🔴 Highest" in description  # ticket.priority severity badge
    assert "A03 (Injection)" in description
    assert "```mermaid" in description
    assert "flowchart TD" in description
    assert "$0.0231" in description
    assert "**Estimated Cost**" in description
    assert "### Before → After" in description
    assert "```typescript" in description
    assert "WHERE email = '${email}'" in description
    assert "replacements: { email }" in description


def test_render_mr_description_omits_code_section_when_agent_provides_none():
    text = (
        "===FIX_REPORT===\nCONFIDENCE: 60\nBLAST_RADIUS: LOW\n"
        "AFFECTED_FILES: routes/search.ts\nSUMMARY: fixed it\n"
        "BLAST_RADIUS_DETAILS: low risk\nTESTS: added one\n"
        "===END_FIX_REPORT==="
    )
    report = parse_fix_report(text)
    description = render_mr_description(TICKET, "A03 (Injection)", report)
    assert "Before → After" not in description


def test_parse_fix_report_preserves_paragraph_breaks_in_summary():
    text = (
        "===FIX_REPORT===\nCONFIDENCE: 60\nBLAST_RADIUS: LOW\n"
        "SUMMARY: First paragraph, one sentence.\n"
        "Still first paragraph, continued.\n"
        "\n"
        "Second paragraph entirely.\n"
        "BLAST_RADIUS_DETAILS: low risk\nTESTS: added one\n"
        "===END_FIX_REPORT==="
    )
    report = parse_fix_report(text)
    assert report.summary == (
        "First paragraph, one sentence. Still first paragraph, continued.\n\n"
        "Second paragraph entirely."
    )


def test_render_mr_description_escapes_html_like_text_in_prose():
    text = (
        "===FIX_REPORT===\nCONFIDENCE: 60\nBLAST_RADIUS: LOW\n"
        "SUMMARY: An attacker could send <script>alert(1)</script> as input.\n"
        "BLAST_RADIUS_DETAILS: low risk\nTESTS: added one\n"
        "===END_FIX_REPORT==="
    )
    report = parse_fix_report(text)
    description = render_mr_description(TICKET, "A03 (Injection)", report)
    assert "<script>" not in description
    assert "&lt;script&gt;" in description


def test_code_language_is_sanitized_to_safe_token():
    text = (
        '===FIX_REPORT===\nCONFIDENCE: 60\nBLAST_RADIUS: LOW\n'
        'CODE_LANGUAGE: typescript```\nSUMMARY: fixed it\n'
        'BLAST_RADIUS_DETAILS: low risk\nTESTS: added one\n'
        '===VULNERABLE_CODE===\nold code\n===END_VULNERABLE_CODE===\n'
        '===FIXED_CODE===\nnew code\n===END_FIXED_CODE===\n'
        '===END_FIX_REPORT==='
    )
    report = parse_fix_report(text)
    assert report.code_language == "typescript"


def test_render_mr_description_cost_unavailable_is_labeled_clearly():
    report = parse_fix_report(SAMPLE_OUTPUT)
    description = render_mr_description(
        TICKET, "A03 (Injection)", report, cost_usd=None, cost_note="could not parse output"
    )
    assert "_unavailable_" in description
    assert "could not parse output" in description


def test_render_mr_description_falls_back_cleanly_when_not_found():
    report = parse_fix_report("nothing useful here")
    ticket = VulnTicket(key="VD-99", summary="x", description="y", priority="Medium")
    description = render_mr_description(
        ticket, "unclassified", report, issue_url="https://vixai.atlassian.net/browse/VD-99"
    )
    assert "No structured fix report" in description
    assert "VD-99" in description


def test_render_mr_description_uses_fallback_diagram_when_agent_omits_one():
    text = (
        "===FIX_REPORT===\nCONFIDENCE: 60\nBLAST_RADIUS: LOW\n"
        "AFFECTED_FILES: routes/search.ts\nSUMMARY: fixed it\n"
        "BLAST_RADIUS_DETAILS: low risk\nTESTS: added one\n"
        "===END_FIX_REPORT==="
    )
    report = parse_fix_report(text)
    description = render_mr_description(TICKET, "A03 (Injection)", report)
    assert "```mermaid" in description
    assert "routes/search.ts" in description
