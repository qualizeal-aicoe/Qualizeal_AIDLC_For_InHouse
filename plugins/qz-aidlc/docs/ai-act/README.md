# EU AI Act record: QualiZeal AI-DLC Studio

Regulation (EU) 2024/1689, as amended by the Digital Omnibus on AI (Regulation (EU) 2026/1744). The data is in `classification.json`; `qz aiact` shows the obligations it brings and the evidence for each. Not legal advice.

| | |
|---|---|
| Intended purpose | Helps QualiZeal engineering teams plan, build, test and deliver software and AI systems inside Claude Code. Every write, push and send waits for a person, and merging is always a person's step. Out of scope: rating or monitoring the people who use it. |
| Risk class | Limited risk: transparency duties (Article 50) |
| Role | Deployer: you use it under your own authority in your work |
| EU link | Not yet known. QualiZeal follows the Act anyway |
| Confirmed by | Not yet: `qz aiact confirm --yes` |

## Prohibited practices (Article 5)

| Practice | Here |
|---|---|
| Subliminal, manipulative or deceptive techniques that distort behaviour and cause significant harm | No |
| Exploiting a person's age, disability or social or economic situation | No |
| Social scoring that leads to unjustified or disproportionate treatment | No |
| Predicting that a person will commit a crime from profiling or personality traits alone | No |
| Untargeted scraping of facial images to build recognition databases | No |
| Inferring emotions at work or in education, other than for medical or safety reasons | No |
| Biometric categorisation to infer race, political opinions, union membership, religion, sex life or orientation | No |
| Real-time remote biometric identification in public spaces for law enforcement | No |
| Generating non-consensual intimate imagery or child sexual abuse material (added by the Omnibus, from 2 December 2026) | No |

## Transparency (Article 50, in force since 2 August 2026)

- People are told they are dealing with an AI: "made with the QualiZeal AI-DLC Studio, an AI-assisted engineering system" (`lib/qz/brand.py`).
- Generated output carries a machine-readable mark: every Studio page carries a generator tag; AI-written commits carry Claude Code's Co-Authored-By trailer (`lib/qz/brand.py`).

## Kept for every system, high-risk or not

- [Risk register](risk-register.md): each risk, its control and its owner.
- [Monitoring plan](monitoring-plan.md): what is watched after release and what triggers a review.
- [Incident runbook](incident-runbook.md): what counts as serious, who decides, the deadlines.
