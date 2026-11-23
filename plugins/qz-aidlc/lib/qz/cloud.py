"""qz cloud: the client's cloud, layer by layer, and OpenTofu files that put a starter on it.

  qz cloud list
      The clouds, and what each template runs the project on.
  qz cloud show <azure|aws|gcp|kubernetes> [--json]
      For each layer (models, gateway, search, document parsing, identity, secrets, tracing, containers): the cloud's
      own service, the open option beside it, its sources and the day it was checked. Then the AI gateway as one pattern.
  qz cloud check [--today YYYY-MM-DD] [--max-age 90]
      Every fact older than the limit, with its source to check it at. Exits 1 when there is one.
  qz cloud add <cloud> [--project DIR] [--stack STACK] [--geo us|eu|global] [--force]
      Writes cloud/<cloud>/ into a starter project: OpenTofu files (Terraform-compatible) for its shape (an HTTP
      service or a job), with Claude through the cloud's own model service and the cloud's open-weight model behind the
      same gateway, the keys named in the cloud's secret store (never their values), tests that plan it with no cloud
      account, and a README of what a person does before the first apply. Nothing is applied, here or in CI.
  qz cloud lint [DIR]
      The checks CI runs on the templates (the Studio's, or a project's cloud/ folder): no resource that would hold a
      key's value, every gateway key read from the environment, and on Kubernetes SIE with its telemetry off and its
      gateway and workers behind tokens. Exits 1 on a finding."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import shutil
import sys
from pathlib import Path

from .util import PLUGIN_ROOT

ROOT = PLUGIN_ROOT / "templates" / "cloud"
FACTS = ROOT / "clouds.json"
CLOUDS = ("azure", "aws", "gcp", "kubernetes")
GEOS = ("us", "eu", "global")

# The user each starter's image runs as: the pod or task runs as that number, so "not root" can be checked.
UIDS = {"claude-agent-sdk-ts": 1000, "go-anthropic": 65532, "maf-dotnet": 1654}
DEFAULT_UID = 10001
# The two RAG kits answer HTTP on their own port; every other starter without a serve command runs to completion.
RAG_SERVICE = {"advanced-rag": (8765, "/api/health"), "vectorless-rag": (8765, "/api/health")}

# Each starter names its models by role; each cloud maps a role to its own model service. Claude comes through the
# cloud's model service, the open-weight model is the cloud's too, and the gateway holds whatever credential it needs.
MODELS = {
    "aws": {
        "claude": ("bedrock/converse/{geo}.anthropic.claude-sonnet-5-5", {"aws_region_name": "os.environ/AWS_REGION"}),
        "claude-small": ("bedrock/converse/{geo}.anthropic.claude-haiku-5-5", {"aws_region_name": "os.environ/AWS_REGION"}),
        "open": ("bedrock/converse/openai.gpt-oss-120b-1:0", {"aws_region_name": "os.environ/AWS_REGION"}),
    },
    "azure": {
        "claude": ("azure_ai/claude-sonnet-5-5", {"api_base": "os.environ/AZURE_AI_API_BASE", "api_key": "os.environ/AZURE_AI_API_KEY"}),
        "claude-small": ("azure_ai/claude-haiku-5-5", {"api_base": "os.environ/AZURE_AI_API_BASE", "api_key": "os.environ/AZURE_AI_API_KEY"}),
        "open": ("openai/gpt-oss-120b", {"api_base": "os.environ/AZURE_OPENAI_V1_BASE", "api_key": "os.environ/AZURE_AI_API_KEY"}),
    },
    "gcp": {
        "claude": ("vertex_ai/claude-sonnet-5-5", {"vertex_project": "os.environ/GOOGLE_CLOUD_PROJECT", "vertex_location": "os.environ/VERTEX_LOCATION"}),
        "claude-small": ("vertex_ai/claude-haiku-5-5", {"vertex_project": "os.environ/GOOGLE_CLOUD_PROJECT", "vertex_location": "os.environ/VERTEX_LOCATION"}),
        "open": ("vertex_ai/openai/gpt-oss-120b-maas", {"vertex_project": "os.environ/GOOGLE_CLOUD_PROJECT", "vertex_location": "global"}),
    },
    "kubernetes": {
        "claude": ("anthropic/claude-sonnet-5-5", {"api_key": "os.environ/ANTHROPIC_API_KEY"}),
        "claude-small": ("anthropic/claude-haiku-5-5", {"api_key": "os.environ/ANTHROPIC_API_KEY"}),
        "open": ("openai/qwen3.8-27b", {"api_base": "os.environ/SIE_API_BASE", "api_key": "os.environ/SIE_AUTH_TOKEN"}),
    },
}

# Resource types that would put a key's value into the plan and the state. The templates name keys; people set them.
VALUE_HOLDERS = ("aws_secretsmanager_secret_version", "azurerm_key_vault_secret", "google_secret_manager_secret_version",
                 "kubernetes_secret", "kubernetes_secret_v1", "random_password")
VALUE_ATTRS = ("set_sensitive", "set_wo", "secret_string", "secret_data")

# SIE's chart settings that are unsafe at their default before 0.13.0, and the value the template must hold.
SIE_SAFE = {("telemetry", "enabled"): False, ("gateway", "auth", "mode"): ("token", "static"),
            ("workers", "auth", "enabled"): True, ("workers", "networkPolicy", "enabled"): True}


def facts() -> dict:
    return json.loads(FACTS.read_text(encoding="utf-8"))


# --- show and check ----------------------------------------------------------------------------------------------------
def show(cloud: str, as_json: bool = False) -> str:
    f = facts()
    if cloud not in f["clouds"]:
        raise SystemExit(f"Unknown cloud '{cloud}'. Choose one of: {', '.join(f['clouds'])}")
    c = f["clouds"][cloud]
    if as_json:
        return json.dumps({"cloud": cloud, **c, "gateway_pattern": f["gateway_pattern"]}, indent=2)
    out = [f"{c['name']}: {c['template']}.", ""]
    for key, title in f["layers"].items():
        fact = c["layers"][key]
        out += [f"{title}", f"  On {c['name']}: {fact['service']}", f"  Open option: {fact['open']}",
                f"  Checked {fact['checked']}: " + " ; ".join(fact["sources"]), ""]
    out += ["The AI gateway, the same on every cloud:"] + [f"  - {line}" for line in f["gateway_pattern"]]
    return "\n".join(out)


def stale(today: _dt.date | None = None, max_age: int | None = None) -> list[dict]:
    """Every fact older than max_age days on `today`, oldest first. A fact dated after today (a time zone ahead) counts as fresh."""
    f = facts()
    today = today or _dt.date.today()
    limit = int(max_age if max_age is not None else f.get("max_age_days", 90))
    rows = []
    for cloud, c in f["clouds"].items():
        for layer, fact in c["layers"].items():
            rows.append((cloud, layer, fact))
    rows.append(("kubernetes", "sie chart", f["sie"]))
    old = []
    for cloud, layer, fact in rows:
        age = (today - _dt.date.fromisoformat(fact["checked"])).days
        if age > limit:
            old.append({"cloud": cloud, "layer": layer, "checked": fact["checked"], "age_days": age, "sources": fact["sources"]})
    return sorted(old, key=lambda r: -r["age_days"])


# --- add ---------------------------------------------------------------------------------------------------------------
def detect_stack(project: Path) -> str:
    from .buildkit.cli import stacks
    sol = project / ".qz" / "solution.json"
    if sol.is_file():
        title = json.loads(sol.read_text(encoding="utf-8")).get("stack", "")
        for key, meta in stacks().items():
            if meta.get("title") == title:
                return key
    raise SystemExit(f"{project} does not look like a starter project (no .qz/solution.json naming its stack); pass --stack")


def starter_shape(stack: str, meta: dict, name: str) -> dict:
    from .lanekit import slug
    if meta.get("serve"):
        shape, port, health, args = "service", 8080, "/health", list(meta["serve"])
    elif stack in RAG_SERVICE:
        (port, health), shape, args = RAG_SERVICE[stack], "service", []
    else:
        shape, port, health, args = "job", 0, "", []
    roles = sorted({role(m) for _n, m, _k, _b in (meta.get("gateway") or {}).get("models", [])})
    return {"slug": slug(name, 40), "shape": shape, "port": port, "health": health, "args": args,
            "gateway": bool(roles), "uid": UIDS.get(stack, DEFAULT_UID), "models": roles}


def role(model: str) -> str:
    if model.startswith("anthropic/") and "haiku" in model:
        return "claude-small"
    if model.startswith("anthropic/"):
        return "claude"
    return "open"


def gateway_config(cloud: str, meta: dict, geo: str) -> str:
    """The gateway's model list for this cloud, from the starter's own model names: the same names the agent asks for."""
    lines = []
    for name, model, _key, budget in (meta.get("gateway") or {}).get("models", []):
        target, params = MODELS[cloud][role(model)]
        lines += [f"  - model_name: {name}", "    litellm_params:", f"      model: {target.format(geo=geo)}"]
        lines += [f"      {k}: {v}" for k, v in params.items()]
        if budget:
            lines += [f"      max_budget: {budget}                  # USD per budget_duration; once spent, calls go to the fallback",
                      "      budget_duration: 30d"]
    return "\n".join(lines)


CREDENTIAL = {"aws": "the task's IAM role (no key)", "gcp": "the service account (no key)",
              "azure": "the Foundry resource's key, from Key Vault", "kubernetes": None}


def model_table(cloud: str, meta: dict, geo: str) -> str:
    """The README's table: each name the agent asks for, where the gateway sends it on this cloud, and with what."""
    rows = ["| The agent asks for | The gateway calls | With |", "|---|---|---|"]
    for name, model, _key, budget in (meta.get("gateway") or {}).get("models", []):
        r = role(model)
        target = MODELS[cloud][r][0].format(geo=geo)
        cred = CREDENTIAL[cloud] or ("SIE's token, from the secret store" if r == "open" else "the Claude API key, from the secret store")
        cap = f"; budget {budget} USD a month" if budget else ""
        rows.append(f"| `{name}` | `{target}` | {cred}{cap} |")
    return "\n".join(rows)


