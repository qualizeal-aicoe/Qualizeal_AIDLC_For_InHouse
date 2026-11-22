---
title: Lane pages stay under 1100 tokens
author: Prashobh Paul
date: 2026-11-21
touches:
  - tests/test_names.py#test_context_footprint_stays_inside_its_budget
  - plugins/qz-aidlc/skills/qz/lanes/
---

## Decided
- Each lane page stays under 1,100 tokens and the conductor under 1,300 (`max(use["lanes"].values()) < 1100`): a lane page is read at the start of every task in its lane, so its length is paid on every run.

## Ruled out
- Raising the limit when the RAG lane reached 1,119 tokens: its web paragraph was trimmed instead.

## Watch out
- Everything listed before work starts is held under 8,000 tokens; a new tool or skill description has to fit inside what is left.
