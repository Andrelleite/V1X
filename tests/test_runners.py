from orchestrator.runners import GEMINI, CLAUDE, Runner, select_runner


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