def starter_tf(s: dict, geo: str = "us") -> str:
    args = json.dumps(s["args"])
    models = json.dumps(s["models"])
    return f"""# What the cloud templates need to know about this project. `qz cloud add` wrote it from the starter's scaffold;
# change it here if the project's shape changes (and run `tofu test` again).
locals {{
  starter = {{
    slug    = "{s['slug']}"
    shape   = "{s['shape']}"   # service: it answers HTTP; job: it runs to completion
    port    = {s['port']}
    health  = "{s['health']}"
    args    = {args}
    gateway = {str(s['gateway']).lower()}   # every model call goes through the gateway beside it
    uid     = {s['uid']}   # the user the image runs as
    models  = {models}   # the kinds of model the gateway calls: claude, claude-small, open
    geo     = "{geo}"   # on AWS, the Bedrock inference profile the gateway calls Claude through (us, eu or global)
  }}
}}
"""


def fill(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def tests_tf(cloud: str, s: dict) -> str:
    """The plan test for this project: shared lines, then the asserts for its shape, from tests/*.tftest.hcl.in."""
    src = (ROOT / cloud / "tests" / "plan.tftest.hcl.in").read_text(encoding="utf-8")
    keep = {"service": s["shape"] == "service", "job": s["shape"] == "job", "gateway": s["gateway"], "nogateway": not s["gateway"],
            "claude": "claude" in s["models"], "noclaude": "claude" not in s["models"]}
    out, on = [], [True]
    for line in src.splitlines():
        m = re.match(r"\s*#\s*@(if|end)\s*(\w*)", line)
        if m and m.group(1) == "if":
            on.append(on[-1] and keep[m.group(2)])
            continue
        if m and m.group(1) == "end":
            on.pop()
            continue
        if on[-1]:
            out.append(line)
    return fill("\n".join(out) + "\n", {"__SLUG__": s["slug"]})


def add(cloud: str, project: Path, stack: str | None = None, geo: str = "us", force: bool = False) -> dict:
    from .buildkit.cli import stacks
    if cloud not in CLOUDS:
        raise SystemExit(f"Unknown cloud '{cloud}'. Choose one of: {', '.join(CLOUDS)}")
    if geo not in GEOS:
        raise SystemExit(f"--geo is one of {', '.join(GEOS)}")
    project = project.resolve()
    stack = stack or detect_stack(project)
    meta = stacks().get(stack)
    if not meta:
        raise SystemExit(f"Unknown stack '{stack}'")
    sol = project / ".qz" / "solution.json"
    name = json.loads(sol.read_text(encoding="utf-8")).get("name", project.name) if sol.is_file() else project.name
    s = starter_shape(stack, meta, name)
    dest = project / "cloud" / cloud
    if dest.exists() and any(dest.iterdir()) and not force:
        raise SystemExit(f"{dest} already exists; pass --force to write it again (your changes there would be lost)")
    src = ROOT / cloud
    shutil.copytree(src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.in", "README.md", "gateway", "__pycache__"))
    (dest / "starter.tf").write_text(starter_tf(s, geo), encoding="utf-8")
    (dest / "tests").mkdir(exist_ok=True)
    (dest / "tests" / "plan.tftest.hcl").write_text(tests_tf(cloud, s), encoding="utf-8")
    written = sorted(p.relative_to(project).as_posix() for p in dest.rglob("*")
                     if p.is_file() and ".terraform" not in p.parts and p.name != ".terraform.lock.hcl")
    subs = {"__NAME__": name, "__SLUG__": s["slug"], "__SHAPE__": shape_line(s), "__GEO__": geo,
            "__STACK__": meta.get("title", stack), "__MODEL_TABLE__": model_table(cloud, meta, geo) if s["gateway"] else ""}
    if s["gateway"]:
        g = dest / "gateway"
        g.mkdir(exist_ok=True)
        common = (ROOT / "_gateway" / "litellm.yaml.in").read_text(encoding="utf-8")
        (g / "litellm.yaml").write_text(fill(common, {**subs, "__CLOUD__": cloud, "__MODEL_LIST__": gateway_config(cloud, meta, geo)}),
                                        encoding="utf-8")
        shutil.copy2(ROOT / "_gateway" / "Dockerfile", g / "Dockerfile")
        written += [f"cloud/{cloud}/gateway/litellm.yaml", f"cloud/{cloud}/gateway/Dockerfile"]
    readme = fill((src / "README.md").read_text(encoding="utf-8"), subs)
    readme = keep_sections(readme, {"gateway": s["gateway"], "nogateway": not s["gateway"], "service": s["shape"] == "service",
                                    "job": s["shape"] == "job"})
    (dest / "README.md").write_text(readme, encoding="utf-8")
    written.append(f"cloud/{cloud}/README.md")
    return {"cloud": cloud, "stack": stack, "shape": s, "dest": str(dest), "files": sorted(set(written))}


def shape_line(s: dict) -> str:
    if s["shape"] == "service":
        side = " with the model gateway beside it" if s["gateway"] else ""
        return f"an HTTP service on port {s['port']} (health at {s['health']}){side}"
    return "a job that runs to completion when someone starts it"


def keep_sections(text: str, keep: dict) -> str:
    """Drop the <!-- @if X --> ... <!-- @end --> parts of a README that do not apply to this project."""
    out, on = [], [True]
    for line in text.splitlines():
        m = re.match(r"\s*<!--\s*@(if|end)\s*(\w*)\s*-->", line)
        if m and m.group(1) == "if":
            on.append(on[-1] and keep[m.group(2)])
            continue
        if m and m.group(1) == "end":
            on.pop()
            continue
        if on[-1]:
            out.append(line)
    return "\n".join(out) + "\n"


# --- lint --------------------------------------------------------------------------------------------------------------
def _get(d, path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def lint(target: Path) -> list[str]:
    """Findings for a templates folder (the Studio's templates/cloud) or a project's cloud/ folder."""
    findings = []
    for tf in sorted(target.rglob("*.tf")):
        text = tf.read_text(encoding="utf-8")
        code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        for bad in VALUE_HOLDERS:
            if re.search(r'resource\s+"' + re.escape(bad) + r'"', code):
                findings.append(f"{tf.relative_to(target)}: {bad} would put a key's value in the plan and the state; name the key and let a person set it")
        for bad in VALUE_ATTRS:
            if re.search(r"^\s*" + re.escape(bad) + r"\s*=", code, re.M):
                findings.append(f"{tf.relative_to(target)}: {bad} would put a key's value in the plan and the state; name the key and let a person set it")
    for y in sorted(target.rglob("litellm.yaml*")):
        for n, line in enumerate(y.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*(api_key|master_key|aws_secret_access_key|vertex_credentials)\s*:\s*(\S+)", line)
            if m and not m.group(2).startswith("os.environ/"):
                findings.append(f"{y.relative_to(target)}:{n}: {m.group(1)} must be read from the gateway's environment (os.environ/...), not written in the file")
    for vals in sorted(target.rglob("sie-values.yaml")):
        findings += sie_findings(vals, target)
    sie_tf = [p for p in target.rglob("sie.tf")]
    for p in sie_tf:
        t = p.read_text(encoding="utf-8")
        if 'file("${path.module}/sie-values.yaml")' not in t:
            findings.append(f"{p.relative_to(target)}: SIE's chart must take its values from sie-values.yaml, where telemetry is off and both tokens are on")
        if re.search(r"^\s*set(_list)?\s*=", t, re.M):
            findings.append(f"{p.relative_to(target)}: no set or set_list on SIE's release: they could turn telemetry or authentication back to the default")
    return findings


def sie_findings(path: Path, root: Path) -> list[str]:
    try:
        import yaml
    except ImportError:  # pragma: no cover - the Studio's CI installs PyYAML
        return [f"{path.relative_to(root)}: PyYAML is needed to check SIE's values"]
    v = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for key, want in SIE_SAFE.items():
        got = _get(v, key)
        ok = got in want if isinstance(want, tuple) else got is want
        if not ok:
            out.append(f"{path.relative_to(root)}: {'.'.join(key)} is {got!r}; SIE's default before 0.13.0 is unsafe, set it to {want!r}")
    if not _get(v, ("gateway", "auth", "tokenSecretName")):
        out.append(f"{path.relative_to(root)}: gateway.auth.tokenSecretName is empty; the gateway token comes from the cloud's secret store")
    return out


# --- the command -------------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qz cloud", description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    s = sp.add_parser("show"); s.add_argument("cloud"); s.add_argument("--json", action="store_true")
    c = sp.add_parser("check"); c.add_argument("--today"); c.add_argument("--max-age", type=int)
    a = sp.add_parser("add"); a.add_argument("cloud"); a.add_argument("--project", default="."); a.add_argument("--stack")
    a.add_argument("--geo", default="us", choices=GEOS); a.add_argument("--force", action="store_true")
    li = sp.add_parser("lint"); li.add_argument("dir", nargs="?", default="")
    a_ = ap.parse_args(argv)
    if a_.cmd == "list":
        for k, c_ in facts()["clouds"].items():
            print(f"{k}\n    {c_['name']}: {c_['template']}")
        return 0
    if a_.cmd == "show":
        print(show(a_.cloud, a_.json))
        return 0
    if a_.cmd == "check":
        today = _dt.date.fromisoformat(a_.today) if a_.today else None
        old = stale(today, a_.max_age)
        limit = a_.max_age if a_.max_age is not None else facts().get("max_age_days", 90)
        if not old:
            print(f"Every cloud fact was checked within {limit} days.")
            return 0
        print(f"{len(old)} cloud fact(s) older than {limit} days: check each at its source, then change its text and date in templates/cloud/clouds.json.")
        for r in old:
            print(f"  {r['cloud']} / {r['layer']}: checked {r['checked']} ({r['age_days']} days ago): {r['sources'][0]}")
        return 1
    if a_.cmd == "add":
        r = add(a_.cloud, Path(a_.project), a_.stack, a_.geo, a_.force)
        print(f"Wrote {len(r['files'])} files for {r['cloud']} ({r['stack']}: {shape_line(r['shape'])}):")
        for f in r["files"]:
            print(f"  {f}")
        print(f"  Next: cloud/{r['cloud']}/README.md says what a person does before the first apply. Nothing was applied.")
        return 0
    target = Path(a_.dir) if a_.dir else ROOT
    found = lint(target)
    for f in found:
        print(f)
    print(f"{len(found)} finding(s) in {target}." if found else f"No findings in {target}.")
    return 1 if found else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
