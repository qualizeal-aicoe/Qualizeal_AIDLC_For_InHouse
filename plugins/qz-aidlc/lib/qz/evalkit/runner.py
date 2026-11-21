"""Run a gold set through an agent's adapter, or replay recorded outputs for a free, deterministic CI run.

The adapter is any command that reads one case as JSON on stdin and writes one JSON object on stdout:
  {"output": <text or object>, "tool_calls": [{"name", "args", "status"}], "usage": {"input_tokens", "output_tokens"},
   "cost_usd": optional, "latency_ms": optional}
The kit never puts API keys in files: the adapter inherits only the environment variables named in pass_env."""
from __future__ import annotations

import json
import math
import os
import subprocess
import time
from pathlib import Path

from . import checks
from .. import guard
from ..util import now, read_json, write_json

RUNNERS = ("python3", "python", "uv", "node", "npx", "tsx", "go", "dotnet", "java", "deno", "bun")
BASE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "PYTHONPATH", "VIRTUAL_ENV", "GOPATH", "GOCACHE", "GOMODCACHE", "GOFLAGS", "GOPROXY",
            "DOTNET_ROOT", "NODE_PATH", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "UV_SYSTEM_CERTS", "USERPROFILE", "APPDATA", "LOCALAPPDATA")


def load(proj: Path, cfg_path: str = "evals/eval.json") -> tuple[dict, list[dict]]:
    cfg = read_json(proj / cfg_path)
    if not cfg:
        raise SystemExit(f"{cfg_path} is missing. Create it with: qz eval init")
    gold = proj / cfg.get("gold", "evals/gold.jsonl")
    cases = []
    for i, line in enumerate(gold.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("//"):
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{gold.name} line {i}: {e}")
    return cfg, cases


def lint(cfg: dict, cases: list[dict]) -> list[str]:
    errs, ids = [], set()
    for c in cases:
        cid = c.get("id")
        if not cid or cid in ids:
            errs.append(f"case id missing or repeated: {cid}")
        ids.add(cid)
        if "input" not in c:
            errs.append(f"{cid}: no input")
        if not c.get("checks") and not c.get("rubric"):
            errs.append(f"{cid}: no checks and no rubric, so it can never fail")
        for ch in c.get("checks") or []:
            if ch.get("type") not in checks.TYPES:
                errs.append(f"{cid}: unknown check type {ch.get('type')!r}")
        if c.get("rubric") and c["rubric"] not in (cfg.get("rubrics") or {}) and len(str(c["rubric"])) < 30:
            errs.append(f"{cid}: rubric '{c['rubric']}' is not defined in eval.json")
    return errs


def _adapter_ok(cmd: list[str], proj: Path) -> None:
    if not cmd or Path(cmd[0]).name not in RUNNERS:
        raise SystemExit(f"The adapter must start with one of: {', '.join(RUNNERS)}. Got: {cmd[:1]}")
    d = guard.decide("Bash", {"command": " ".join(cmd)}, proj)
    if d.action:
        raise SystemExit(f"The guard will not run this adapter ({d.rule}): {d.message}")
    for a in cmd[1:]:
        if not a.startswith("-") and ("/" in a or "\\" in a or "." in a):
            p = (proj / a).resolve()
            if p.exists() and proj.resolve() not in (p, *p.parents):
                raise SystemExit(f"The adapter script must live inside the project: {a}")


def call(cmd: list[str], case: dict, proj: Path, timeout: float, env_extra: dict, pass_env: list[str]) -> dict:
    env = {k: os.environ[k] for k in list(BASE_ENV) + list(pass_env) if k in os.environ}
    env.update({k: str(v) for k, v in (env_extra or {}).items()})
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=json.dumps({"id": case["id"], "input": case["input"]}), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=str(proj), env=env)
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout:g}s", "latency_ms": int((time.time() - t0) * 1000)}
    ms = int((time.time() - t0) * 1000)
    if r.returncode != 0:
        return {"error": f"adapter exit {r.returncode}: {guard.redact(r.stderr[-400:])[0]}", "latency_ms": ms}
    line = next((x for x in reversed(r.stdout.strip().splitlines()) if x.strip().startswith("{")), "")
    try:
        res = json.loads(line)
    except json.JSONDecodeError:
        return {"error": f"adapter did not print a JSON object: {guard.redact(r.stdout[-200:])[0]!r}", "latency_ms": ms}
    res.setdefault("latency_ms", ms)
    return res


