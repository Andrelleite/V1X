from orchestrator.runners import GEMINI, CLAUDE, Runner, select_runner
import orchestrator.runners as runners_mod


def _fake_available(answer: bool):
    return lambda self: answer


def test_gemini_tried_before_claude_when_both_available(monkeypatch):
    monkeypatch.setattr(Runner, "available", _fake_available(True))
    runner, skipped = select_runner()
    assert runner is GEMINI
    assert skipped == []


def test_falls_back_to_claude_when_gemini_unavailable(monkeypatch):
    def available(self):
        return self is CLAUDE

    monkeypatch.setattr(Runner, "available", available)
    runner, skipped = select_runner()
    assert runner is CLAUDE
    assert any("gemini" in s for s in skipped)


def test_no_runner_available_reports_both_skipped(monkeypatch):
    monkeypatch.setattr(Runner, "available", _fake_available(False))
    runner, skipped = select_runner()
    assert runner is None
    assert len(skipped) == 2


def test_gemini_command_uses_prompt_flag_and_model():
    cmd = GEMINI.build_args("do the thing")
    assert cmd[0] == "gemini"
    assert "-p" in cmd
    assert "do the thing" in cmd


def test_claude_command_uses_print_flag():
    cmd = CLAUDE.build_args("do the thing")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "do the thing" in cmd


def test_claude_configured_via_api_key_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setattr(runners_mod, "CLAUDE_CREDENTIALS_FILE", tmp_path / "nope.json")
    assert CLAUDE.is_configured()


def test_claude_configured_via_restored_subscription_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake_creds = tmp_path / ".credentials.json"
    fake_creds.write_text('{"claudeAiOauth": {}}')
    monkeypatch.setattr(runners_mod, "CLAUDE_CREDENTIALS_FILE", fake_creds)
    assert runners_mod._claude_configured()


def test_claude_not_configured_when_neither_present(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        runners_mod, "CLAUDE_CREDENTIALS_FILE", tmp_path / "nope.json"
    )
    assert not runners_mod._claude_configured()
