"""Time and team estimates that respect QualiZeal's caps: no project longer than 3 months (13 weeks) and no team larger
than 6 people. Work that does not fit is split into phases, each a project of its own, never stretched or staffed past
the caps.

Each work item has an optimistic, most likely and pessimistic effort (three-point, PERT): expected = (O + 4M + P) / 6,
spread = (P - O) / 6. The project's P80 assumes independent items (spreads add as variances). Duration is the larger of
what the team's capacity allows and the longest chain of dependent items. Effort is in person-days; there are no
rates, costs or prices anywhere in an estimate."""
from __future__ import annotations

import math
from datetime import date, timedelta

Z80, Z90 = 0.8416, 1.2816
MAX_WEEKS, MAX_TEAM, FOCUS = 13, 6, 0.8


class EstimateError(ValueError):
    pass


def _days(item: dict, key: str, unit: str) -> float:
    v = float(item[key])
    return v * 5 if unit == "weeks" else v


def items(spec: dict) -> list[dict]:
    unit = spec.get("unit", "days")
    seen, out = set(), []
    for n, it in enumerate(spec.get("items") or [], 1):
        iid = str(it.get("id") or f"W{n}")
        if iid in seen:
            raise EstimateError(f"Work item id {iid} is used twice.")
        seen.add(iid)
        try:
            o, m, p = (_days(it, k, it.get("unit", unit)) for k in ("o", "m", "p"))
        except (KeyError, TypeError, ValueError):
            raise EstimateError(f"{iid}: give o, m and p (optimistic, most likely, pessimistic) as numbers.") from None
        if not (0 <= o <= m <= p) or p == 0:
            raise EstimateError(f"{iid}: need 0 <= o <= m <= p and p > 0 (got {o}, {m}, {p}).")
        out.append({"id": iid, "name": str(it.get("name") or iid), "role": str(it.get("role") or "engineer").lower(),
                    "o": o, "m": m, "p": p, "e": (o + 4 * m + p) / 6, "sd": (p - o) / 6,
                    "after": [str(x) for x in it.get("after") or []], "phase": it.get("phase"), "max_people": it.get("max_people")})
    if not out:
        raise EstimateError("No work items. Give items with id, name, role, o, m, p.")
    known = {i["id"] for i in out}
    for i in out:
        bad = [x for x in i["after"] if x not in known]
        if bad:
            raise EstimateError(f"{i['id']} waits on {', '.join(bad)}, which is not in the list.")
    return out


def _order(its: list[dict]) -> list[dict]:
    by, done, out = {i["id"]: i for i in its}, set(), []

    def visit(i, path=()):
        if i["id"] in done:
            return
        if i["id"] in path:
            raise EstimateError("Dependencies go in a circle: " + " -> ".join(path + (i["id"],)))
        for d in i["after"]:
            if d in by:                                  # a dependency outside this set was done in an earlier phase
                visit(by[d], path + (i["id"],))
        done.add(i["id"])
        out.append(i)
    for i in its:
        visit(i)
    return out


def _p80(its: list[dict]) -> float:
    return sum(i["e"] for i in its) + Z80 * math.sqrt(sum(i["sd"] ** 2 for i in its))


def plan_items(its: list[dict], focus: float, team: dict) -> dict[str, tuple[float, float]]:
    """Start and finish (weeks from the start) of each item: dependency order, each role's people as a pool, an item
    shared by at most its max_people (default 2). The same schedule draws the Gantt, so estimate and plan agree."""
    free = {role: [0.0] * max(1, int(n)) for role, n in team.items()}
    done: dict[str, tuple[float, float]] = {}
    for i in _order(its):
        pool = free.setdefault(i["role"], [0.0])
        k = max(1, min(len(pool), int(i.get("max_people") or 2)))
        chosen = sorted(range(len(pool)), key=lambda n: pool[n])[:k]
        begin = max([done[d][1] for d in i["after"] if d in done] + [pool[n] for n in chosen] + [0.0])
        finish = begin + (i["e"] + Z80 * i["sd"]) / (k * 5 * focus)
        for n in chosen:
            pool[n] = finish
        done[i["id"]] = (begin, finish)
    return done


