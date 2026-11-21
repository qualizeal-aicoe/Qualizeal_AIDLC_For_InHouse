---
title: Destructive commands need a person's yes
author: Prashobh Paul
date: 2026-11-21
touches:
  - plugins/qz-aidlc/templates/build/cli-harness-py/mockctl/cli.py
---

## Decided
- A destructive command refuses to run without `--yes` (`kind == "destructive" and not (yes or dry_run)`): the agent shows the dry run, and adds `--yes` only after the person agreed to it.

## Ruled out
- A `--force` flag or an environment variable that skips the refusal: it would let an agent clear a shared server on its own say.
