# EU AI Act: the house standard

QualiZeal builds to the EU AI Act (Regulation (EU) 2024/1689, as amended by the Digital Omnibus on AI, Regulation (EU)
2026/1744, in force since 27 July 2026) whether or not a system reaches the EU. `qz aiact` keeps the record and checks
the evidence; this page is what the lanes need to fill the record in well. It is not legal advice: the classification
is final once a person (the client's compliance owner, or ours for internal tools) confirms it.

Checked on 21 November 2026 against the Official Journal summaries, the Commission's Article 50 guidelines (20 July
2026) and the Code of Practice on transparency of AI-generated content (10 June 2026).

## The six steps, in order

1. **Classify.** Prohibited (Article 5), high-risk (Article 6 with Annex I or Annex III), limited risk (Article 50
   transparency duties) or minimal. A system can be high-risk and carry transparency duties at once.
2. **Name the role.** Provider (builds it, or has it built, and puts it out under its own name), deployer (uses it
   under its own authority at work), importer, distributor or authorised representative. When we build for a client,
   the client is usually the provider; we record the role from the owner's side.
3. **Check the EU link.** Placed on the EU market, used in the EU, or its output used in the EU. No link: the Act may
   not bind it in law, and we follow it anyway (practices `standards.eu_ai_act` = follow).
4. **Govern.** Risk register, data governance, logs, human oversight, accuracy and robustness, technical documentation.
5. **Prove.** Transparency notices and marks; for high-risk systems, conformity assessment, EU declaration, CE marking
   and EU database registration.
6. **Monitor.** Post-market monitoring plan and the serious-incident runbook.

## Dates that matter now

| From | What applies |
|---|---|
| 2 February 2025 | Article 5 bans; Article 4 AI literacy (the Omnibus made it a duty to take measures, not to guarantee a level) |
| 2 August 2025 | General-purpose AI model duties (Articles 53 and 55) |
| 2 August 2026 | Article 50 transparency: tell people they deal with an AI; mark generated content; label deepfakes and AI-written public-interest text |
| 2 December 2026 | Marking (Article 50(2)) for generative systems already on the market before 2 August 2026; new Article 5 bans on non-consensual intimate imagery and child sexual abuse material |
| 2 December 2027 | High-risk duties for Annex III systems (stand-alone) |
| 2 August 2028 | High-risk duties for Annex I systems (safety components of regulated products) |

## Prohibited practices (Article 5)

Manipulative or deceptive techniques that cause significant harm; exploiting age, disability or social or economic
situation; social scoring; predicting crime from profiling alone; untargeted scraping of facial images; emotion
recognition at work or in education (medical and safety reasons aside); biometric categorisation of sensitive traits;
real-time remote biometric identification in public spaces for law enforcement (narrow exceptions); and, from
2 December 2026, generating non-consensual intimate imagery or child sexual abuse material. Any "yes" stops the work.

## High-risk areas (Annex III)

Biometrics; critical infrastructure; education (admission, assessment, proctoring); employment (recruiting,
screening, promotion, task allocation, monitoring or rating workers); essential services (public benefits, credit
scoring, life and health insurance pricing, emergency triage); law enforcement; migration and borders; justice and
democratic processes. Under Article 6(3) a provider may assess an Annex III system as not high-risk when it only does
a narrow procedural task, improves a finished human activity, detects patterns without replacing human judgment, or
prepares an assessment: the assessment must be written down and the system still registered (simplified). A system
that profiles people is always high-risk.

**Watch the drift.** A support bot is limited risk; the same bot used to rate the staff who handle escalations is
Annex III. A change of use is a change request: re-run `qz aiact`.

## What a high-risk provider owes

Risk management (Article 9), data governance (10), technical documentation (11, Annex IV), automatic logs (12),
instructions for use (13), human oversight (14), accuracy, robustness and cybersecurity (15), a quality management
system (17), conformity assessment (43), the EU declaration (47), CE marking (48), registration (49), post-market
monitoring (72) and serious-incident reports (73: within 15 days; 2 days for a widespread infringement or critical
infrastructure; 10 days after a death). Deployers: use as instructed, assign competent oversight, keep logs at least
six months, inform workers, and a fundamental-rights impact assessment where required (public bodies, credit and
insurance). SMEs and the new small mid-caps get simpler documentation and lower penalty caps.

## How the starters meet it

Every starter ships `docs/ai-act/` (the record, a risk register, a monitoring plan and an incident runbook). Agents
return `ai_notice` (show it before the first reply) and `ai_generated` (true only when a model wrote the text, false
for fixed refusals and approval notices). The knowledge kits show the notice on the page; text-to-SQL shows it with
every answer. Article 15 evidence is the gold set and the six guardrails; Article 14 is the approval gate; Article 12
is the traces and audit logs. Penalties for reference: up to EUR 35 million or 7% of worldwide turnover for an
Article 5 breach, EUR 15 million or 3% for most other duties.
