---
title: Keep READY at 70 percent
author: Prashobh Paul
date: 2026-11-21
touches:
  - plugins/qz-aidlc/lib/qz/auditkit/scan.py
---

## Decided
- A project is READY only at 70% or more with no blocker scored 0 (`pct < 70` means NOT READY): that bar is what the README, the audit page and every starter's CI promise, so moving it changes what READY means for every project already scored.

## Ruled out
- Lowering the bar to let a starter pass: fix the starter's gaps instead. The command-line harness reached 90.6% by adding its decision record, runbook and CI, not by moving the bar.

## Watch out
- A blocker at 0 fails a project whatever its percentage; an item that does not apply is marked not applicable, never scored up.
