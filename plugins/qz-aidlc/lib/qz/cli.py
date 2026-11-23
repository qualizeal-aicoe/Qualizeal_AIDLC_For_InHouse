"""`qz` command line: the deterministic tools the skills call. No model, and no
network except where a subcommand says so (Knowledge Fabric ingestion from
Confluence or GitHub)."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from . import audit, guard, ledger, redteam, report
from .util import now, project_dir


def _proj() -> Path:
    return project_dir()


def cmd_run(a):
    proj = _proj()
    if a.action == "start":
        led = ledger.start_run(proj, a.lane, a.key or "", a.title or "")
        audit.append(proj, "RUN_START", run=led["run_id"], lane=a.lane, key=a.key, who=led["owner"]["email"])
        print(f"Recorded: run {led['run_id']} · lane {a.lane} · owner {led['owner']['name']}")
    else:
        led = ledger.load(proj, create=False)
        if not led:
            print("No run yet. Start one with: qz run start <lane> --key <KEY>")
            return
        used, lim, frac = ledger.budget_state(proj, led)
        print(f"Run {led['run_id']} · lane {led['lane']} · key {led['key'] or '-'} · stage {led['stage']} ({int(frac*100)}% of {lim:,} tokens)")
        print("Stages: " + " → ".join(led["order"]))


def cmd_stage(a):
    proj = _proj()
    led = ledger.load(proj)
    if ledger.set_stage(led, a.name):
        ledger.save(proj, led)
        audit.append(proj, "STAGE", run=led["run_id"], stage=a.name)
    print(f"Recorded: stage {led['stage']}")


def _file_locally(proj, path, kind, led=None):
    """Put a result into the project's docs, ppts, guides or architecture folder. Best effort."""
    try:
        from .ws import core
        return core.auto_file(proj, path, kind, (led or {}).get("key"))
    except Exception:
        return None


