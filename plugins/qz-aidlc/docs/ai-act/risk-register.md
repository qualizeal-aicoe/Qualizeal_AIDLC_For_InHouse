# Risk register: QualiZeal AI-DLC Studio

Kept as the house standard (Article 9 asks it of high-risk systems; the Studio is not one). Reviewed at each release.

| # | Risk | Control in the Studio | Owner | Last reviewed |
|---|---|---|---|---|
| 1 | Instructions hidden in repository files, web pages or tool results steer the agent | injection patterns read on every tool result; connectors read-only unless a person approves a write; 147 red-team cases at every release | AI CoE | release 1.0.0 |
| 2 | A key, a card number or an ID number leaves the machine | prompts carrying them are blocked; secrets scanned before anything is published; tokens live only in the OS keychain or the environment | AI CoE | release 1.0.0 |
| 3 | Client rates or margin reach a client document | rates and margin stay in .qz/internal/; memory refuses them; publishing checks for them | AI CoE | release 1.0.0 |
| 4 | Wrong code reaches master | test-first, ship_check, the decision trail and the house standards before every merge request; a person squash-merges | Engineering lead | release 1.0.0 |
| 5 | A destructive or irreversible command runs | deny rules for destructive commands; pushes and repository writes ask first; `qz undo` restores checkpoints | AI CoE | release 1.0.0 |
| 6 | A long session runs up cost or time | token budget per stage, step caps, loop detection, and the router's model tiers | Engineering lead | release 1.0.0 |
| 7 | Use drifts into rating people from the run ledgers (Annex III, employment) | the intended purpose excludes it; ledgers describe the work, never a person | AI CoE | release 1.0.0 |
