"""The agent: a LangGraph state graph that turns a question into a read-only query and an answer it can stand behind.

    understand -> retrieve -> generate -> guard -> execute -> check -> answer
                                 ^          |         |         |
                                 +----------+---------+---------+   retry with a precise note, at most max_attempts

understand  refuses a request to change data, asks back when a word is ambiguous (semantic.toml), spots a follow-up
retrieve    picks the tables the question needs and builds the schema card, only with what the role may read
generate    the model writes SQL (or asks back)
guard       the SQL tree is checked: one query, allowed tables and columns, LIMIT capped (guard.py)
execute     runs it read-only, with a time limit and a row limit (db.py)
check       does it double count, does a filter name a value the data does not have (checks.py)
answer      text that reads like instructions is withheld from the rows, then the answer is written; a model's
            answer is kept only if every number in it is in the rows

A blocked query is refused, never retried. The checkpointer keeps each thread's answered questions, so "and the
East?" follows on from the question before it."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import checks, config, db, guard, models, schema
from .audit import AuditLog
from .telemetry import tracer

READ_ONLY = "I can only read this database, so nothing was changed."
WRITE = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+|kindly\s+)?(delete|remove|drop|truncate|insert|alter|grant|revoke|rename|wipe|"
    r"erase|purge|modify|overwrite|cancel|update(?!\s+me\b)|change(?!\s+(in|over|of|from|between)\b)|set(?!\s+of\b))\b"
    r"|;\s*(drop|delete|update|insert|alter|attach|pragma|create|vacuum|replace)\b"
    r"|\b(run|execute|exec)\b.{0,40}\b(drop|delete|update|insert|alter|attach|pragma|vacuum)\b", re.I)
FOLLOW_UP = re.compile(r"^\s*(and|also|what about|how about|same|only|now|then|break (that|it|this) down|split (that|it|this)|"
                       r"by (month|week|year|region|carrier|category|segment|customer|product))\b|\b(that|those|these)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?![\w])")


class State(TypedDict, total=False):
    question: str
    role: str
    history: list            # answered questions on this thread, kept by the checkpointer: {question, sql, tables}
    previous: dict           # the answered question this one follows up, if it does
    card: str
    tables: list
    sql: str                 # what the model wrote
    run_sql: str             # what ran: the model's SQL with the LIMIT applied
    attempt: int
    feedback: str
    path: list               # the steps this question took, each {name, status, args}: what the gold set checks
    columns: list
    rows: list
    truncated: bool
    notes: list
    outcome: str             # answered | refused | clarify | failed
    answer: str
    usage: dict
    next: str


def _step(state: State, name: str, status: str, **args) -> list:
    return list(state.get("path") or []) + [{"name": name, "status": status, "args": args}]


def _fmt(v) -> str:
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    return str(v)


def describe(columns: list, rows: list) -> str:
    """The answer when no model words it: the rows, plainly."""
    if not rows:
        return "No rows matched."
    label = lambda c: str(c).replace("_", " ")  # noqa: E731
    if len(rows) == 1 and len(columns) == 1:
        return f"{label(columns[0]).capitalize()}: {_fmt(rows[0][0])}."
    if len(columns) == 2 and len(rows) <= 12:
        return "; ".join(f"{_fmt(a)}: {_fmt(b)}" for a, b in rows) + "."
    if len(rows) == 1:
        return "; ".join(f"{label(c)}: {_fmt(v)}" for c, v in zip(columns, rows[0])) + "."
    if len(columns) == 1 and len(rows) <= 12:
        return ", ".join(_fmt(r[0]) for r in rows) + "."
    line = lambda r: f"{_fmt(r[0])} ({', '.join(_fmt(v) for v in r[1:])})" if len(r) > 1 else _fmt(r[0])  # noqa: E731
    if len(rows) <= 12:
        return "; ".join(line(r) for r in rows) + "."
    return f"{len(rows)} rows. The first five: " + "; ".join(line(r) for r in rows[:5]) + "."


def grounded(text: str, rows: list, question: str) -> bool:
    """Every number in a model's answer must be in the rows (or the question, or be the row count)."""
    have = {str(len(rows))}
    for r in rows:
        for v in r:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                have |= {str(v), _fmt(v).replace(",", ""), str(round(v)), f"{v:.2f}", f"{v:.1f}"}
            elif v is not None:
                have |= {n.replace(",", "") for n in NUMBER.findall(str(v))}
    have |= {n.replace(",", "") for n in NUMBER.findall(question)}
    return all(n.replace(",", "") in have for n in NUMBER.findall(text))


