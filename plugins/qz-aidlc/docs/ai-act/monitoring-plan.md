# Monitoring plan: QualiZeal AI-DLC Studio

| Signal | Where it comes from | How often | Review when |
|---|---|---|---|
| Red-team pass rate | `qz redteam` | every release | anything below 100% |
| The house standards | `qz standards --studio` | every release | any standard not met |
| Denied and asked actions | the policy guard's decisions in each run ledger | weekly | a new kind of denial, or a jump |
| Tokens and time per stage | report cards (`qz report`) | weekly | a stage over its budget twice running |
| Incidents and near misses | the incident runbook | as they come | any serious incident |

A change to a hook, a policy rule or a lane is a release: the suite and the red-team set run first.