def cmd_output(a):
    """Seal an approved output: copy it under .qz/outputs/<run>/ and put its hash on the audit chain."""
    proj = _proj()
    led = ledger.load(proj)
    src = Path(a.path).resolve()
    if not src.is_file():
        sys.exit(f"Not a file: {a.path}")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    dest_dir = proj / ".qz" / "outputs" / led["run_id"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    _file_locally(proj, src, a.kind, led)
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
        dest = dest_dir / f"{src.stem}.{now()[:19].replace(':', '')}{src.suffix}"
    shutil.copy2(src, dest)
    rel = str(dest.relative_to(proj)).replace("\\", "/")
    led["outputs"].append({"path": rel, "kind": a.kind, "sha256": digest, "ts": now(), "stage": led["stage"]})
    ledger.save(proj, led)
    audit.append(proj, "OUTPUT_SEALED", run=led["run_id"], path=rel, kind=a.kind, sha256=digest)
    print(f"Sealed: {rel} sha256 {digest[:16]}…")


def cmd_takeover(a):
    proj = _proj()
    led = ledger.load(proj)
    if a.layer not in ("spec", "context", "environment", "verification", "state"):
        sys.exit("layer must be one of: spec, context, environment, verification, state")
    led["takeovers"].append({"ts": now(), "stage": a.stage, "layer": a.layer, "why": a.why})
    ledger.save(proj, led)
    audit.append(proj, "TAKEOVER", run=led["run_id"], stage=a.stage, layer=a.layer)
    print(f"Recorded: takeover at {a.stage} ({a.layer})")


def cmd_review(a):
    proj = _proj()
    led = ledger.load(proj)
    val = {"accept": 1.0, "rework": 0.0}[a.decision]
    led["outputs"].append({"kind": "review-decision", "value": val, "ts": now(), "path": a.link or "", "sha256": ""})
    ledger.save(proj, led)
    audit.append(proj, "REVIEW_DECISION", run=led["run_id"], decision=a.decision, link=a.link)
    print(f"Recorded: review {a.decision}")


def cmd_report(a):
    jp, hp = report.write(_proj(), a.run)
    s = json.loads(jp.read_text(encoding="utf-8"))
    t = s["totals"]
    _file_locally(_proj(), hp, "report-card", ledger.load(_proj()))
    print(f"Wrote {hp}")
    print(f"Result: {len(s['stages'])} stages · {t['input'] + t['output'] + t['cache_read'] + t['cache_write']:,} tokens · "
          f"gates {s['gates']['approved'] + s['gates']['answered']} passed, {s['gates']['pending']} pending · audit {'intact' if s['audit']['intact'] else 'BROKEN'}")


def cmd_audit(a):
    ok, msg = audit.verify(_proj())
    print(msg)
    sys.exit(0 if ok else 2)


def cmd_redteam(a):
    r = redteam.run()
    print(f"Guard red-team: {r['passed']}/{r['total']} passed")
    for f in r["failures"]:
        print("  FAIL", json.dumps(f))
    sys.exit(0 if not r["failures"] else 2)


def cmd_guard(a):
    tool, payload = (a.tool, {"command": a.text}) if a.tool in ("Bash", "PowerShell") else (a.tool, {"file_path": a.text, "url": a.text})
    d = guard.decide(tool, payload, _proj())
    print(f"{d.action or 'no objection'} {d.rule} {d.message}".strip())
    if a.explain and tool == "Bash":
        from . import shellscan
        print(json.dumps(shellscan.explain(guard.normalise(a.text)), indent=2))


def cmd_snapshots(a):
    from . import snapshot
    proj = _proj()
    off = snapshot.enabled(proj)
    if off:
        print(f"Snapshots are off here: {off}.")
        return
    rows = snapshot.listing(proj)
    if not rows:
        print("No turn has changed files yet.")
    for r in rows:
        print(f"turn {r['turn']:>4}  {r['at'][:16].replace('T', ' ')}  {r['files']:>3} file(s){'  (undone)' if r['undone'] else ''}  {', '.join(r['sample'])}")


def cmd_tokens(a):
    from . import footprint
    print(footprint.text(_proj()))


def cmd_tools(a):
    """Show or set which tools a session lists. The setting takes effect in the next session."""
    from . import mcp_tools
    from .util import read_json
    cfgp = _proj() / ".qz" / "config.json"
    if a.action == "set":
        name = a.profile or "all"
        if name not in mcp_tools.PROFILES and any(g not in mcp_tools.GROUPS for g in name.split(",")):
            sys.exit(f"Unknown profile '{name}'. Profiles: {', '.join(mcp_tools.PROFILES)}; or a comma list of groups: {', '.join(mcp_tools.GROUPS)}.")
        cfg = read_json(cfgp, {}) or {}
        cfg["tools"] = name
        cfgp.parent.mkdir(parents=True, exist_ok=True)
        cfgp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        audit.append(_proj(), "TOOLS_PROFILE", profile=name)
        print(f"Tools profile set to {name} in {cfgp}. It applies from the next session.")
    now_ = mcp_tools.profile_name()
    listed = mcp_tools.active()
    print(f"Tools profile: {now_} · {len(listed)} of {len(mcp_tools.TOOLS)} tools listed")
    for name, groups in mcp_tools.PROFILES.items():
        n = len(mcp_tools.active(name))
        print(f"  {name:<9} {n:>2} tools  {'everything' if groups is None else ' + '.join(groups)}")
    hidden = [t for t in mcp_tools.TOOLS if t not in listed]
    if hidden:
        print("Not listed in this profile: " + ", ".join(hidden))


def cmd_doctor(a):
    from . import doctor
    out = a.json if a.json != "" else "doctor-report.json"
    sys.exit(doctor.run(_proj(), do_fix=a.fix, json_out=out, ci=a.ci, repo=a.repo))


def github_agent(proj: Path, yes: bool, force: bool = False) -> int:
    """Put the Studio's GitHub agent workflow in this repository (.github/workflows/qz-agent.yml)."""
    src = Path(__file__).resolve().parents[2] / "templates" / "github" / "qz-agent.yml"
    dst = proj / ".github" / "workflows" / "qz-agent.yml"
    if dst.exists() and not force:
        print(f"{dst.relative_to(proj)} is already there. Run again with --force to replace it.")
        return 1
    if not yes:
        print(f"This writes {dst.relative_to(proj)}: comment '/qz <request>' on an issue or pull request and Claude works on it on a "
              "branch of its own, then opens a pull request (it never merges). Run again with --yes to write it, then follow "
              "docs/GITHUB-AGENT.md in the Studio repository: two secrets and the Claude GitHub App, all on the GitHub website.")
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Wrote {dst.relative_to(proj)}. Commit it in a pull request; then add the secrets QZ_STUDIO_TOKEN and ANTHROPIC_API_KEY "
          "(or CLAUDE_CODE_OAUTH_TOKEN) in Settings > Secrets and variables > Actions, and install the Claude GitHub App.")
    return 0


