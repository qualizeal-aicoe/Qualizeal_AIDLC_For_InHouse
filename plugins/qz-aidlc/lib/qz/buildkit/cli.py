"""qz build list | new <stack> <dest> [--name "Order Support"] [--module example.com/x] [--no-kit] [--stage N]
             | stage <dest> <N> [--yes]
             | solution <agent stack> <dest> [--name ...] [--module ...] [--no-kit]
             | pipeline [<dest>] [--platform github|azure|gitlab ...]

`qz build solution` puts an agent starter and the knowledge service (the hybrid kit) in one repository, with a compose
file and one pipeline definition written out for GitHub Actions, Azure Pipelines and GitLab CI (buildkit/solution.py).
`qz build pipeline` writes those three again after pipeline/pipeline.yaml changes (buildkit/pipeline.py).

Starts an agent project on a chosen stack with the parts teams skip: one read tool, one side-effecting tool
behind a human approval gate, hard limits in one file, tracing, an offline stub model, a gold set, CI, a runbook.

A staged stack (it has stages.json, like vectorless-rag) can start at any stage: `--stage 0` gives the stories,
tests, data and settings with nothing built, for a live build. `qz build stage <dest> <N>` then brings the project
to stage N from the tested reference, the checkpoint when a live step goes wrong; it shows its plan first and
changes files only with --yes."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from ..lanekit import record, slug
from ..util import PLUGIN_ROOT, read_json

ROOT = PLUGIN_ROOT / "templates" / "build"
TEXT = {".py", ".ts", ".js", ".json", ".jsonl", ".md", ".yml", ".yaml", ".txt", ".toml", ".cs", ".csproj", ".go", ".mod", ".gitignore", ""}
SKIP_PARTS = {"__pycache__", "bin", "obj", "node_modules", ".vrag", ".pytest_cache", "results"}
MARKER = ".qz-build.json"


def stacks() -> dict[str, dict]:
    return {p.parent.name: read_json(p) for p in sorted(ROOT.glob("*/scaffold.json"))}


def serve_step(cmd: list[str] | None) -> str:
    """The CI step that starts the HTTP interface inside the image with no network and waits for it to report healthy."""
    if not cmd:
        return ""
    args = " ".join(cmd)
    return ("      - name: The HTTP interface inside the container (no network), reported healthy by the image's own check\n"
            "        run: |\n"
            f"          cid=$(docker run -d --network none --health-interval 2s --health-timeout 5s app:ci {args})\n"
            "          for i in $(seq 1 60); do s=$(docker inspect \"$cid\" --format '{{.State.Health.Status}}'); [ \"$s\" = healthy ] && break; sleep 2; done\n"
            "          docker logs --tail 20 \"$cid\"; docker rm -f \"$cid\" > /dev/null; test \"$s\" = healthy\n")


def gateway_models(meta: dict) -> str:
    """The model_list of gateway/litellm.yaml: the gateway's model names, each on its provider, the keys read from the
    gateway's own environment, a budget on each paid one."""
    out = []
    for name, model, key, budget in (meta.get("gateway") or {}).get("models", []):
        out += [f"  - model_name: {name}", "    litellm_params:", f"      model: {model}"]
        if key:
            out.append(f"      api_key: os.environ/{key}")
        if model.startswith("ollama"):
            out.append("      api_base: os.environ/OLLAMA_API_BASE")
        if budget:
            out += [f"      max_budget: {budget}                  # USD per budget_duration; once spent, calls go to the fallback",
                    "      budget_duration: 30d"]
    return "\n".join(out)


def staging(stack: str) -> dict | None:
    p = ROOT / stack / "stages.json"
    return read_json(p) if p.exists() else None


def stage_files(stack: str, upto: int) -> dict[str, Path]:
    """Project path -> template file, for a staged stack brought to stage `upto` (overlays replace stage-0 files)."""
    src, plan = ROOT / stack, staging(stack) or {}
    files: dict[str, Path] = {}
    for p in sorted(src.rglob("*")):
        parts = p.relative_to(src).parts
        rel = p.relative_to(src).as_posix()
        if (not p.is_file() or rel in ("scaffold.json", "stages.json") or parts[0] == "_overlays"
                or SKIP_PARTS.intersection(parts)):
            continue
        if plan.get("files", {}).get(rel, 0) <= upto:
            files[rel] = p
    for n, rels in sorted(plan.get("overlays", {}).items(), key=lambda kv: int(kv[0])):
        if int(n) <= upto:
            files.update({rel: src / "_overlays" / n / rel for rel in rels})
    return files


