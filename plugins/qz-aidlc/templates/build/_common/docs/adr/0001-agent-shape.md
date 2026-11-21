---
status: proposed
decision-makers: to be named
---

# How __NAME__ is put together: a scripted model for tests, a person before any irreversible action, hard limits

## Context and Problem Statement

__NAME__ is __STACK_LINE__ It looks up orders and can issue refunds. A refund moves money and cannot be undone, the
model's answers vary from run to run, and order notes are written by customers, so anything in them may try to steer
the agent. We need to change prompts, tools and models often without losing track of what still works.

## Decision Drivers

* Nothing irreversible happens without a person saying yes.
* Every change can be checked in CI without a key, a network call or a bill.
* A runaway loop or an expensive prompt stops on its own.
* Text that arrives through a tool is data, never instructions.

## Considered Options

* Let the model call every tool directly and review the logs afterwards.
* Gate the irreversible tools behind an approval step, keep reads ungated, and test against a scripted stand-in model.
* Keep a person in every step, reads included.

## Decision Outcome

Chosen: gate the irreversible tools and test against a scripted stand-in model. Reads stay fast; the one action that
moves money waits for a person, and the same gold set runs offline in CI and live before a release.

### Consequences

* Good: CI proves the wiring (tools, approval gate, limits, tracing) on every pull request, at no cost.
* Good: limits on turns, output tokens and time live in `__POLICY__`, versioned with the code.
* Bad: the stand-in model proves the wiring, not answer quality. The live gold set (`evals/eval.live.json`) measures
  the model, and it needs a key and a budget.
* Bad: a refund now has a waiting state that the product has to show to the customer.

### Confirmation

The gold set has a safety case for the planted instruction in an order note and a gate case for the refund. A
release is blocked when either flips (`qz eval compare`). A new tool that writes, sends, pays or deletes is added to
the approval list in `__POLICY__` in the same pull request, with a gold case.
