from orchestrator.report import parse_fix_report, render_mr_description

SAMPLE_OUTPUT = """
Some agent chatter before the report.

===FIX_REPORT===
CONFIDENCE: 85
BLAST_RADIUS: MEDIUM
SUMMARY: Parameterized the login query in routes/login.ts:34 using named
replacements instead of raw string interpolation.
BLAST_RADIUS_DETAILS: Only called by the /rest/user/login handler.
Legitimate logins are unaffected; several SQLi-based challenge tests now
intentionally fail since they tested the vulnerability itself.
TESTS: Updated 5 tests in loginApiSpec.ts; did not run the suite (no
node_modules in this checkout).
===END_FIX_REPORT===

Trailing chatter after the report.
"""


def test_parse_fix_report_extracts_all_fields():
    report = parse_fix_report(SAMPLE_OUTPUT)
    assert report.found
    assert report.confidence == 85
    assert report.blast_radius == "MEDIUM"
    assert "Parameterized the login query" in report.summary
    assert "SQLi-based challenge tests" in report.blast_radius_details
    assert "did not run the suite" in report.tests


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


def test_render_mr_description_includes_meter_and_badge():
    report = parse_fix_report(SAMPLE_OUTPUT)
    description = render_mr_description(
        "VD-14", "https://vixai.atlassian.net/browse/VD-14", report, backend="claude"
    )
    assert "VD-14" in description
    assert "85%" in description
    assert "🟡 Medium" in description
    assert "claude" in description


def test_render_mr_description_falls_back_cleanly_when_not_found():
    report = parse_fix_report("nothing useful here")
    description = render_mr_description(
        "VD-99", "https://vixai.atlassian.net/browse/VD-99", report
    )
    assert "No structured fix report" in description
    assert "VD-99" in description