def new(stack: str, dest: Path, name: str, module: str | None = None, kit: bool = True, stage: int | None = None) -> dict:
    all_ = stacks()
    if stack not in all_:
        raise SystemExit(f"Unknown stack '{stack}'. Choose one of: {', '.join(all_)}")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty; choose a new folder")
    meta = all_[stack]
    staged = staging(stack)
    if stage is not None and not staged:
        raise SystemExit(f"'{stack}' has no stages; leave out --stage")
    upto = int(meta.get("stages", 0)) if stage is None else stage
    if staged and not 0 <= upto <= int(meta.get("stages", 0)):
        raise SystemExit(f"'{stack}' has stages 0 to {meta.get('stages', 0)}")
    sl = slug(name)
    if meta.get("common", True):
        shutil.copytree(ROOT / "_common", dest, dirs_exist_ok=True)
    if staged:
        for rel, src in stage_files(stack, upto).items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
        (dest / MARKER).write_text(json.dumps({"stack": stack, "stage": upto}) + "\n", encoding="utf-8")
    else:
        shutil.copytree(ROOT / stack, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("scaffold.json", *SKIP_PARTS))
    subs = {
        "__NAME__": name, "__SLUG__": sl, "__MODULE__": module or f"example.com/{sl}", "__STACK_LINE__": meta["stack_line"], "__POLICY__": meta["policy"],
        "__AGENT_DIR__": meta["agent_dir"], "__TEST_CMD__": meta["test_cmd"], "__RUN_CMD__": meta["run_cmd"], "__ADAPTER__": json.dumps(meta.get("adapter", [])),
        "__PASS_ENV__": json.dumps(meta.get("pass_env", [])), "__SETUP_STEPS__": "\n".join("      " + s for s in meta.get("setup_steps", [])),
        "__SECRET_ENV__": "\n".join(f"          {k}: ${{{{ secrets.{k} }}}}" for k in meta.get("secret_env", [])),
        "__CONTAINER_CHECK__": meta.get("container_check", "docker run --rm --network none app:ci"),
        "__SERVE_STEP__": serve_step(meta.get("serve")),
        "__SERVE_JSON__": json.dumps(meta.get("serve") or []),
        "__GATEWAY_MODEL_LIST__": gateway_models(meta),
    }
    for p in dest.rglob("*"):
        if p.is_file() and (p.suffix in TEXT or p.name in ("CODEOWNERS", ".gitignore")) and p.name not in ("go.sum", "packages.lock.json"):
            t = p.read_text(encoding="utf-8")
            n = t
            for k, v in subs.items():
                n = n.replace(k, v)
            if n != t:
                p.write_text(n, encoding="utf-8")
    if not meta.get("own_readme"):
        (dest / "README.md").write_text(readme(name, meta), encoding="utf-8")
    else:
        add_house_sections(dest / "README.md", name, meta)
    standards(dest, name, meta)
    vend = None
    if kit and meta.get("kit", True):
        from ..vendor.cli import apply
        vend = apply(dest, "ci")
    return {"stack": stack, "dest": str(dest), "name": name, "kit": vend, "verified": meta["verified"], "next": meta["next"],
            "stage": upto if staged else None}


