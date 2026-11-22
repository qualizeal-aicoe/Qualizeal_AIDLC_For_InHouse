"""Governed long-term memory for agents: what a person tells an assistant is kept per person, updated with its history,
recalled when it helps, and forgotten when they ask. Sensitive kinds wait for consent, personal numbers are never
stored, and text that tries to instruct a model is not kept at all."""

__version__ = "0.1.0"
