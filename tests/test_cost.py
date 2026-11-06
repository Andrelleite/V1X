import json

from orchestrator.cost import extract, extract_claude, extract_gemini


def test_claude_reports_direct_cost_when_present():
    stdout = json.dumps({"result": "the fix text", "total_cost_usd": 0.0231})
    run = extract_claude(stdout, using_subscription=False)
    assert run.text == "the fix text"
    assert run.cost_usd == 0.0231
    assert "directly" in run.cost_note


def test_claude_falls_back_to_cost_usd_field_name():
    stdout = json.dumps({"result": "fix text", "cost_usd": 0.004})
    run = extract_claude(stdout, using_subscription=False)
    assert run.cost_usd == 0.004


def test_claude_subscription_run_reports_zero_cost_regardless_of_field():
    stdout = json.dumps({"result": "fix text", "total_cost_usd": 0.01})
    run = extract_claude(stdout, using_subscription=True)
    assert run.cost_usd == 0.0
    assert "subscription" in run.cost_note


def test_claude_unparseable_output_falls_back_gracefully():
    run = extract_claude("not json at all, just agent chatter", using_subscription=False)
    assert run.cost_usd is None
    assert run.text == "not json at all, just agent chatter"
    assert "could not parse" in run.cost_note


def test_gemini_estimates_cost_from_token_stats():
    stdout = json.dumps({
        "response": "the fix text",
        "stats": {"models": {"gemini-3.8-flash": {"tokens": {"prompt": 10_000, "candidates": 2_000}}}},
    })
    run = extract_gemini(stdout)
    assert run.text == "the fix text"
    assert run.cost_usd is not None
    # 10_000/1e6 * 0.75 + 2_000/1e6 * 3.75 = 0.0075 + 0.0075 = 0.015
    assert round(run.cost_usd, 4) == 0.015
    assert "10,000" in run.cost_note


def test_gemini_no_token_stats_reports_unavailable():
    stdout = json.dumps({"response": "fix text", "stats": {"models": {}}})
    run = extract_gemini(stdout)
    assert run.cost_usd is None
    assert "no token usage" in run.cost_note


def test_find_json_object_prefers_last_json_blob_over_earlier_noise():
    # Mirrors a real Gemini retry: an earlier error message happens to
    # contain a JSON body, and the real result comes after it.
    stdout = (
        'Attempt 1 failed: {"error": {"code": 503, "message": "unavailable"}}\n'
        'Retrying...\n'
        + json.dumps({"response": "final text", "stats": {"models": {}}})
    )
    run = extract_gemini(stdout)
    assert run.text == "final text"


def test_extract_dispatches_on_backend_name():
    stdout = json.dumps({"result": "x", "total_cost_usd": 0.001})
    assert extract("claude", stdout, using_subscription=False).cost_usd == 0.001
    assert extract("unknown-backend", stdout).cost_usd is None
