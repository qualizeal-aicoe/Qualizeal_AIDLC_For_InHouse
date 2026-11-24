"""One pipeline definition, three platforms: pipeline/pipeline.yaml becomes GitHub Actions (.github/workflows/ci.yml and
deploy.yml), Azure Pipelines (azure-pipelines.yml) and GitLab CI (.gitlab-ci.yml). Edit the definition, then
`qz build pipeline` writes the three again; never edit the rendered files by hand.

Every platform gets the same order: build, test, the evaluation gates, the test lane's acceptance cases against the
running solution, the scans, the container images and the checks inside them, then a staged deploy. Staging follows a green main branch on its own; production waits for a person:
on GitHub a person starts the deploy workflow (and the production environment's reviewers, where the team has set
them, apply too), on Azure a manual validation holds the run, on GitLab a manual job does. scripts/deploy.sh deploys
nothing until DEPLOY_COMMAND is set, so the whole pipeline runs with no cloud account.

Steps are shell commands, the same on every platform. A step marked `pull_request: true` runs only for a pull or merge
request, and `{base}` in it is the branch the request goes into. Only the GitHub workflow is run end to end by the
Studio's CI; the Azure and GitLab files are checked against their platforms' schemas."""
from __future__ import annotations

import json
import re
from pathlib import Path

UV = "0.11.32"
PLATFORMS = ("github", "azure", "gitlab")
FILES = {"github": [".github/workflows/ci.yml", ".github/workflows/deploy.yml"], "azure": ["azure-pipelines.yml"], "gitlab": [".gitlab-ci.yml"]}
HEADER = "# Written by `qz build pipeline` from pipeline/pipeline.yaml. Edit that file and run it again; do not edit this one.\n"


# --- a small YAML writer: block style, quoting only where a plain scalar could be misread -------------------------

_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "~", "y", "n"}


def _scalar(v) -> str:
    if v is True or v is False:
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    plain = (s and s == s.strip() and s.lower() not in _RESERVED and not re.fullmatch(r"[-+]?[0-9][0-9_.:eE+-]*", s)
             and s[0] not in "!&*-?{}[],#|>@`\"'%=" and ": " not in s and " #" not in s and not s.endswith(":") and "\t" not in s)
    if plain:
        return s
    return json.dumps(s, ensure_ascii=False)