def to_stage(dest: Path, upto: int, yes: bool) -> dict:
    """Bring a staged project to stage `upto` from the tested reference. Without yes it only plans."""
    info = read_json(dest / MARKER) or {}
    stack = info.get("stack")
    if stack not in stacks() or not staging(stack):
        raise SystemExit(f"{dest} was not started with `qz build new <staged stack>`; nothing to bring forward")
    top = int(stacks()[stack].get("stages", 0))
    if not 0 <= upto <= top:
        raise SystemExit(f"'{stack}' has stages 0 to {top}")
    plan = staging(stack) or {}
    owned = set(plan.get("files", {})) | {r for rels in plan.get("overlays", {}).values() for r in rels}
    add, replace = [], []
    for rel, src in stage_files(stack, upto).items():
        out = dest / rel
        if not out.exists():
            add.append(rel)
        elif rel in owned and out.read_bytes() != src.read_bytes():
            replace.append(rel)
    if yes:
        for rel in add + replace:
            src = stage_files(stack, upto)[rel]
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
        (dest / MARKER).write_text(json.dumps({"stack": stack, "stage": max(upto, int(info.get("stage", 0)))}) + "\n",
                                   encoding="utf-8")
    return {"stack": stack, "stage": upto, "add": add, "replace": replace, "applied": yes}


def standards(dest: Path, name: str, meta: dict) -> list[str]:
    """The house standards a new project starts with: its EU AI Act record (docs/ai-act/) and, when the starter is
    tied to a vendor, that choice recorded in .qz/practices.json so open-source-first knows it was deliberate."""
    from ..auditkit import aiact
    ai = meta.get("ai_act") or {}
    r = aiact.blank(name, str(ai.get("purpose", "")).replace("__NAME__", name), bool(ai.get("people")), bool(ai.get("generates")),
                    notice=tuple(ai.get("notice") or ("", "")), marking=tuple(ai.get("marking") or ("", "")))
    r["literacy"] = "the README, the runbook and CLAUDE.md say what the system does, where it stops and who approves what"
    written = aiact.write_docs(dest, r)
    rel = dest / "docs" / "release.md"
    if not rel.exists():
        rel.parent.mkdir(parents=True, exist_ok=True)
        rel.write_text(release_recipe(name, slug(name), meta), encoding="utf-8")
        written.append("docs/release.md")
    written += shape_files(dest, name, meta)
    written += golive_files(dest, name, meta)
    if meta.get("vendors"):
        f = dest / ".qz" / "practices.json"
        cur = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        cur.setdefault("standards", {})["vendors"] = sorted(set(cur.get("standards", {}).get("vendors", [])) | set(meta["vendors"]))
        cur["standards"]["_vendors_why"] = f"chosen with the starter: {meta.get('title', 'this stack')}"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
        written.append(".qz/practices.json")
    return written


def shape_files(dest: Path, name: str, meta: dict) -> list[str]:
    """The solution's parts in .qz/solution.json (`qz structure` checks them), and .env.example: every variable the
    code reads, by name only, so nobody has to guess what a .env needs and nobody commits one."""
    from ..auditkit import shape
    out = []
    if meta.get("roles"):
        f = dest / ".qz" / "solution.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"name": name, "stack": meta.get("title", ""), "roles": meta["roles"],
                                 "_about": "The parts of this solution and where each lives (qz structure). Keep it true when the code moves."},
                                indent=2) + "\n", encoding="utf-8")
        out.append(".qz/solution.json")
    names = list(dict.fromkeys([*(meta.get("secret_env") or []), *(meta.get("pass_env") or []), *sorted(shape._env_reads(dest))]))
    if names and not (dest / ".env.example").exists():
        keys = [n for n in names if shape.KEYLIKE.search(n)]
        rest = [n for n in names if n not in keys]
        text = ["# The variables this project reads, by name only. Never put a value in this file, and never commit a .env.",
                "# Keys come from your system's keychain, the environment or the CI's secret store."]
        if keys:
            text += ["", "# Keys and secrets"] + [f"{n}=" for n in keys]
        if rest:
            text += ["", "# Settings (optional)"] + [f"# {n}=" for n in rest]
        (dest / ".env.example").write_text("\n".join(text) + "\n", encoding="utf-8")
        out.append(".env.example")
    return out


def golive_files(dest: Path, name: str, meta: dict) -> list[str]:
    """The go-live record (.qz/golive.json, `qz golive`): where each of the nine gates lives in this starter, every host
    it may call with its processor, and the questions only the client can answer, as TODOs."""
    from ..auditkit import golive
    if not meta.get("golive"):
        return []
    f = golive.write_record(dest, golive.propose(dest, {**meta["golive"], "name": name}))
    return [golive.RECORD] if f else []


