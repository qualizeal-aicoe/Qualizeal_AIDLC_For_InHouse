"""QualiZeal names for the parts of the harness. One place, so messages, the doctor and the guide agree."""
from __future__ import annotations

PREFIX = "qz"
RULE_PREFIX = "QZ-"

# name -> (what it is, where it lives)
PARTS: dict[str, tuple[str, str]] = {
    "qz-guard": ("checks every tool call against the policy before it runs; rule ids start with QZ-", "hooks/hooks.json, lib/qz/guard.py, policy/qz-policy.json"),
    "qz-audit": ("hash-chained record of what happened in a run", ".qz/audit/"),
    "qz-ledger": ("run ledger: lane, stage, gates, tokens and time per stage; hand-off note between sessions", ".qz/runs/<run>/"),
    "qz-report": ("report card for a run: the five AI-DLC measures and where the tokens went", ".qz/runs/<run>/report-card.html"),
    "qz-kf": ("knowledge fabric: search earlier work instead of pasting it", ".qz/kf/"),
    "qz-graph": ("code graph: ask what calls what instead of reading files", ".qz/graph/graph.db"),
    "qz-craft": ("measuring tools for pages, decks and user-interface flows", "lib/qz/craft/"),
    "qz-workspace": ("local projects folder with code, docs, ppts, guides, architecture per project", "D:\\New_Projects (Windows)"),
    "qz-mcp": ("the tool server the lanes call", ".mcp.json, scripts/qz_mcp.py"),
    "qz-console": ("live map of the run beside the chat (desktop, separate plugin)", "plugins/qz-console"),
    "qz-context": ("shortens large tool output before the model reads it and keeps the original searchable", ".qz/ctx/ctx.sqlite"),
    "qz-memory": ("project notes a person confirmed, read at the start of each session, with history and undo", ".qz/memory/"),
    "qz-decisions": ("team decisions tied to the code they are about: shown when an agent opens that code, checked before a commit and in CI", "docs/decisions/, lib/qz/decisions.py"),
    "qz-conventions": ("branch, commit and merge-request conventions checked at the commit, the push and the merge request; the delivery gate suggests the squash type and says what it releases", "lib/qz/conventions.py"),
    "qz-practices": ("the team's practices: QualiZeal defaults, overridden per team at practices discovery", "policy/qz-practices.json, .qz/practices.json"),
    "qz-aidlc-workspace": ("the team's shared AI-DLC workspace: the records in one repository, the service repositories beside it under services/", "qz aidlc setup, qz aidlc check, lib/qz/aidlcws.py"),
    "qz-guardrails": ("the six gates every agent passes (input filter, output filter, tool allowlist, human approval, step limits, sandboxed execution), checked with evidence on the Studio and on any project", "qz guardrails, lib/qz/auditkit/gates.py"),
    "qz-aiact": ("the EU AI Act record every project keeps: risk class, role, the obligations they bring and evidence for each; a person confirms the class", "qz aiact, docs/ai-act/, lib/qz/auditkit/aiact.py"),
    "qz-stack": ("open source first: which layers of an AI stack are open, which are tied to a vendor by recorded choice, and the open option for each", "qz stack, lib/qz/auditkit/oss.py"),
    "qz-cost": ("the six cost levers (prompt caching, model routing, batch, semantic cache, trimmed context, smaller models), checked with evidence", "qz cost, lib/qz/auditkit/cost.py"),
    "qz-standards": ("one scorecard for the house standards: the six guardrails, the EU AI Act, open source first, the cost levers and the solution shape; the CI gate in every starter", "qz standards, lib/qz/auditkit/standards.py"),
    "qz-route": ("reads each request without a model call and names the lane, tool, agent, model and effort that fit, with what is in hand", "policy/qz-routes.json, lib/qz/router.py"),
    "qz-office": ("decks, planning and status workbooks, estimates and e-mails written for each reader", "lib/qz/office/"),
    "qz-publish": ("saves locally first, then pushes to a new, existing or team repository after a person's yes", "lib/qz/ws/publish.py"),
}

# AWS AI-DLC agents keep their upstream slugs (the engine looks them up by slug); these are the names people see.
# slug -> (QualiZeal name, name shown, upstream name shown)
ROSTER: dict[str, tuple[str, str, str]] = {
    "aidlc-product-lead-agent": ("qz-product-lead", "QZ Product Lead", "Product Lead"),
    "aidlc-product-agent": ("qz-product", "QZ Product", "Product Agent"),
    "aidlc-design-agent": ("qz-design", "QZ Design", "Design Agent"),
    "aidlc-architect-agent": ("qz-architect", "QZ Architect", "Architect Agent"),
    "aidlc-architecture-reviewer-agent": ("qz-architecture-reviewer", "QZ Architecture Reviewer", "Architecture Reviewer"),
    "aidlc-aws-platform-agent": ("qz-aws-platform", "QZ AWS Platform", "AWS Platform Agent"),
    "aidlc-developer-agent": ("qz-developer", "QZ Developer", "Developer Agent"),
    "aidlc-quality-agent": ("qz-quality", "QZ Quality", "Quality Agent"),
    "aidlc-devsecops-agent": ("qz-devsecops", "QZ DevSecOps", "DevSecOps Agent"),
    "aidlc-compliance-agent": ("qz-compliance", "QZ Compliance", "Compliance Agent"),
    "aidlc-delivery-agent": ("qz-delivery", "QZ Delivery", "Delivery Agent"),
    "aidlc-pipeline-deploy-agent": ("qz-pipeline-deploy", "QZ Pipeline & Deploy", "Pipeline & Deploy Agent"),
    "aidlc-operations-agent": ("qz-operations", "QZ Operations", "Operations Agent"),
    "aidlc-composer-agent": ("qz-composer", "QZ Composer", "Composer Agent"),
}


def tag(part: str) -> str:
    """Label a harness message with the part that wrote it: [qz-guard] ..."""
    return f"[{part}]"


def shown(agent: str) -> str:
    """The QualiZeal name for an agent, whatever layer it comes from."""
    a = (agent or "").split(":")[-1]
    return ROSTER[a][0] if a in ROSTER else a


def apply_roster(root) -> int:
    """Show the AWS AI-DLC agents under their QualiZeal names. Only the display_name line changes, and only
    where it still holds the upstream value, so a name someone chose is left alone. Slugs never change:
    the AI-DLC engine finds agents by slug."""
    import re
    from pathlib import Path
    done = 0
    for slug, (_, shown_as, upstream) in ROSTER.items():
        f = Path(root) / ".claude" / "agents" / f"{slug}.md"
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        new, n = re.subn(rf"(?m)^display_name:[ \t]*{re.escape(upstream)}[ \t]*$", f"display_name: {shown_as}", text, count=1)
        if n:
            f.write_text(new, encoding="utf-8", newline="")
            done += 1
    return done
