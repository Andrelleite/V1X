from orchestrator.knowledge import cheatsheet_paths, classify


def test_classifies_sql_injection_as_injection():
    text = (
        "SQL Injection in /auth login endpoint. The handler concatenates "
        "the username into the query string."
    )
    cats = classify(text)
    assert cats
    assert cats[0].code == "A03"


def test_classifies_ssrf():
    text = (
        "SSRF via webhook URL field. The server fetches a user-supplied "
        "callback URL, reaching 169.254.169.254."
    )
    cats = classify(text)
    assert cats[0].code == "A10"


def test_cheatsheet_paths_for_injection():
    cats = classify("SQL injection via string concatenation into query")
    paths = cheatsheet_paths(cats)
    assert "security/knowledge/cheatsheets/injection.md" in paths


def test_unmatched_text_returns_empty():
    assert classify("the sky is blue today") == []


def test_limit_caps_results():
    text = (
        "SQL injection, XSS, and also an SSRF issue, plus weak password "
        "policy and session fixation all in one ticket"
    )
    cats = classify(text, limit=2)
    assert len(cats) <= 2