def release_recipe(name: str, sl: str, m: dict) -> str:
    """How a release moves: one image per tag, three steps to everyone, and a rollback that is one switch."""
    return f"""# Release: {name}

Semantic-release tags each squash-merge to master (`vMAJOR.MINOR.PATCH`, from the squash commit's type). The image is
built once per tag, checked in CI (`{m.get('container_check', 'docker run --rm --network none app:ci')}`), and never rebuilt:
`<registry>/{sl}:<tag>`.

| Environment | How a release gets there | Who |
|---|---|---|
| dev0 | deploys automatically when a release is tagged | the pipeline |
| qa0 | a change request | a person |
| prod0 | a change request, then the three steps below; the first time, all nine go-live gates signed (`qz golive --gate`) | a person |

## Three steps to everyone

1. **Shadow.** The new tag runs beside the live one on copies of real requests; its replies are compared and never
   sent. Gate: the live gold set passes at the tool, response and outcome levels, no new kind of guard finding,
   tokens per run within a fifth of the live tag.
2. **A small share.** 5% of requests for a day, then 25%. Gate: `qz eval monitor` raises no alert at any of the three
   levels against the live tag, and no serious incident (`docs/ai-act/incident-runbook.md`).
3. **Everyone.** The monitor keeps running on a schedule; an alert is a reason to roll back.

## What is versioned

The code, the system prompt and the limits live in `{m.get('policy', 'the settings file')}`, so they ship inside the
image. The model is set per environment (`AGENT_MODEL`, or the settings file's model) and written in the release notes
beside the tag. A prompt or model change is a release like any other: the gold set runs first.

## Rollback: one switch

Point the environment back at the previous tag, with the model it ran:

- Docker: `docker run ... <registry>/{sl}:<previous tag>`
- Kubernetes: `kubectl rollout undo deployment/{sl}`
- A managed runtime (AgentCore, a PaaS): redeploy the previous image tag.

Nothing is rebuilt: the previous image is exactly what ran before. Record why in `docs/decisions/`.
"""


AGENT_COST = ("prompt caching on the fixed prefix, easy turns routed to `AGENT_MODEL_SMALL` when it is set, and capped "
              "turns, tokens and output.")


def house_sections(name: str, m: dict) -> str:
    """The two sections every project's README carries: the QualiZeal standards and how its image is released."""
    kit = m.get("kit", True)
    qz = "python3 .claude/qz/scripts/qz.py" if kit else "qz"
    lead = (f"CI checks every change against seven standards; `{qz} standards` shows the scorecard here." if kit else
            "Seven standards apply to every change: the Studio's `qz standards` shows the scorecard, and the Deliver lane "
            "runs it before a change is called done.")
    golive = f"`{qz} golive`" if kit else "`qz golive`"
    evals = ("`" + qz + " eval run` scores the gold set and `" + qz + " eval monitor` scores live traffic from the audit log"
             if kit else m.get("eval_line") or "the kit's own eval gate scores the golden set, and its audit log is read at the same levels")
    ai = m.get("ai_act") or {}
    marks = [x for x, on in (("`ai_notice` (show it before the first reply)", ai.get("people")),
                             ("`ai_generated` (a machine-readable mark)", ai.get("generates"))) if on]
    act = (f"Every result carries {' and '.join(marks)}." if marks else
           "No person talks to it and it makes no content of its own, so Article 50 asks nothing of it; the record says why.")
    check = m.get("container_check", "docker run --rm --network none app:ci")
    staged = f" A staged project builds it from stage {m['stages']}, once every stage is in." if m.get("stages") else ""
    served = (" It also starts the HTTP interface inside the image with no network, and waits for the image's own health check "
              "to report it healthy." if m.get("serve") else "")
    return f"""## QualiZeal standards

{lead}

- **Six guardrails:** input filter, output filter, tool allowlist, human approval, step limits and sandboxed execution.
- **EU AI Act:** the record in `docs/ai-act/` gives the risk class, the role and the obligations. {act} The class is a draft until a person confirms it: `{qz} aiact confirm --yes`.
- **Open source first:** {m.get('open_line', 'open-source options first at every layer.')}
- **Cost levers:** {m.get('cost_line', AGENT_COST)}
- **Solution shape:** the fourteen parts every solution has, each named in `.qz/solution.json` where it lives or why it does not apply (`{qz} structure`); `.env.example` names every variable the code reads, with no values.
- **Go-live readiness:** the nine gates an enterprise checks before go-live (single sign-on, roles, data residency, personal data, audit log, network isolation, vendor review, data processing terms, penetration test). The code carries each control, named in `.qz/golive.json`; a named person signs each gate off before production: {golive}.
- **Agent evals:** every case is checked at three levels: tool (the right tool, arguments and order), response (one reply, grounded in what the tools returned) and outcome (what the session changed and how it ended). Each level has a floor and at least three cases; {evals}, and CI proves the log carries all three.

## Container and release

`docker build -t {slug(name)} .` builds the image.{staged} CI builds it on every push and runs `{check}`, with no network and no key.{served}

`docs/release.md` is the recipe: one image per release tag, shadow, a small share, then everyone, and a rollback that is one switch.

"""