def _cost(res: dict, prices: dict | None) -> None:
    if res.get("cost_usd") is None and prices and res.get("usage"):
        u = res["usage"]
        res["cost_usd"] = round(((u.get("input_tokens") or 0) * prices.get("input_per_mtok", 0) + (u.get("output_tokens") or 0) * prices.get("output_per_mtok", 0)) / 1e6, 6)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _pct(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(math.ceil(q * len(xs))) - 1)] if xs else None


def run(proj: Path, mode: str = "live", cfg_path: str = "evals/eval.json", only: list[str] | None = None, tag: str | None = None, label: str = "") -> dict:
    cfg, cases = load(proj, cfg_path)
    errs = lint(cfg, cases)
    if errs:
        raise SystemExit("Gold set problems:\n  " + "\n  ".join(errs))
    ad = cfg.get("adapter") or {}
    rec_dir = proj / cfg.get("recordings", "evals/recordings")
    stub = str((ad.get("env") or {}).get("AGENT_MODE", "")).lower() == "stub"   # a scripted model: token counts are estimates, so no cost is derived
    if mode == "live":
        _adapter_ok(ad.get("command") or [], proj)
        rec_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        if (only and c["id"] not in only) or (tag and tag not in (c.get("tags") or [])):
            continue
        if mode == "replay":
            res = read_json(rec_dir / f"{c['id']}.json")
            if res is None:
                res = {"error": "no recording; run once live to record it"}
            elif res.get("input_sha") != _sha(c["input"]):
                res = {"error": "the case input changed since it was recorded; run live to re-record"}
        else:
            res = call(ad["command"], c, proj, float(ad.get("timeout_s", 120)), ad.get("env"), ad.get("pass_env") or [])
            if not stub:
                _cost(res, cfg.get("prices"))
            if "error" not in res:
                text, n_secrets = guard.redact(json.dumps(res, ensure_ascii=False))
                if n_secrets:
                    res["secrets_in_output"] = n_secrets
                write_json(rec_dir / f"{c['id']}.json", {**json.loads(text), **({"secrets_in_output": n_secrets} if n_secrets else {}), "input_sha": _sha(c["input"]), "recorded": now()})
        fails = []
        if "error" in res:
            fails.append({"type": "adapter", "detail": res["error"]})
        else:
            if res.get("secrets_in_output"):          # a credential in the output fails the case whatever its checks say
                fails.append({"type": "secret", "detail": "the output contained what looks like a credential; it is redacted in the recording"})
            for ch in c.get("checks") or []:
                ok, why = checks.run(ch, res)
                if not ok:
                    fails.append({"type": ch["type"], "detail": why, "check": {k: v for k, v in ch.items() if k != "schema"}})
        rows.append({"id": c["id"], "tags": c.get("tags") or [], "passed": not fails, "fails": fails, "needs_judge": bool(c.get("rubric")), "rubric": c.get("rubric"),
                     "input": c["input"], "output": res.get("output"), "tool_calls": res.get("tool_calls") or [], "latency_ms": res.get("latency_ms"),
                     "usage": res.get("usage"), "cost_usd": res.get("cost_usd")})
    return summarise(proj, cfg, rows, "replay" if mode == "replay" else ("stub" if stub else "live"), label)