def dump(obj, indent: int = 0) -> str:
    pad = " " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = _scalar(k) if str(k) != "on" else "on"
            if isinstance(v, str) and "\n" in v:
                out.append(f"{pad}{key}: |")
                out += [f"{pad}  {line}" if line else "" for line in v.rstrip("\n").split("\n")]
            elif isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key}:")
                out.append(dump(v, indent + 2))
            elif isinstance(v, dict):
                out.append(f"{pad}{key}: {{}}")
            elif isinstance(v, list):
                out.append(f"{pad}{key}: []")
            else:
                out.append(f"{pad}{key}: {_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item:
                body = dump(item, indent + 2).split("\n")
                out.append(f"{pad}- {body[0][indent + 2:]}")
                out += body[1:]
            elif isinstance(item, list) and item:
                out.append(f"{pad}-")
                out.append(dump(item, indent + 2))
            elif isinstance(item, str) and "\n" in item:
                out.append(f"{pad}- |")
                out += [f"{pad}  {line}" if line else "" for line in item.rstrip("\n").split("\n")]
            else:
                out.append(f"{pad}- {_scalar(item)}")
    return "\n".join(out)


# --- the definition ----------------------------------------------------------------------------------------------

def spec(name: str, meta: dict, go_version: str = "") -> dict:
    """The pipeline for a solution on this stack: what a team edits in pipeline/pipeline.yaml."""
    title = meta.get("title", "")
    tools = ["python", "uv"]
    if any("setup-python" in s for s in meta.get("setup_steps", [])):
        tools.append("pip")                              # the starter installs with pip into its own Python, not uv
    if any("setup-node" in s for s in meta.get("setup_steps", [])):
        tools.append("node")
    if any("setup-go" in s for s in meta.get("setup_steps", [])):
        tools.append("go")
    if any("setup-dotnet" in s for s in meta.get("setup_steps", [])):
        tools.append("dotnet")
    build = [s.split("run:", 1)[1].strip() for s in meta.get("setup_steps", []) if s.strip().startswith("- run:")]
    qz = "python3 .claude/qz/scripts/qz.py"
    serve = " ".join(meta.get("serve") or [])
    container = [{"name": "Build the agent's image", "run": "docker build -t app:ci ."},
                 {"name": "The agent's gold set inside its image (offline, no key)", "run": meta.get("container_check", "docker run --rm --network none app:ci")}]
    if serve:
        container.append({"name": "The agent's HTTP interface inside its image (no network), reported healthy by the image's own check",
                          "run": ("cid=$(docker run -d --network none --health-interval 2s --health-timeout 5s app:ci " + serve + ")\n"
                                  "for i in $(seq 1 60); do s=$(docker inspect \"$cid\" --format '{{.State.Health.Status}}'); [ \"$s\" = healthy ] && break; sleep 2; done\n"
                                  "docker logs --tail 20 \"$cid\"; docker rm -f \"$cid\" > /dev/null; test \"$s\" = healthy")})
    container += [{"name": "Build the knowledge service's image (documents indexed inside it)", "run": "docker build -t knowledge:ci knowledge"},
                  {"name": "The knowledge gate inside its image (offline)", "run": "docker run --rm --network none knowledge:ci uv run -m arag eval --gate"}]
    return {
        "name": name,
        "about": f"{name}: an agent ({title}) with the knowledge service beside it. `qz build pipeline` turns this file into "
                 "GitHub Actions, Azure Pipelines and GitLab CI.",
        "tools": tools,
        "versions": {"python": "3.12", "uv": UV, "node": "22", "go": go_version or "1.25", "dotnet": "10.0.x"},
        "stages": [
            {"id": "build", "steps": [{"name": "The agent's dependencies", "run": b} for b in build]
                                    + [{"name": "The knowledge service's dependencies", "run": "cd knowledge && uv sync --locked"}]},
            {"id": "test", "steps": [{"name": "The agent's unit tests", "run": meta["test_cmd"]},
                                     {"name": "The knowledge service's tests (offline models, no download)", "run": "cd knowledge && uv run -m pytest -q tests"}]},
            {"id": "evaluate", "steps": [
                {"name": "The agent's gold set against the offline stub (tool, response and outcome levels; no key, no spend)", "run": f"{qz} eval run --label ci"},
                {"name": "Live monitoring wiring: the audit lines the gold set wrote, scored at the same three levels",
                 "run": f"{qz} eval monitor --log .agent/eval-audit.jsonl --min-runs 1 --require-signal"},
                {"name": "The knowledge gate: the golden questions, who may read what, and hybrid at least as good as words alone",
                 "run": "cd knowledge && uv run -m arag ingest && uv run -m arag eval --gate && uv run -m arag compare --gate"},
                {"name": "The agent and the knowledge service together: answers with their sources, and each role reads only its own",
                 "run": f"bash scripts/knowledge.sh start\ntrap 'bash scripts/knowledge.sh stop' EXIT\n{qz} eval run --config evals/eval.knowledge.json --label knowledge"}]},
            {"id": "accept", "steps": [
                {"name": "The test design: every acceptance criterion covered, a negative or boundary case for each", "run": f"{qz} test check"},
                {"name": "The test lane's automated cases against the running solution, over its HTTP interface",
                 "run": "bash scripts/knowledge.sh start\ntrap 'bash scripts/agent.sh stop; bash scripts/knowledge.sh stop' EXIT\n"
                        "bash scripts/agent.sh start\npython3 tests/acceptance/run.py --junit reports/acceptance.xml"}]},
            {"id": "scan", "steps": [
                {"name": "Agentic project audit", "run": f"{qz} audit-project scan"},
                {"name": "QualiZeal standards (six guardrails, EU AI Act, open source first, cost levers, solution shape, go-live readiness, agent evals)",
                 "run": f"{qz} standards --gate"},
                {"name": "Team decisions (docs/decisions/) against this request", "run": f"{qz} decisions check --base origin/{{base}} --ci", "pull_request": True},
                {"name": "Conventions (branch name, request title, the squash commit and its release)",
                 "run": f"{qz} conventions check --base origin/{{base}} --ci --offline", "pull_request": True}]},
        ],
        "container": container,
        "reports": ["evals/results/report.html", "evals/monitor/latest.json", ".qz/outputs/project-audit/audit.html", "knowledge/evals/results",
                    "reports/acceptance.xml"],
        "deploy": {"run": "bash scripts/deploy.sh {environment}",
                   "environments": [{"name": "staging", "approval": False}, {"name": "production", "approval": True}]},
    }


def write_spec(dest: Path, s: dict) -> Path:
    p = dest / "pipeline" / "pipeline.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# The solution's one pipeline. Edit it here, then `qz build pipeline` writes GitHub Actions, Azure Pipelines\n"
                 "# and GitLab CI from it. Steps are shell commands; `pull_request: true` runs a step only for a pull or merge\n"
                 "# request, where {base} is the branch it goes into. Production always waits for a person.\n"
                 + dump(s) + "\n", encoding="utf-8")
    return p


