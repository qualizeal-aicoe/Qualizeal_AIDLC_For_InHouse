# Incident runbook: QualiZeal AI-DLC Studio

1. Contain: turn the plugin off for the affected repository (`/plugin disable qz-aidlc`), keep the run ledger and the transcript.
2. Decide within a day whether it is serious (Article 3(49)): the AI CoE decides with the engineering lead.
3. Report: Anthropic is the provider of Claude Code; serious incidents in its behaviour go to Anthropic as well as to the client under the contract. If personal data was breached, the GDPR clock is 72 hours (Article 33).
4. Fix: add a red-team case or a test that would have caught it, and record the decision in docs/decisions/.