def _sha(x) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def summarise(proj: Path, cfg: dict, rows: list[dict], mode: str, label: str = "", judge: dict | None = None) -> dict:
    def final(r):
        return r["passed"] and (r.get("judge_pass", True) if (judge or {}).get("trusted") else True)
    n, k = len(rows), sum(1 for r in rows if final(r))
    lo, hi = wilson(k, n)
    tags = {}
    for r in rows:
        for t in r["tags"] or ["untagged"]:
            a = tags.setdefault(t, [0, 0])
            a[0] += 1 if final(r) else 0
            a[1] += 1
    th = cfg.get("thresholds") or {}
    breaches = []
    if n and k / n < th.get("pass_rate", 0.9):
        breaches.append(f"pass rate {k / n:.1%} is under the threshold {th.get('pass_rate', 0.9):.0%}")
    for t, floor in (th.get("by_tag") or {}).items():
        if t in tags and tags[t][0] / tags[t][1] < floor:
            breaches.append(f"tag '{t}': {tags[t][0]}/{tags[t][1]} is under {floor:.0%}")
    lat = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    cost = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    if th.get("p95_latency_ms") and lat and _pct(lat, 0.95) > th["p95_latency_ms"]:
        breaches.append(f"p95 latency {_pct(lat, 0.95):.0f} ms is over {th['p95_latency_ms']}")
    if th.get("mean_cost_usd") and cost and sum(cost) / len(cost) > th["mean_cost_usd"]:
        breaches.append(f"mean cost ${sum(cost) / len(cost):.4f} is over ${th['mean_cost_usd']}")
    res = {"schema": 1, "at": now(), "mode": mode, "label": label, "n": n, "passed": k, "pass_rate": round(k / n, 4) if n else 0.0, "ci95": [round(lo, 4), round(hi, 4)],
           "by_tag": {t: {"passed": a[0], "n": a[1]} for t, a in sorted(tags.items())}, "p50_latency_ms": _pct(lat, 0.5), "p95_latency_ms": _pct(lat, 0.95),
           "mean_cost_usd": round(sum(cost) / len(cost), 6) if cost else None, "total_cost_usd": round(sum(cost), 6) if cost else None,
           "tokens": sum(((r["usage"] or {}).get("input_tokens") or 0) + ((r["usage"] or {}).get("output_tokens") or 0) for r in rows),
           "judge": judge, "awaiting_judge": sum(1 for r in rows if r["needs_judge"] and "judge_pass" not in r), "breaches": breaches, "verdict": "FAIL" if breaches else "PASS",
           "note": " ".join(x for x in ("This ran against the scripted stub: it proves the wiring and the checks, not a model." if mode == "stub" else "",
                                         "n is small: the 95% interval is wide, so treat the rate as a signal, not a measurement." if n < 50 else "") if x), "rows": rows}
    out = proj / cfg.get("results", "evals/results")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "latest.json", res)
    write_json(out / f"{res['at'][:19].replace(':', '').replace('-', '')}{'-' + label if label else ''}.json", res)
    return res


def compare(base: dict, new: dict, max_drop: float = 0.02, cost_up: float = 0.2) -> dict:
    b = {r["id"]: r for r in base["rows"]}
    flipped = [r["id"] for r in new["rows"] if r["id"] in b and b[r["id"]]["passed"] and not r["passed"]]
    fixed = [r["id"] for r in new["rows"] if r["id"] in b and not b[r["id"]]["passed"] and r["passed"]]
    critical = [i for i in flipped if set(next(r for r in new["rows"] if r["id"] == i)["tags"]) & {"safety", "security", "critical"}]
    reasons = []
    if critical:
        reasons.append(f"safety or critical cases now fail: {', '.join(critical)}")
    if new["pass_rate"] < base["pass_rate"] - max_drop:
        reasons.append(f"pass rate fell from {base['pass_rate']:.1%} to {new['pass_rate']:.1%}")
    if base.get("mean_cost_usd") and new.get("mean_cost_usd") and new["mean_cost_usd"] > base["mean_cost_usd"] * (1 + cost_up):
        reasons.append(f"mean cost rose from ${base['mean_cost_usd']:.4f} to ${new['mean_cost_usd']:.4f}")
    overlap = not (new["ci95"][1] < base["ci95"][0] or base["ci95"][1] < new["ci95"][0])
    return {"verdict": "REGRESSION" if reasons else "OK", "reasons": reasons, "flipped_to_fail": flipped, "fixed": fixed,
            "base": {"pass_rate": base["pass_rate"], "ci95": base["ci95"], "n": base["n"]}, "new": {"pass_rate": new["pass_rate"], "ci95": new["ci95"], "n": new["n"]},
            "note": "The two 95% intervals overlap; a difference in rate alone is not evidence of change at this sample size." if overlap and base["pass_rate"] != new["pass_rate"] else ""}


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)
