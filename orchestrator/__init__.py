"""Orchestration layer for the AppSec remediation pipeline (Phase 2+).

This package contains only the deterministic plumbing: classifying a ticket,
picking the right knowledge-base files, assembling context, and deciding
fix-vs-defend routing for review comments. The actual patch writing and
false-positive judgment is done by Claude Code / Aider itself, invoked by
`cli.py` inside GitHub Actions — this code prepares its inputs and parses
its outputs, it does not replace its judgment.
"""