def cmd_setup(a):
    from . import doctor
    if a.what in ("detect", "statusline", "plan", "org"):
        from . import onboard
        sys.exit(onboard.main(a.what, a.rest))
    if a.what == "github-agent":
        sys.exit(github_agent(_proj(), "--yes" in a.rest, "--force" in a.rest))
    if "-h" in a.rest or "--help" in a.rest:
        print("qz setup workspace|engine|deps [--yes] · qz setup detect|statusline|plan|org (each with --help)")
        return
    a.yes = "--yes" in a.rest
    if a.what == "sandbox":
        sys.exit(doctor.setup_sandbox(_proj(), a.yes))
    if a.what == "deps":
        if not a.yes:
            print(f"This installs the Python packages the tools use (office files, PDF, browser checks) into the Studio's own "
                  f"environment, {doctor.STUDIO_VENV}, with uv. Nothing else on this machine changes.\nRun again with --yes to install.")
            return
        doctor.fix(["packages"])
        return
    sys.exit({"workspace": doctor.setup_workspace, "engine": doctor.setup_engine}[a.what](_proj()))


def _lane(mod: str, name: str, rest: list[str]) -> None:
    try:
        m = __import__(f"qz.{mod}.cli", fromlist=["main"])
    except ModuleNotFoundError as e:
        if e.name in (f"qz.{mod}", f"qz.{mod}.cli"):
            sys.exit(f"'{name}' is not part of this vendored kit. Use the qz-aidlc plugin, or vendor the full profile: qz vendor --profile full")
        raise
    m.main(name, rest)


PASS_THROUGH = {"ship": ("qz.ship", {}), "publish": ("qz.ws.publish", {}), "undo": ("qz.snapshot", {}),
                "redo": ("qz.snapshot", {"redo": True}), "goal": ("qz.goal", {}), "spec": ("qz.spec.cli", {}),
                "hillclimb": ("qz.hillclimb", {}), "board": ("qz.board", {}), "decisions": ("qz.decisions", {}),
                "conventions": ("qz.conventions", {}), "practices": ("qz.practices", {}), "aidlc": ("qz.aidlcws", {}),
                "guardrails": ("qz.auditkit.gates", {}), "aiact": ("qz.auditkit.aiact", {}), "stack": ("qz.auditkit.oss", {}),
                "cost": ("qz.auditkit.cost", {}), "standards": ("qz.auditkit.standards", {}), "structure": ("qz.auditkit.shape", {}), "golive": ("qz.auditkit.golive", {}), "autonomy": ("qz.autonomy", {}), "claims": ("qz.claims", {}),
                "debt": ("qz.debt", {})}
# Lane tools by command name -> package under qz/. Each parses its own options.
LANES = {"kf": "kf", "price": "bid", "sow": "bid", "deck": "bid", "voice": "bid", "demo": "demo", "arch": "arch",
         "build": "buildkit", "eval": "evalkit", "test": "stlc", "audit-project": "auditkit", "craft": "craft",
         "project": "ws", "graph": "graph", "vendor": "vendor", "ctx": "ctx", "data": "data", "office": "office",
         "route": "route"}