def add_house_sections(path: Path, name: str, m: dict) -> None:
    """A kit with its own README gets the same two sections, before its production notes."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if "## QualiZeal standards" in text:
        return
    block = house_sections(name, m)
    at = text.find("\n## Before ")
    text = text.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n" if at < 0 else text[:at + 1] + block + text[at + 1:]
    path.write_text(text, encoding="utf-8")


def serve_section(m: dict) -> str:
    """How to serve an agent starter over HTTP and answer what waits, for a starter with an interface."""
    if not m.get("serve_cmd"):
        return ""
    return f"""## Serve it

`{m['serve_cmd']}` serves the agent on http://127.0.0.1:8080. On a laptop it runs with demo identities: name one in the
`X-Demo-User` header (sam asks, ana asks and approves, vic may only look orders up). Demo identities are refused when
`APP_ENV` says production.

- `POST /ask` with `{{"message": "..."}}`: the result. A refund waits for a person: 202, with its `thread_id`.
- `GET /runs/<thread>`: how the run stands and what waits, for the person who asked or an approver.
- `POST /runs/<thread>/approve` or `/decline`: an approver's answer. Nobody approves their own request; a second answer gets 409.
- `GET /health`: no sign-in.

A run that waits is kept in the state database (`AGENT_STATE_DB`, default `.agent/state.db`), so a restart or a deploy
loses nothing, and any instance can answer it; `{m['answer_cmd']}` answers one from the command line. Each change a tool
makes is made once: a retry after a crash returns the first result, and the same key goes to the system that makes the
change. Before anyone else can reach the interface, set `AGENT_IDENTITY=oidc` with `AGENT_OIDC_ISSUER`,
`AGENT_OIDC_AUDIENCE` and `AGENT_OIDC_JWKS_URL` (or `proxy` behind an identity-aware proxy, with
`AGENT_TRUSTED_PROXIES`), and map your groups to roles in `{m['policy']}`.

"""


def gateway_section(m: dict) -> str:
    """The model gateway option, for an agent starter that has one."""
    if not (m.get("gateway") or {}).get("models"):
        return ""
    return """## Model gateway and traces

`AGENT_GATEWAY=litellm` sends every model call through a LiteLLM proxy (`gateway/litellm.yaml`): the provider keys,
fallbacks between providers and budgets live there, and the agent holds only `AGENT_GATEWAY_KEY`. Traces go to
Langfuse over OpenTelemetry, the gateway's record of each call inside the run's trace, with no prompt or answer text
unless the team turns it on. `docker compose -f gateway/compose.yaml up --build` runs both on a laptop;
`gateway/README.md` says what each setting does, and `evals/eval.gateway.json` runs the gold set through the gateway.

"""


def readme(name: str, m: dict) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(m["next"], 1))
    durable = ("\n- Durable runs and an HTTP interface: a run that waits for a person is kept in SQLite and finished from any "
               "process or over the API; each change a tool makes is made once; temporary errors are retried and permanent ones stop."
               if m.get("serve_cmd") else "")
    return f"""# {name}

{m['stack_line']} Started from the QualiZeal agent scaffold: {m['summary']}

## What is here

