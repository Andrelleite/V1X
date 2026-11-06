"""Extracts the agent's actual response text and a USD cost figure from a
--output-format json run (see runners.py). Claude Code and Gemini CLI have
different, individually unstable JSON schemas (checked empirically against
real CI runs, not just docs — field names have already drifted once), so
every lookup here degrades to "cost unavailable" with a clear reason
rather than ever reporting a confidently wrong number. This module never
raises on malformed input — a parsing bug here must never take down the
actual fix delivery, which is the real deliverable.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Gemini CLI's JSON output doesn't include a dollar figure, only token
# counts — these per-1M-token USD rates are used to estimate one. They
# drift (gemini-3.8-flash's own rates are scheduled to double on
# 2027-01-01) and may not match the model GEMINI_MODEL actually points at
# by the time you're reading this — override via env if so, and treat the
# result as an estimate, not an invoice. Verify at
# ai.google.dev/gemini-api/docs/pricing.
GEMINI_PRICE_INPUT_PER_M = float(os.environ.get("GEMINI_PRICE_INPUT_PER_M", "0.75"))
GEMINI_PRICE_OUTPUT_PER_M = float(os.environ.get("GEMINI_PRICE_OUTPUT_PER_M", "3.75"))


@dataclass(frozen=True)
class RunCost:
    backend: str
    text: str  # the agent's actual response text — feed this to parse_fix_report
    cost_usd: float | None  # None only when genuinely unavailable
    cost_note: str  # always set — explains the figure or its absence


def _find_json_object(raw: str) -> dict | None:
    """Try the whole string first; otherwise scan every '{' from the END
    backward and parse from there, so a final real result is preferred
    over earlier incidental JSON-shaped text (observed in real runs: a
    mid-stream retry error can itself contain a nested JSON body before
    the eventual successful result)."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass

    positions = [i for i, ch in enumerate(raw) if ch == "{"]
    for start in reversed(positions):
        try:
            parsed = json.loads(raw[start:])
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_claude(stdout: str, using_subscription: bool) -> RunCost:
    data = _find_json_object(stdout)
    if data is None:
        return RunCost(
            "claude", stdout, None,
            "could not parse --output-format json output (fell back to raw stdout)",
        )

    text = data.get("result") or data.get("response") or stdout

    if using_subscription:
        return RunCost(
            "claude", text, 0.0,
            "Claude Pro/Max subscription — no marginal per-request cost",
        )

    cost = data.get("total_cost_usd", data.get("cost_usd"))
    if isinstance(cost, (int, float)):
        return RunCost("claude", text, float(cost), "reported directly by Claude Code")

    return RunCost(
        "claude", text, None,
        "no cost_usd/total_cost_usd field in this Claude Code version's JSON output",
    )


def extract_gemini(stdout: str) -> RunCost:
    data = _find_json_object(stdout)
    if data is None:
        return RunCost(
            "gemini", stdout, None,
            "could not parse --output-format json output (fell back to raw stdout)",
        )

    text = data.get("response") or data.get("result") or stdout

    total_in = total_out = 0
    for model_stats in (data.get("stats") or {}).get("models", {}).values():
        tokens = model_stats.get("tokens") or {}
        total_in += tokens.get("prompt", 0) or 0
        total_out += tokens.get("candidates", tokens.get("output", 0)) or 0

    if not (total_in or total_out):
        return RunCost(
            "gemini", text, None,
            "no token usage stats in this Gemini CLI version's JSON output",
        )

    cost = (total_in / 1_000_000) * GEMINI_PRICE_INPUT_PER_M + (
        total_out / 1_000_000
    ) * GEMINI_PRICE_OUTPUT_PER_M
    return RunCost(
        "gemini", text, cost,
        f"estimated from {total_in:,} input + {total_out:,} output tokens at "
        f"${GEMINI_PRICE_INPUT_PER_M}/${GEMINI_PRICE_OUTPUT_PER_M} per 1M "
        "(input/output) — verify current rates, these drift",
    )


def extract(backend: str, stdout: str, using_subscription: bool = False) -> RunCost:
    if backend == "claude":
        return extract_claude(stdout, using_subscription)
    if backend == "gemini":
        return extract_gemini(stdout)
    return RunCost(backend, stdout, None, f"unknown backend {backend!r}")
