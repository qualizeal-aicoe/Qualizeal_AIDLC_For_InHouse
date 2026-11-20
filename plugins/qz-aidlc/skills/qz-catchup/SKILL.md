---
name: qz-catchup
description: Catch the person up after they step away - what changed since their last message in plain words, and every decision waiting on them, each one decidable from the reply alone
disable-model-invocation: true
---
The person remembers their last message and nothing after it. Subagent results and notifications are not theirs.
Keep this turn read-only: run nothing that changes a file, a ticket or a repository.

1. Gather: your own work since their last message, subagent reports, `run_status` and the latest `report_card` path
   if a run is open, pending gates, and anything still waiting on them from earlier.
2. Open with one sentence: what waits on them, or "nothing waits on you".
3. What happened, in under 100 words: one line per thing they asked for, saying what came of it and whether it is
   done, running, failed or not checked, the way you would say it aloud ("search was slow from a missing index").
   Name each bug found on the way. Leave out work that changed nothing for them, hashes, paths and commands.
4. Each decision waiting on them: the call, your pick, what it changes for users, the evidence, and its risk (even
   "low risk: only the colours change"). Options get what each one gains and costs. Never cut a decision to save
   words, and never invent one to fill the list.
5. One line on work left that you can do yourself.

Draw a picture only where it explains more than a sentence (a pipeline with each step's state, a before and after);
never for a status list.