class Agent:
    """One role, one database. ask() is one question on a thread; the same thread_id carries follow-ups."""

    def __init__(self, cfg: dict | None = None, role: str | None = None, model=None, sem: dict | None = None, checkpointer=None):
        self.cfg = cfg or config.load()
        self.sem = sem or config.semantic()
        self.role = role or self.cfg["agent"]["role"]
        if self.role not in self.sem["roles"]:
            raise ValueError(f"No role '{self.role}' in semantic.toml: {', '.join(self.sem['roles'])}.")
        r = self.sem["roles"][self.role]
        self.allowed = {t.lower() for t in r.get("tables", [])}
        self.deny = {c.lower() for c in r.get("deny_columns", [])}
        lim = self.cfg["limits"]
        path = db.ensure(self.cfg)
        personal = {c.lower() for role in self.sem["roles"].values() for c in role.get("deny_columns", [])}
        personal |= {f"{t}.{c}" for t, m in self.sem["tables"].items() for c, note in m.get("columns", {}).items() if "personal" in note.lower()}
        con = db.open_readonly(path)
        try:
            self.tables = schema.profile(con, self.sem, personal)
        finally:
            con.close()
        self.schema_map = {t: {c: col.type for c, col in tb.columns.items()} for t, tb in self.tables.items()}
        self.keys = schema.fks(self.tables)
        self.retriever = schema.Retriever(self.tables, self.sem)
        self.runner = db.ReadOnly(path, self.allowed, self.deny, int(lim["query_timeout_ms"]), int(lim["max_rows"]))
        self.model = model or models.make(self.cfg)
        if checkpointer is None:
            store = Path(self.cfg["store"]["threads"])
            store.parent.mkdir(parents=True, exist_ok=True)
            self._threads = sqlite3.connect(str(store), check_same_thread=False)
            checkpointer = SqliteSaver(self._threads)
        else:
            self._threads = None
        self.audit = AuditLog(self.cfg["store"]["audit"])
        self.graph = self._build().compile(checkpointer=checkpointer)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ the steps
    def _understand(self, s: State) -> dict:
        q = re.sub(r"\s+", " ", str(s.get("question") or "")).strip()
        fresh = {"question": q, "previous": None, "card": "", "tables": [], "sql": "", "run_sql": "", "attempt": 0, "feedback": "",
                 "path": [], "columns": [], "rows": [], "truncated": False, "notes": [], "outcome": "", "answer": "",
                 "usage": {"input_tokens": 0, "output_tokens": 0}}
        limit = int(self.cfg["limits"]["max_question_chars"])
        if not q:
            return {**fresh, "outcome": "failed", "answer": "Ask a question about the data.", "path": _step(fresh, "understand", "empty"), "next": "end"}
        if len(q) > limit:
            return {**fresh, "outcome": "refused", "answer": f"Keep a question under {limit} characters.", "path": _step(fresh, "understand", "too_long"), "next": "end"}
        if WRITE.search(q):
            return {**fresh, "outcome": "refused", "answer": READ_ONLY, "path": _step(fresh, "understand", "write"), "next": "end"}
        low = f" {q.lower()} "
        for a in self.sem["ambiguous"].values():
            if any(w in low for w in a.get("words", [])) and not any(u in low for u in a.get("unless", [])):
                return {**fresh, "outcome": "clarify", "answer": a["ask"], "path": _step(fresh, "understand", "clarify"), "next": "end"}
        hist = list(s.get("history") or [])
        prev = hist[-1] if hist and FOLLOW_UP.search(q) else None
        return {**fresh, "previous": prev, "path": _step(fresh, "understand", "follow-up" if prev else "new"), "next": "retrieve"}

    def _retrieve(self, s: State) -> dict:
        q, prev = s["question"], s.get("previous")
        text = q + (f" {prev['question']}" if prev else "")
        ranked = self.retriever.rank(text)
        if ranked and ranked[0][0] not in self.allowed:
            best = max((sc for n, sc in ranked if n in self.allowed), default=0.0)
            if best < 0.6 * ranked[0][1]:
                return {"outcome": "refused", "answer": f"That is in {ranked[0][0]}, which the {self.role} role cannot read.",
                        "path": _step(s, "retrieve", "blocked", table=ranked[0][0]), "next": "end"}
        also = list(prev.get("tables", [])) if prev else []
        for m in self.sem["metrics"].values():
            if any(w in q.lower() for w in m.get("words", [])):
                also += [t for t in re.findall(r"\b([a-z_]+)\.", m.get("sql", "")) if t in self.tables]
        names = self.retriever.pick(text, self.allowed, int(self.cfg["retrieval"]["max_tables"]), list(dict.fromkeys(also)))
        names = names or sorted(self.allowed)[: int(self.cfg["retrieval"]["max_tables"])]
        return {"tables": names, "card": schema.card(self.tables, names, self.deny, self.sem), "path": _step(s, "retrieve", "ok", tables=names), "next": "generate"}

    def _generate(self, s: State) -> dict:
        attempt = int(s.get("attempt") or 0) + 1
        try:
            d = self.model.write_sql(s["question"], s["card"], s.get("previous"), s.get("feedback", ""), attempt)
        except models.NotScripted:
            return {"attempt": attempt, "outcome": "failed", "path": _step(s, "generate", "unknown"), "next": "end",
                    "answer": "The offline scripted model only knows the sample questions (`uv run -m sqlagent samples`). "
                              "For your own questions set provider = \"anthropic\" or \"openai\" in sql.toml."}
        except Exception as e:                                   # a model or network error: say what kind, never a key
            return {"attempt": attempt, "outcome": "failed", "path": _step(s, "generate", "error"), "next": "end",
                    "answer": f"The model call failed ({type(e).__name__}). Nothing was run."}
        usage = {k: s["usage"].get(k, 0) + d.usage.get(k, 0) for k in ("input_tokens", "output_tokens")}
        if d.clarify and not d.sql:
            return {"attempt": attempt, "usage": usage, "outcome": "clarify", "answer": d.clarify, "path": _step(s, "generate", "clarify"), "next": "end"}
        return {"attempt": attempt, "usage": usage, "sql": d.sql, "path": _step(s, "generate", "ok", attempt=attempt), "next": "guard"}

    def _retry(self, s: State, step: str, status: str, note: str, **args) -> dict:
        if int(s["attempt"]) >= int(self.cfg["limits"]["max_attempts"]):
            return {"outcome": "failed", "feedback": note, "path": _step(s, step, status, **args), "next": "end",
                    "answer": f"I couldn't get a query I trust in {s['attempt']} attempts. The last problem: {note}"}
        return {"feedback": note, "path": _step(s, step, status, **args), "next": "generate"}

    def _guard(self, s: State) -> dict:
        try:
            ck = guard.check(s["sql"], self.schema_map, self.allowed, self.deny, int(self.cfg["limits"]["max_rows"]))
        except guard.Blocked as e:
            msg = READ_ONLY if e.kind in ("write", "multi") else str(e)
            return {"outcome": "refused", "answer": msg, "path": _step(s, "guard", "blocked", kind=e.kind), "next": "end"}
        except guard.Invalid as e:
            return self._retry(s, "guard", "invalid", str(e))
        return {"run_sql": ck.sql, "tables": ck.tables, "feedback": "", "path": _step(s, "guard", "ok", limited=ck.limited), "next": "execute"}

    def _execute(self, s: State) -> dict:
        try:
            r = self.runner.run(s["run_sql"])
        except db.QueryError as e:
            if e.kind == "denied":
                return {"outcome": "refused", "answer": str(e), "path": _step(s, "execute", "denied"), "next": "end"}
            return self._retry(s, "execute", e.kind, f"The database said: {e}")
        return {"columns": r.columns, "rows": r.rows, "truncated": r.truncated, "path": _step(s, "execute", "ok", rows=len(r.rows), ms=r.ms), "next": "check"}

    def _lookup(self, table: str, column: str, value: str):
        if self.runner.run(f'SELECT 1 FROM "{table}" WHERE "{column}" = ? LIMIT 1', (value,)).rows:
            return True, []
        col = self.tables[table].columns.get(column)
        known = (col.values if col else []) or [r[0] for r in self.runner.run(
            f'SELECT DISTINCT "{column}" FROM "{table}" WHERE lower("{column}") = lower(?) LIMIT 3', (value,)).rows]
        return False, checks.suggest(value, [str(k) for k in known])

    def _check(self, s: State) -> dict:
        tree = guard.check(s["sql"], self.schema_map, self.allowed, self.deny, int(self.cfg["limits"]["max_rows"])).tree
        fan = checks.fan_out(tree, self.keys)
        if fan:
            return self._retry(s, "check", "fan-out", fan[0])
        vals = checks.values(tree, self._lookup)
        fixable = [v for v in vals if v["suggest"]]
        if fixable:
            v = fixable[0]
            return self._retry(s, "check", "value", f"{v['column']} has no '{v['value']}'. Did you mean '{v['suggest'][0]}'? "
                                                    "Compare text exactly as it is stored.", column=v["column"])
        notes = list(s.get("notes") or [])
        if not s["rows"] or s["rows"] == [[0]] or s["rows"] == [[None]]:
            for v in vals:
                t, c = v["column"].split(".", 1)
                known = self.tables[t].columns[c].values
                notes.append(f"There is no {v['column']} '{v['value']}'" + (f": the values are {', '.join(known)}." if known else "."))
        return {"notes": notes, "path": _step(s, "check", "ok"), "next": "answer"}

    def _answer(self, s: State) -> dict:
        rows, withheld = checks.withhold(s["rows"])
        notes = list(s.get("notes") or [])
        if s.get("truncated"):
            notes.append(f"Showing the first {self.cfg['limits']['max_rows']} rows; there are more.")
        if withheld:
            notes.append(f"{withheld} value{'s' if withheld > 1 else ''} withheld: the text reads like instructions to an AI, "
                         "so it was kept out of this answer. Read it in the database if you need it.")
        text, usage = self.model.summarise(s["question"], s["run_sql"], s["columns"], rows, notes)
        total = {k: s["usage"].get(k, 0) + usage.get(k, 0) for k in ("input_tokens", "output_tokens")}
        status = "model"
        if not text or not grounded(text, rows, s["question"]):
            status = "template" if not text else "template (a number in the model's answer was not in the rows)"
            text = describe(s["columns"], rows)
        answer = " ".join([text] + notes)
        hist = (list(s.get("history") or []) + [{"question": s["question"], "sql": s["run_sql"], "tables": s.get("tables", [])}])[-5:]
        return {"rows": rows, "notes": notes, "usage": total, "answer": answer, "outcome": "answered", "history": hist,
                "path": _step(s, "answer", "ok", by=status, withheld=withheld), "next": "end"}

    def _build(self) -> StateGraph:
        g = StateGraph(State)
        steps = {"understand": self._understand, "retrieve": self._retrieve, "generate": self._generate, "guard": self._guard,
                 "execute": self._execute, "check": self._check, "answer": self._answer}
        for name, fn in steps.items():
            g.add_node(name, _traced(name, fn))
        g.add_edge(START, "understand")
        route = lambda s: s.get("next") or "end"  # noqa: E731
        for name in steps:
            g.add_conditional_edges(name, route, {**{n: n for n in steps if n != "understand"}, "end": END})
        return g

    # ------------------------------------------------------------------ one question
    def ask(self, question: str, thread_id: str | None = None) -> dict:
        thread_id = thread_id or uuid.uuid4().hex
        cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": int(self.cfg["limits"]["recursion_limit"])}
        with self._lock, tracer().start_as_current_span("sql.ask") as span:
            s = self.graph.invoke({"question": question, "role": self.role}, cfg)
            out = {"thread_id": thread_id, "role": self.role, "outcome": s.get("outcome") or "failed", "answer": s.get("answer", ""),
                   "sql": s.get("sql") or "", "ran": s.get("run_sql") or "", "columns": s.get("columns") or [], "rows": s.get("rows") or [],
                   "truncated": bool(s.get("truncated")), "tables": s.get("tables") or [], "attempts": int(s.get("attempt") or 0),
                   "notes": s.get("notes") or [], "path": s.get("path") or [], "usage": s.get("usage") or {}, "provider": self.model.name}
            masked = guard.masked(out["ran"] or out["sql"]) if (out["ran"] or out["sql"]) else ""
            for k, v in (("sql.role", self.role), ("sql.outcome", out["outcome"]), ("sql.attempts", out["attempts"]),
                         ("sql.rows", len(out["rows"])), ("sql.query", masked), ("sql.tables", out["tables"]),
                         ("sql.path", json.dumps([f"{p['name']}:{p['status']}" for p in out["path"]])),
                         ("gen_ai.usage.input_tokens", out["usage"].get("input_tokens", 0)),
                         ("gen_ai.usage.output_tokens", out["usage"].get("output_tokens", 0))):
                span.set_attribute(k, v)
            rec = self.audit.write(thread=thread_id, role=self.role, outcome=out["outcome"], attempts=out["attempts"], tables=out["tables"],
                                   sql=masked, rows=len(out["rows"]), path=[f"{p['name']}:{p['status']}" for p in out["path"]],
                                   provider=self.model.name, usage=out["usage"])
            span.set_attribute("sql.audit_seq", rec["seq"])
            return out

    def close(self) -> None:
        self.runner.close()
        if self._threads is not None:
            self._threads.close()


def _traced(name: str, fn):
    def run(state):
        with tracer().start_as_current_span(f"sql.{name}") as span:
            out = fn(state)
            last = (out.get("path") or [{}])[-1]
            span.set_attribute("sql.status", str(last.get("status", "")))
            if "attempt" in out:
                span.set_attribute("sql.attempt", int(out["attempt"]))
            return out
    run.__name__ = name
    return run