SETUP = ("workspace", "engine", "deps", "detect", "statusline", "plan", "org", "github-agent", "sandbox")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # The commands below parse their own options. argparse.REMAINDER drops a first word that starts with "-"
    # (qz undo --yes, qz vendor --profile full), so they are handed over before the top-level parser sees them.
    if argv and argv[0] in PASS_THROUGH:
        mod, kw = PASS_THROUGH[argv[0]]
        sys.exit(__import__(mod, fromlist=["main"]).main(argv[1:], **kw))
    if argv and argv[0] in LANES:
        return _lane(LANES[argv[0]], argv[0], argv[1:])
    if argv and argv[0] == "setup":
        rest = argv[1:]
        what = next((w for w in rest if not w.startswith("-")), None)
        if what in SETUP:
            rest.remove(what)
            return cmd_setup(argparse.Namespace(what=what, rest=rest))
        if what is None and ("-h" in rest or "--help" in rest):
            print("qz setup workspace|engine|deps [--yes] · qz setup detect|statusline|plan|org (each with --help)"
                  " · qz setup github-agent [--yes] [--force]")
            return None
    ap = argparse.ArgumentParser(prog="qz", description="QualiZeal AI-DLC tools")
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("action", choices=["start", "status"]); r.add_argument("lane", nargs="?", default="general")
    r.add_argument("--key"); r.add_argument("--title"); r.set_defaults(f=cmd_run)
    s = sp.add_parser("stage"); s.add_argument("name"); s.set_defaults(f=cmd_stage)
    o = sp.add_parser("output"); o.add_argument("path"); o.add_argument("--kind", default="deliverable"); o.set_defaults(f=cmd_output)
    t = sp.add_parser("takeover"); t.add_argument("stage"); t.add_argument("layer"); t.add_argument("why"); t.set_defaults(f=cmd_takeover)
    v = sp.add_parser("review"); v.add_argument("decision", choices=["accept", "rework"]); v.add_argument("--link"); v.set_defaults(f=cmd_review)
    p = sp.add_parser("report"); p.add_argument("--run"); p.set_defaults(f=cmd_report)
    sp.add_parser("audit").set_defaults(f=cmd_audit)
    sp.add_parser("redteam").set_defaults(f=cmd_redteam)
    g = sp.add_parser("guard"); g.add_argument("text"); g.add_argument("--tool", default="Bash"); g.add_argument("--explain", action="store_true"); g.set_defaults(f=cmd_guard)
    dr = sp.add_parser("doctor", help="check this machine before a session; --fix does the safe fixes")
    dr.add_argument("--fix", action="store_true", help="install the Studio's own packages and put the demo's packages in uv's cache")
    dr.add_argument("--json", nargs="?", const="", default=None, help="write the report (default doctor-report.json)")
    dr.add_argument("--ci", action="store_true", help="skip the checks that need a person's sign-in (Claude Code, GitHub)")
    dr.add_argument("--repo", default="qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse", help="the Studio repository to test access to")
    dr.set_defaults(f=cmd_doctor)
    sp.add_parser("tokens").set_defaults(f=cmd_tokens)
    gd = sp.add_parser("guide"); gd.add_argument("--out")
    gd.set_defaults(f=lambda a: __import__("qz.guide", fromlist=["main"]).main("guide", ["--out", a.out] if a.out else []))
    tl = sp.add_parser("tools"); tl.add_argument("action", nargs="?", default="show", choices=["show", "set"]); tl.add_argument("profile", nargs="?"); tl.set_defaults(f=cmd_tools)
    sh = sp.add_parser("ship", add_help=False); sh.add_argument("rest", nargs=argparse.REMAINDER)
    sh.set_defaults(f=lambda a: sys.exit(__import__("qz.ship", fromlist=["main"]).main(a.rest)))
    pb = sp.add_parser("publish", add_help=False); pb.add_argument("rest", nargs=argparse.REMAINDER)
    pb.set_defaults(f=lambda a: sys.exit(__import__("qz.ws.publish", fromlist=["main"]).main(a.rest)))
    for name, mod, kw in (("undo", "qz.snapshot", {}), ("redo", "qz.snapshot", {"redo": True}), ("goal", "qz.goal", {}),
                          ("spec", "qz.spec.cli", {})):
        x = sp.add_parser(name, add_help=False); x.add_argument("rest", nargs=argparse.REMAINDER)
        x.set_defaults(f=lambda a, mod=mod, kw=kw: sys.exit(__import__(mod, fromlist=["main"]).main(a.rest, **kw)))
    sn = sp.add_parser("snapshots"); sn.set_defaults(f=cmd_snapshots)
    su = sp.add_parser("setup", add_help=False); su.add_argument("what", choices=list(SETUP))
    su.add_argument("rest", nargs=argparse.REMAINDER); su.set_defaults(f=cmd_setup)
    for name, mod in LANES.items():
        x = sp.add_parser(name, add_help=False)
        x.add_argument("rest", nargs=argparse.REMAINDER)
        x.set_defaults(f=lambda a, mod=mod, name=name: _lane(mod, name, a.rest))
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