def _chain_weeks(its: list[dict], focus: float, team: dict | None = None) -> float:
    return max((f for _, f in plan_items(its, focus, team or {r: 1 for r in {i["role"] for i in its}}).values()), default=0.0)


def options(its: list[dict], focus: float, max_team: int) -> list[dict]:
    """Weeks for each team size from the smallest to the cap, growing where it shortens the work most."""
    roles = sorted({i["role"] for i in its})
    team, out = {r: 1 for r in roles}, []
    while True:
        s = shape(its, focus, 10 ** 6, max_team, fixed=team)
        out.append({"size": s["size"], "weeks": s["weeks"], "team": dict(team)})
        if sum(team.values()) >= max_team:
            break
        cur = s["weeks"]
        best = min(roles, key=lambda r: shape(its, focus, 10 ** 6, max_team, fixed={**team, r: team[r] + 1})["weeks"])
        if shape(its, focus, 10 ** 6, max_team, fixed={**team, best: team[best] + 1})["weeks"] >= cur - 1e-9:
            break
        team[best] += 1
    return out


def shape(its: list[dict], focus: float, max_weeks: int, max_team: int, fixed: dict | None = None) -> dict:
    """Smallest team (one person per role to start, then one more wherever that shortens the work most) that
    finishes within max_weeks, never more than max_team people."""
    roles = sorted({i["role"] for i in its})
    if len(roles) > max_team:
        raise EstimateError(f"{len(roles)} roles need at least {len(roles)} people, over the {max_team}-person cap; combine roles.")
    total_e = sum(i["e"] for i in its)
    p80 = _p80(its)
    # each role's share of the P80: its expected effort scaled by the project's spread
    load = {r: sum(i["e"] for i in its if i["role"] == r) * (p80 / total_e if total_e else 1) for r in roles}
    team = dict(fixed or {r: 1 for r in roles})

    def weeks(t):
        return _chain_weeks(its, focus, t)
    while not fixed and weeks(team) > max_weeks and sum(team.values()) < max_team:
        best = min(roles, key=lambda r: weeks({**team, r: team[r] + 1}))
        if weeks({**team, best: team[best] + 1}) >= weeks(team) - 1e-9:      # nobody more shortens it
            break
        team[best] += 1
    w = weeks(team)
    return {"team": team, "size": sum(team.values()), "weeks": round(w, 1), "chain_weeks": round(_chain_weeks(its, focus, team), 1),
            "fits": w <= max_weeks + 1e-9 and sum(team.values()) <= max_team, "p80_days": round(p80, 1), "load_days": {r: round(v, 1) for r, v in load.items()}}


def _phases(its: list[dict], focus: float, max_weeks: int, max_team: int) -> list[list[dict]]:
    """Cut the ordered items into phases that each fit the caps. When items name a "phase", those phases are kept
    as given (and each must fit); otherwise items are packed in dependency order."""
    if any(i.get("phase") for i in its):
        named: dict[str, list[dict]] = {}
        for i in _order(its):
            named.setdefault(str(i.get("phase") or "Unphased"), []).append(i)
        phases = list(named.values())
        for name, ph in named.items():
            if not shape(ph, focus, max_weeks, max_team)["fits"]:
                raise EstimateError(f"Phase {name} does not fit {max_weeks} weeks with {max_team} people: move items out of it or split them.")
        return phases
    phases, cur = [], []
    for i in _order(its):
        trial = cur + [i]
        if cur and not shape(trial, focus, max_weeks, max_team)["fits"]:
            phases.append(cur)
            cur = [i]
        else:
            cur = trial
    if cur:
        phases.append(cur)
    for ph in phases:
        if not shape(ph, focus, max_weeks, max_team)["fits"]:
            big = max(ph, key=lambda x: x["p"])
            raise EstimateError(f"{big['id']} ({big['name']}) alone does not fit {max_weeks} weeks with {max_team} people: split it into smaller items.")
    return phases