- One read-only tool and one tool that moves money, which waits for a person's approval.
- Limits in one file: `{m['policy']}` (model, turn limit, token cap, approval list).
- An offline stub model, so tests and the gold set run with no key and no spend.
- A gold set of 16 cases in `evals/gold.jsonl`, each checked at the tool, response and outcome levels: lookups, the approval gate, a made-up tracking number, injection attempts, the input filter, a refund approved from a new process after a restart, and a crash right after the refund that still refunds once. `evals/monitor.json` scores live traffic at the same three levels.{durable}
- Tracing with OpenTelemetry, a CI workflow, a runbook and rules for coding agents (`CLAUDE.md`).

{house_sections(name, m)}## Run it

Offline: `{m['run_cmd']}`

Tests: `{m['test_cmd']}`

Gold set: `python3 .claude/qz/scripts/qz.py eval run` (writes `evals/results/report.html`)

Live: {m['live']} Then `python3 .claude/qz/scripts/qz.py eval run --config evals/eval.live.json`.

{serve_section(m)}{gateway_section(m)}## What was checked before you got this

{m['verified']}

The stub follows fixed rules. A green offline run proves the wiring (tools, approval, limits, checks); it says nothing about how a model answers. Measure that with the live gold set.

## First changes to make

{steps}

## Before it goes anywhere near production

Run the Architect lane (`/qz-aidlc:qz-architect`) for requirements, the option decision, feasibility and diagrams, and the project audit (`python3 .claude/qz/scripts/qz.py audit-project scan`). The sample data and the demo identities are placeholders, and one SQLite state database serves one machine: several instances share Postgres instead (the same two tables).
"""


def main(name: str, rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    x = sub.add_parser("new"); x.add_argument("stack"); x.add_argument("dest"); x.add_argument("--name", default=""); x.add_argument("--module"); x.add_argument("--no-kit", action="store_true")
    x.add_argument("--stage", type=int)
    st = sub.add_parser("stage"); st.add_argument("dest"); st.add_argument("stage", type=int); st.add_argument("--yes", action="store_true")
    sub.add_parser("solution", add_help=False)
    pl = sub.add_parser("pipeline"); pl.add_argument("dest", nargs="?", default="."); pl.add_argument("--platform", action="append", choices=["github", "azure", "gitlab"])
    if rest[:1] == ["solution"]:
        from .solution import main as solution_main
        solution_main(rest[1:])
        return
    a = ap.parse_args(rest)
    if a.cmd == "pipeline":
        from . import pipeline
        dest = Path(a.dest).resolve()
        for rel in pipeline.render(dest, pipeline.read_spec(dest), a.platform or pipeline.PLATFORMS):
            print(f"  wrote {rel}")
        return
    if a.cmd == "list":
        for k, m in stacks().items():
            staged = f" Stages 0 to {m['stages']}." if m.get("stages") else ""
            print(f"{k}\n    {m['title']}: {m['summary']}{staged}\n    Checked: {m['verified']}")
        return
    if a.cmd == "stage":
        r = to_stage(Path(a.dest).resolve(), a.stage, a.yes)
        verb = ("Added", "Replaced") if r["applied"] else ("Would add", "Would replace")
        print(f"{r['stack']} to stage {r['stage']}: {len(r['add'])} to add, {len(r['replace'])} to replace with the reference.")
        for f in r["add"]:
            print(f"  {verb[0]}  {f}")
        for f in r["replace"]:
            print(f"  {verb[1]}  {f}  (your version is overwritten; qz undo can bring it back)")
        if not r["applied"] and (r["add"] or r["replace"]):
            print("Run again with --yes to apply.")
        return
    dest = Path(a.dest).resolve()
    r = new(a.stack, dest, a.name or dest.name.replace("-", " ").title(), a.module, not a.no_kit, a.stage)
    stage_note = f", stage {r['stage']}" if r["stage"] is not None else ""
    print(f"Created {r['dest']} ({r['stack']}{stage_note}).")
    if r["kit"]:
        print(f"  Engineering kit vendored to .claude/qz/ ({r['kit']['files']} files) so CI and cloud sessions can run evals and the audit.")
    print(f"  Checked: {r['verified']}")
    print("  Next:")
    for s in r["next"]:
        print("    - " + s)
    record("agent-scaffold", str(dest), "scaffold", stack=a.stack)
