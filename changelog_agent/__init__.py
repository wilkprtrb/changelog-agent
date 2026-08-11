"""Changelog Agent — turn git commits into plain-language, customer-facing release notes.

Local-first, $0 budget, Python stdlib only. Uses the local Ollama API
(qwen2.5:7b) to write release notes. Human review gate is non-negotiable:
the CLI writes drafts to drafts/ and never auto-publishes.
"""

__version__ = "0.1.0"