def estimate(spec: dict) -> dict:
    """The estimate for a work breakdown. Caps cannot be raised above the company's: a spec may only lower them."""
    max_weeks = min(int(spec.get("max_weeks") or MAX_WEEKS), MAX_WEEKS)
    max_team = min(int(spec.get("max_team") or MAX_TEAM), MAX_TEAM)
    target = min(int(spec.get("target_weeks") or max_weeks), max_weeks)     # a faster plan: more people, still capped
    focus = float(spec.get("focus") or FOCUS)
    if not 0.3 <= focus <= 1.0:
        raise EstimateError("focus is the share of a week spent on this work: between 0.3 and 1.0.")
    its = items(spec)
    e = sum(i["e"] for i in its)
    sd = math.sqrt(sum(i["sd"] ** 2 for i in its))
    one = shape(its, focus, max_weeks, max_team)
    groups = _phases(its, focus, max_weeks, max_team) if any(i.get("phase") for i in its) or not one["fits"] else [its]
    start = date.fromisoformat(spec["start"]) if spec.get("start") else None
    phases, cursor = [], start
    for n, g in enumerate(groups, 1):
        s = shape(g, focus, target, max_team)
        if not s["fits"]:                                   # the target cannot be met: the fastest team within the caps
            fastest = min(options(g, focus, max_team), key=lambda o: (o["weeks"], o["size"]))
            s = shape(g, focus, max_weeks, max_team, fixed=fastest["team"]) if target < max_weeks else shape(g, focus, max_weeks, max_team)
        wk = max(1, math.ceil(s["weeks"]))
        label = g[0].get("phase") if g[0].get("phase") else (f"Phase {n}" if len(groups) > 1 else "Project")
        ph = {"name": str(label), "items": [i["id"] for i in g], "team": s["team"], "size": s["size"],
              "weeks": wk, "p80_days": s["p80_days"], "load_days": s["load_days"], "options": options(g, focus, max_team)}
        if cursor:
            ph["start"], ph["end"] = cursor.isoformat(), (cursor + timedelta(weeks=wk) - timedelta(days=3)).isoformat()
            cursor = cursor + timedelta(weeks=wk)
        phases.append(ph)
    notes = []
    if len(groups) > 1:
        notes.append(f"The work does not fit {max_weeks} weeks with {max_team} people, so it is {len(groups)} phases, each planned and staffed as its own project.")
    if any(i["p"] > 3 * i["m"] for i in its):
        notes.append("Some items have a pessimistic figure over three times the likely one: find out more before committing.")
    return {"project": spec.get("project", "Project"), "unit": "person-days", "focus": focus,
            "caps": {"weeks": max_weeks, "team": max_team}, "expected_days": round(e, 1),
            "p80_days": round(e + Z80 * sd, 1), "p90_days": round(e + Z90 * sd, 1), "items": its, "phases": phases,
            "fits_in_one": len(groups) == 1, "weeks_total": sum(p["weeks"] for p in phases), "peak_team": max(p["size"] for p in phases), "notes": notes}


def markdown(r: dict) -> str:
    rows = [f"# Estimate: {r['project']}", "",
            f"Expected {r['expected_days']:,} person-days; P80 {r['p80_days']:,}; P90 {r['p90_days']:,} (three-point estimates, {int(r['focus'] * 100)}% focus).",
            f"Caps: at most {r['caps']['weeks']} weeks and {r['caps']['team']} people per project.", ""]
    rows += ["| Phase | Weeks | People | Team | Work items |", "|---|---|---|---|---|"]
    for p in r["phases"]:
        team = ", ".join(f"{v} {k}" for k, v in sorted(p["team"].items()))
        when = f" ({p['start']} to {p['end']})" if p.get("start") else ""
        rows.append(f"| {p['name']}{when} | {p['weeks']} | {p['size']} | {team} | {', '.join(p['items'])} |")
    for p in r["phases"]:
        if len(p.get("options") or []) > 1:
            rows += ["", f"{p['name']}: weeks by team size: " + "; ".join(f"{o['size']} people {o['weeks']:g} weeks" for o in p["options"]) + "."]
    rows += ["", "| Item | Role | O | M | P | Expected |", "|---|---|---|---|---|---|"]
    rows += [f"| {i['id']} {i['name']} | {i['role']} | {i['o']:g} | {i['m']:g} | {i['p']:g} | {i['e']:.1f} |" for i in r["items"]]
    if r["notes"]:
        rows += [""] + [f"- {n}" for n in r["notes"]]
    rows += ["", "Effort only: no rates, costs or prices are part of this estimate."]
    return "\n".join(rows) + "\n"