def read_spec(dest: Path) -> dict:
    try:
        import yaml
    except ImportError:
        raise SystemExit("`qz build pipeline` reads pipeline/pipeline.yaml with PyYAML: pip install pyyaml (qz doctor lists it).")
    return yaml.safe_load((dest / "pipeline" / "pipeline.yaml").read_text(encoding="utf-8"))


def _steps(s: dict):
    for st in s["stages"]:
        for step in st["steps"]:
            yield st["id"], step


# --- GitHub Actions ----------------------------------------------------------------------------------------------

def github(s: dict) -> dict[str, str]:
    v = s["versions"]
    setup = [{"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}}, {"uses": "astral-sh/setup-uv@v6", "with": {"version": v["uv"]}}]
    if "pip" in s["tools"]:
        setup.append({"uses": "actions/setup-python@v5", "with": {"python-version": v["python"], "cache": "pip"}})
    if "node" in s["tools"]:
        setup.append({"uses": "actions/setup-node@v4", "with": {"node-version": v["node"], "cache": "npm"}})
    if "go" in s["tools"]:
        setup.append({"uses": "actions/setup-go@v5", "with": {"go-version-file": "go.mod"}})
    if "dotnet" in s["tools"]:
        setup.append({"uses": "actions/setup-dotnet@v4", "with": {"dotnet-version": v["dotnet"]}})
    steps = list(setup)
    for _, step in _steps(s):
        g = {"name": step["name"], "run": step["run"].replace("{base}", "${{ github.base_ref }}")}
        if step.get("pull_request"):
            g = {"name": step["name"], "if": "github.event_name == 'pull_request'", "run": g["run"]}
        steps.append(g)
    steps.append({"uses": "actions/upload-artifact@v4", "if": "always()", "with": {"name": "qz-reports", "path": "\n".join(s["reports"]) + "\n"}})
    container = [{"uses": "actions/checkout@v4"}] + [{"name": c["name"], "run": c["run"]} for c in s["container"]]
    envs = s["deploy"]["environments"]
    first = envs[0]["name"]
    ci = {
        "name": "ci",
        "on": {"pull_request": {}, "push": {"branches": ["main", "master"]}},
        "permissions": {"contents": "read"},
        "jobs": {
            "check": {"runs-on": "ubuntu-latest", "steps": steps},
            "container": {"runs-on": "ubuntu-latest",
                          "env": {"UBUNTU_MIRROR": "http://azure.archive.ubuntu.com/ubuntu/"},     # GitHub's runners sit in Azure
                          "steps": container},
            "vulnerabilities": {"permissions": {"actions": "read", "contents": "read", "security-events": "write"},
                                "uses": "google/osv-scanner-action/.github/workflows/osv-scanner-reusable.yml@v2.7.1",
                                "with": {"upload-sarif": False, "scan-args": "--recursive\n./\n"}},
            f"deploy-{first}": {"needs": ["check", "container", "vulnerabilities"],
                                "if": "github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')",
                                "runs-on": "ubuntu-latest", "environment": first,
                                "steps": [{"uses": "actions/checkout@v4"},
                                          {"name": f"Deploy to {first} (deploys nothing until DEPLOY_COMMAND is set)",
                                           "run": s["deploy"]["run"].replace("{environment}", first),
                                           "env": {"DEPLOY_COMMAND": "${{ vars.DEPLOY_COMMAND }}"}}]},
        },
    }
    later = [e["name"] for e in envs[1:]]
    deploy = {
        "name": "deploy",
        "on": {"workflow_dispatch": {"inputs": {
            "environment": {"description": "Where to deploy (a person starting this run is the approval)", "required": True, "type": "choice", "options": later},
            "tag": {"description": "The commit whose images passed staging", "required": True, "type": "string"}}}},
        "permissions": {"contents": "read"},
        "jobs": {"deploy": {"runs-on": "ubuntu-latest", "environment": "${{ inputs.environment }}",
                            "steps": [{"uses": "actions/checkout@v4", "with": {"ref": "${{ inputs.tag }}"}},
                                      {"name": "Deploy the approved commit (deploys nothing until DEPLOY_COMMAND is set)",
                                       "run": s["deploy"]["run"].replace("{environment}", "${{ inputs.environment }}"),
                                       "env": {"DEPLOY_COMMAND": "${{ vars.DEPLOY_COMMAND }}", "DEPLOY_TAG": "${{ inputs.tag }}",
                                               "DEPLOY_APPROVED_BY": "${{ github.actor }}"}}]}},
    }
    return {".github/workflows/ci.yml": HEADER + dump(ci) + "\n", ".github/workflows/deploy.yml": HEADER + dump(deploy) + "\n"}


# --- Azure Pipelines ---------------------------------------------------------------------------------------------

def _strings(x):
    """Azure Pipelines' own schema types its scalars as strings (any of them may be a template expression), and Azure
    reads "0" and "false" as it reads 0 and false: every number and true or false is written as a string. A task's
    inputs are the exception: each task's schema types its own inputs (ManualValidation's
    allowApproversToApproveTheirOwnRuns is a true boolean), so they keep their types."""
    if isinstance(x, dict):
        return {k: v if k == "inputs" else _strings(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_strings(v) for v in x]
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return str(x)
    return x


def azure(s: dict) -> dict[str, str]:
    v = s["versions"]
    setup = [{"checkout": "self", "fetchDepth": 0},
             {"task": "UsePythonVersion@0", "inputs": {"versionSpec": v["python"]}, "displayName": "Python"},
             {"script": f"curl -LsSf https://astral.sh/uv/{v['uv']}/install.sh | sh\necho \"##vso[task.prependpath]$HOME/.local/bin\"",
              "displayName": f"uv {v['uv']}"}]
    if "node" in s["tools"]:
        setup.append({"task": "NodeTool@0", "inputs": {"versionSpec": f"{v['node']}.x"}, "displayName": "Node.js"})
    if "go" in s["tools"]:
        setup.append({"task": "GoTool@0", "inputs": {"version": v["go"]}, "displayName": "Go"})
    if "dotnet" in s["tools"]:
        setup.append({"task": "UseDotNet@2", "inputs": {"packageType": "sdk", "version": v["dotnet"]}, "displayName": ".NET"})
    steps = list(setup)
    for _, step in _steps(s):
        a = {"script": step["run"].replace("{base}", "$(System.PullRequest.TargetBranchName)"), "displayName": step["name"][:120]}
        if step.get("pull_request"):
            a["condition"] = "and(succeeded(), eq(variables['Build.Reason'], 'PullRequest'))"
        steps.append(a)
    steps.append({"task": "PublishPipelineArtifact@1", "condition": "always()", "inputs": {"targetPath": "evals/results", "artifact": "qz-reports"},
                  "displayName": "Reports"})
    container = [{"checkout": "self"}] + [{"script": c["run"], "displayName": c["name"][:120]} for c in s["container"]]
    envs = s["deploy"]["environments"]
    stages = [{"stage": "ci", "displayName": "Build, test, evaluate, scan", "jobs": [
        {"job": "check", "pool": {"vmImage": "ubuntu-latest"}, "steps": steps},
        {"job": "container", "pool": {"vmImage": "ubuntu-latest"}, "steps": container}]}]
    prev = "ci"
    on_main = "and(succeeded(), in(variables['Build.SourceBranch'], 'refs/heads/main', 'refs/heads/master'), ne(variables['Build.Reason'], 'PullRequest'))"
    for e in envs:
        n = e["name"]
        if e.get("approval"):
            stages.append({"stage": f"approve_{n}", "displayName": f"A person approves {n}", "dependsOn": prev, "condition": on_main, "jobs": [
                {"job": "approval", "pool": "server", "timeoutInMinutes": 1500, "steps": [
                    {"task": "ManualValidation@1", "timeoutInMinutes": 1440,
                     "inputs": {"notifyUsers": "", "allowApproversToApproveTheirOwnRuns": False, "onTimeout": "reject",
                                "instructions": f"Check staging, then approve to deploy $(Build.SourceVersion) to {n}. Nobody approves their own run."}}]}]})
            prev = f"approve_{n}"
        stages.append({"stage": n, "displayName": f"Deploy to {n}", "dependsOn": prev, "condition": on_main, "jobs": [
            {"deployment": f"deploy_{n}", "environment": n, "pool": {"vmImage": "ubuntu-latest"},
             "strategy": {"runOnce": {"deploy": {"steps": [{"checkout": "self"},
                                                            {"script": s["deploy"]["run"].replace("{environment}", n),
                                                             "displayName": f"Deploy to {n} (deploys nothing until DEPLOY_COMMAND is set)",
                                                             "env": {"DEPLOY_COMMAND": "$(DEPLOY_COMMAND)"}}]}}}}]})
        prev = n
    doc = {"trigger": {"branches": {"include": ["main", "master"]}}, "pr": {"branches": {"include": ["*"]}}, "stages": stages}
    return {"azure-pipelines.yml": HEADER + dump(_strings(doc)) + "\n"}


# --- GitLab CI ---------------------------------------------------------------------------------------------------

def gitlab(s: dict) -> dict[str, str]:
    v = s["versions"]
    if "dotnet" in s["tools"]:
        image = f"mcr.microsoft.com/dotnet/sdk:{v['dotnet'].rstrip('.x')}"
    elif "go" in s["tools"]:
        image = f"golang:{v['go']}-bookworm"
    elif "node" in s["tools"]:
        image = f"node:{v['node']}-bookworm"
    else:
        image = f"python:{v['python']}-bookworm"
    before = ["command -v python3 > /dev/null || (apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 curl ca-certificates > /dev/null)",
              f"curl -LsSf https://astral.sh/uv/{v['uv']}/install.sh | sh", "export PATH=\"$HOME/.local/bin:$PATH\""]
    script = []
    for _, step in _steps(s):
        run = step["run"].replace("{base}", "$CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
        script.append(f"# {step['name']}")
        if step.get("pull_request"):
            script.append(f'if [ -n "${{CI_MERGE_REQUEST_IID:-}}" ]; then\n{run}\nfi')
        else:
            script.append(run)
    rules = [{"if": "$CI_PIPELINE_SOURCE == \"merge_request_event\""}, {"if": "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH"}]
    on_main = [{"if": "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_PIPELINE_SOURCE != \"merge_request_event\""}]
    envs = s["deploy"]["environments"]
    doc: dict = {"stages": ["check", "container", *[e["name"] for e in envs]],
                 "variables": {"GIT_DEPTH": "0"},
                 "check": {"stage": "check", "image": image, "rules": rules, "before_script": before, "script": script,
                           "artifacts": {"when": "always", "paths": s["reports"], "expire_in": "30 days"}},
                 "container": {"stage": "container", "image": "docker:27", "services": ["docker:27-dind"], "rules": rules,
                               "variables": {"DOCKER_TLS_CERTDIR": "/certs"},
                               "script": [f"# {c['name']}\n{c['run']}" for c in s["container"]]}}
    prev = "container"
    for e in envs:
        n = e["name"]
        job = {"stage": n, "image": "debian:bookworm-slim", "needs": [prev], "environment": {"name": n},
               "script": [f"# Deploys nothing until DEPLOY_COMMAND is set in the project's CI/CD variables\n" + s["deploy"]["run"].replace("{environment}", n)]}
        if e.get("approval"):
            job["rules"] = [{**on_main[0], "when": "manual"}]        # a person starts it; until then the pipeline waits
            job["allow_failure"] = False
        else:
            job["rules"] = on_main
        doc[f"deploy-{n}"] = job
        prev = f"deploy-{n}"
    return {".gitlab-ci.yml": HEADER + dump(doc) + "\n"}


RENDER = {"github": github, "azure": azure, "gitlab": gitlab}


def render(dest: Path, s: dict, platforms=PLATFORMS) -> list[str]:
    written = []
    for p in platforms:
        for rel, text in RENDER[p](s).items():
            f = dest / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
            written.append(rel)
    return written
