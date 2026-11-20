"""The memory: retain what a person says, recall it when it helps, keep the history of what changed, and forget it
when they ask. Every call names the person; every call is in the audit log, which holds what happened and never what
was said, and whose records are hash-chained so an edited, removed or truncated record shows up in `mem audit`."""
from __future__ import annotations

import functools
import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import extract, policy, store, telemetry
from .config import load

USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
UNKEYED = ("note", "event")                 # each one is its own memory; the rest replace the value of their key
STOP = set("a an and are am as at be but by can could did do does for from had has have how i if in into is it its me my "
           "of on or our so tell that the their them then there these they this to was we were what when where which who "
           "why will with would you your".split())
INTENTS = [
    ("location", r"\b(where (?:do|did) i (?:live|stay)|where am i (?:based|living)|which city|what city|my (?:city|address|location|home)|where i live)\b"),
    ("name", r"\b(my name|what should you call me|what do you call me|who am i)\b"),
    ("employer", r"\b(where (?:do|did) i work|who do i work for|my (?:employer|company)|which company)\b"),
    ("role", r"\b(my (?:role|job|title)|what do i do for (?:a living|work))\b"),
    ("birthday", r"\b(my birthday|when was i born)\b"),
    ("allergy", r"\ballerg"),
    ("prefers:", r"\bwhat (?:do|else do) i (?:like|prefer|enjoy|love)\b"),
    ("dislikes:", r"\bwhat do(?:n't| not) i like\b|\bwhat do i dislike\b"),
]
GENESIS = "0" * 64                          # the "previous hash" of the first record in an audit log


def _locked(fn):
    """One call at a time per Memory (the SQLite connection is shared by the threads of a server), each in its own
    trace span, named memory.<call>."""
    name = "memory." + fn.__name__

    @functools.wraps(fn)
    def run(self, *a, **k):
        with self._lock, telemetry.tracer().start_as_current_span(name) as span:
            if a and isinstance(a[0], str):
                span.set_attribute("memory.user", telemetry.pseudonym(a[0]))
            return fn(self, *a, **k)
    return run


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


HISTORY = re.compile(r"\b(before|previous(?:ly)?|used to|earlier|formerly)\b", re.I)


class MemError(ValueError):
    """A request the memory refuses, with the reason in words a person can act on."""


@dataclass
class Decision:
    decision: str             # added, updated, same, skipped, quarantined, forgotten
    kind: str = ""
    key: str = ""
    id: int | None = None
    value: str = ""
    reason: str = ""


@dataclass
class Report:
    decisions: list[Decision] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})

    def as_dict(self) -> dict:
        return {"decisions": [asdict(d) for d in self.decisions], "removed": self.removed, "usage": self.usage}


@dataclass
class Hit:
    id: int
    kind: str
    key: str
    value: str
    text: str
    score: float
    history: bool = False
    observed: float = 0.0


def _user(u: str) -> str:
    if not USER.match(u or ""):
        raise MemError("A user id is 1 to 64 letters, digits or . _ @ -, and every call names one.")
    return u


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOP]


def intent_keys(q: str) -> list[str]:
    low = (q or "").lower()
    keys = [k for k, rx in INTENTS if re.search(rx, low)]
    rel = re.search(r"\bmy (" + extract.RELATIONS + r")\b", low)
    if rel:
        keys.append(f"relation:{rel.group(1)}")
    fav = re.search(r"\bfavou?rite\s+([a-z]+(?: [a-z]+)?)", low)
    if fav:
        keys.append("favorite:" + extract._norm(fav.group(1)))
    return keys


class Memory:
    def __init__(self, cfg: dict | None = None, path: str | Path | None = None, extractor=None, audit: str | Path | None = None,
                 clock=time.time):
        self.cfg = cfg or load()
        self.con = store.connect(path or self.cfg["store"]["path"])
        self.con.execute("PRAGMA secure_delete=ON")           # erased text is overwritten in the file, not just unlinked
        self.extractor = extractor or extract.make(self.cfg)
        self.audit_path = Path(audit or self.cfg["store"]["audit"])
        self.now = clock
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self.con.close()

    # ------------------------------------------------------------ the audit log: what happened, never what was said
    def _audit(self, action: str, user: str, **detail) -> None:
        """Append one record. It carries the hash of the record before it, and the database keeps the newest hash, so
        `verify_audit_log` finds a record that was edited, taken out or cut off the end. The database's write lock
        orders writers across threads and processes, so two writers never fork the chain."""
        own = not self.con.in_transaction
        if own:
            self.con.execute("BEGIN IMMEDIATE")
        try:
            head = self.con.execute("SELECT seq, hash FROM audit_head WHERE id=1").fetchone()
            seq, prev = (head["seq"] + 1, head["hash"]) if head else (1, GENESIS)
            rec = {"seq": seq, "ts": round(self.now(), 3), "action": action, "user": user, **detail, "prev": prev}
            rec["hash"] = _digest(rec)
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.con.execute("INSERT OR REPLACE INTO audit_head(id, seq, hash) VALUES (1, ?, ?)", (seq, rec["hash"]))
            if own:
                self.con.execute("COMMIT")
            telemetry.record(action, seq, detail)
        except BaseException:
            if own:
                self.con.execute("ROLLBACK")
            raise

    @_locked
    def verify_audit_log(self) -> dict:
        """Walk the audit log: every record's hash, its link to the one before, no gap in the numbering, and the newest
        record still at the end. A log moved aside on purpose (rotation) leaves the next file starting mid-chain: that
        is reported as `first`, not as a problem."""
        problems, prev, first = [], None, None
        lines = self.audit_path.read_text(encoding="utf-8").splitlines() if self.audit_path.is_file() else []
        for i, line in enumerate(lines, 1):
            try:
                rec = json.loads(line)
            except ValueError:
                problems.append(f"line {i}: not a record")
                prev = None
                continue
            seq = rec.get("seq")
            first = seq if first is None else first
            if rec.get("hash") != _digest(rec):
                problems.append(f"line {i} (record {seq}): changed after it was written")
            if prev is not None and (rec.get("prev") != prev.get("hash") or seq != (prev.get("seq") or 0) + 1):
                problems.append(f"line {i} (record {seq}): does not follow record {prev.get('seq')}; one is missing or out of place")
            if seq == 1 and rec.get("prev") != GENESIS:
                problems.append(f"line {i}: record 1 does not start the chain")
            prev = rec
        head = self.con.execute("SELECT seq, hash FROM audit_head WHERE id=1").fetchone()
        if head and (prev is None or prev.get("hash") != head["hash"]):
            problems.append(f"record {head['seq']}, the newest, is not at the end of the log: it was removed or the log was replaced")
        return {"ok": not problems, "records": len(lines), "first": first, "newest": head["seq"] if head else 0, "problems": problems}

    def _tx(self):
        con = self.con

        class Tx:
            def __enter__(self):
                con.execute("BEGIN IMMEDIATE")

            def __exit__(self, et, ev, tb):
                con.execute("ROLLBACK" if et else "COMMIT")
        return Tx()

    # ------------------------------------------------------------ consent
    def categories(self) -> list[str]:
        return list(self.cfg["consent"]["categories"])

    @_locked
    def has_consent(self, user: str, cat: str) -> bool:
        return bool(self.con.execute("SELECT 1 FROM consents WHERE user=? AND category=?", (user, cat)).fetchone())

    @_locked
    def consent(self, user: str, cat: str, grant: bool) -> dict:
        user = _user(user)
        if cat not in self.categories():
            raise MemError(f"'{cat}' is not a consent category here: {', '.join(self.categories())}.")
        with self._tx():
            if grant:
                self.con.execute("INSERT OR REPLACE INTO consents(user, category, granted) VALUES (?,?,?)", (user, cat, self.now()))
                erased = 0
            else:
                self.con.execute("DELETE FROM consents WHERE user=? AND category=?", (user, cat))
                erased = self.con.execute("DELETE FROM memories WHERE user=? AND category=?", (user, cat)).rowcount
        if erased:
            self._compact()
        self._audit("consent", user, category=cat, granted=grant, erased=erased)
        return {"user": user, "category": cat, "granted": grant, "erased": erased}

    # ------------------------------------------------------------ retain
    @_locked
    def retain(self, user: str, text: str) -> Report:
        user = _user(user)
        raw = policy.clean(text)
        rep = Report()
        if not raw:
            return rep
        if policy.is_instruction(raw):
            rep.decisions.append(Decision("quarantined", reason="it reads like an instruction to an AI model"))
            self._audit("retain", user, decisions=[{"decision": "quarantined"}])
            return rep
        safe, rep.removed = policy.redact(raw)
        ex = self.extractor.extract(safe)
        rep.usage = ex.usage
        for what in ex.forget:
            n = self.forget(user, what=what, audit=False)
            rep.decisions.append(Decision("forgotten", key=what, reason=f"{n} memor{'y' if n == 1 else 'ies'}"))
        for c in ex.memories:
            rep.decisions.append(self._keep(user, c))
        self._audit("retain", user, removed=rep.removed, usage=rep.usage,
                    decisions=[{"decision": d.decision, "kind": d.kind, "key": d.key, "id": d.id, "reason": d.reason} for d in rep.decisions])
        return rep

    def _keep(self, user: str, c: extract.Candidate) -> Decision:
        kind = c.kind if c.kind in policy.KINDS else "fact"
        key = re.sub(r"[^a-z0-9:_-]+", "-", (c.key or "").lower())[:60].strip("-") or "note"
        text, _ = policy.redact(policy.clean(c.text or c.value))
        value, _ = policy.redact(policy.clean(c.value))
        if policy.is_instruction(text) or policy.is_instruction(value):
            return Decision("quarantined", kind, key, reason="it reads like an instruction to an AI model")
        if not value or re.fullmatch(r"(\[[a-z]+ removed\]\s*)+", value):
            return Decision("skipped", kind, key, reason="nothing left once personal numbers were removed")
        cat = policy.category(f"{text} {value} {key}", c.category, self.categories())
        if cat and not self.has_consent(user, cat):
            return Decision("skipped", kind, key, reason=f"{cat} details are kept only with consent")
        now = self.now()
        with self._tx():
            if kind in UNKEYED or key == "note":
                same = self.con.execute("SELECT id FROM memories WHERE user=? AND key=? AND lower(text)=lower(?) AND valid_to IS NULL",
                                        (user, key, text)).fetchone()
                if same:
                    return Decision("same", kind, key, same["id"], value)
                mid = self._insert(user, kind, key, value, text, cat, now)
                return Decision("added", kind, key, mid, value)
            cur = self.con.execute("SELECT * FROM memories WHERE user=? AND key=? AND valid_to IS NULL", (user, key)).fetchone()
            if cur and cur["value"].lower() == value.lower():
                self.con.execute("UPDATE memories SET observed=? WHERE id=?", (now, cur["id"]))
                return Decision("same", kind, key, cur["id"], value)
            mid = self._insert(user, kind, key, value, text, cat, now)
            if cur:
                self.con.execute("UPDATE memories SET valid_to=?, superseded_by=? WHERE id=?", (now, mid, cur["id"]))
                return Decision("updated", kind, key, mid, value, reason=f"was {cur['value']}; kept as history")
            return Decision("added", kind, key, mid, value)

    def _insert(self, user, kind, key, value, text, cat, now) -> int:
        return self.con.execute("INSERT INTO memories(user, kind, key, value, text, category, observed, source) VALUES (?,?,?,?,?,?,?,?)",
                                (user, kind, key, value, text, cat, now, getattr(self.extractor, "name", "stub"))).lastrowid

    # ------------------------------------------------------------ recall
    @_locked
    def recall(self, user: str, query: str, k: int | None = None, history: bool | None = None) -> list[Hit]:
        user = _user(user)
        q = policy.clean(query)
        k = int(k or self.cfg["recall"]["k"])
        hist = bool(HISTORY.search(q)) if history is None else history
        keys = intent_keys(q)
        want = terms(q)
        scored: dict[int, Hit] = {}

        def add(row, score, is_hist=False):
            if row["id"] not in scored or scored[row["id"]].score < score:
                scored[row["id"]] = Hit(row["id"], row["kind"], row["key"], row["value"], row["text"], round(score, 3), is_hist, row["observed"])

        if want:
            match = " OR ".join(f'"{t}"*' for t in want)
            rows = self.con.execute("SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? "
                                    "AND m.user=? AND m.valid_to IS NULL LIMIT 100", (match, user)).fetchall()
            for r in rows:
                have = set(terms(f"{r['text']} {r['value']}"))
                cover = sum(1 for t in want if t in have) / len(want)
                add(r, 0.6 * cover + (0.4 if any(_key_hit(r["key"], x) for x in keys) else 0))
        for key in keys:
            like = key + "%" if key.endswith(":") else key
            cond = "valid_to IS NOT NULL" if hist else "valid_to IS NULL"
            for r in self.con.execute(f"SELECT * FROM memories WHERE user=? AND key LIKE ? AND {cond} ORDER BY observed DESC", (user, like)).fetchall():
                add(r, 0.95 if hist else 0.9, hist)
        hits = sorted(scored.values(), key=lambda h: (h.score, h.observed), reverse=True)[:k]
        if hits:
            now = self.now()
            with self._tx():
                for h in hits:
                    self.con.execute("UPDATE memories SET uses=uses+1, last_used=? WHERE id=?", (now, h.id))
        self._audit("recall", user, ids=[h.id for h in hits], history=hist)
        return hits

    # ------------------------------------------------------------ forget, export, retention
    @_locked
    def forget(self, user: str, what: str | None = None, memory_id: int | None = None, everything: bool = False, audit: bool = True) -> int:
        user = _user(user)
        with self._tx():
            if everything or (what or "").strip().lower() == "all":
                n = self.con.execute("DELETE FROM memories WHERE user=?", (user,)).rowcount
            elif memory_id is not None:            # one memory; for a keyed one, its history goes with it
                row = self.con.execute("SELECT kind, key FROM memories WHERE id=? AND user=?", (memory_id, user)).fetchone()
                if row is None:
                    n = 0
                elif row["kind"] in UNKEYED or row["key"] == "note":
                    n = self.con.execute("DELETE FROM memories WHERE id=? AND user=?", (memory_id, user)).rowcount
                else:
                    n = self.con.execute("DELETE FROM memories WHERE user=? AND key=?", (user, row["key"])).rowcount
            else:
                w = (what or "").strip().lower()
                if not w:
                    raise MemError("Say what to forget: a key (location), a memory id, or everything.")
                n = self.con.execute("DELETE FROM memories WHERE user=? AND (key=? OR key LIKE ?)", (user, w, w + ":%")).rowcount
                if n == 0 and len(w) >= 3:          # the person's own words: forget memories that say them
                    n = self.con.execute("DELETE FROM memories WHERE user=? AND (instr(lower(text), ?) > 0 OR instr(lower(value), ?) > 0)",
                                         (user, w, w)).rowcount
        if n:
            self._compact()
        if audit:
            self._audit("forget", user, count=n, everything=bool(everything))
        return n

    def _compact(self) -> None:
        """After an erasure, rebuild the full-text index's segments, so the forgotten words leave the index as well as
        the table; secure_delete overwrites the pages they were on."""
        self.con.execute("INSERT INTO memories_fts(memories_fts) VALUES ('optimize')")

    @_locked
    def export(self, user: str) -> dict:
        user = _user(user)
        mems = [dict(r) for r in self.con.execute("SELECT id, kind, key, value, text, category, observed, valid_to, superseded_by, source "
                                                  "FROM memories WHERE user=? ORDER BY key, observed", (user,))]
        cons = [dict(r) for r in self.con.execute("SELECT category, granted FROM consents WHERE user=?", (user,))]
        self._audit("export", user, count=len(mems))
        return {"user": user, "exported": self.now(), "memories": mems, "consents": cons}

    @_locked
    def purge(self) -> int:
        """Delete what has outlived its kind's retention (mem.toml [retention], in days; 0 keeps it)."""
        n = 0
        with self._tx():
            for kind, days in self.cfg["retention"].items():
                if days and int(days) > 0:
                    n += self.con.execute("DELETE FROM memories WHERE kind=? AND observed < ?", (kind, self.now() - int(days) * 86400)).rowcount
        if n:
            self._compact()
        self._audit("purge", "*", count=n)
        return n


def _key_hit(key: str, want: str) -> bool:
    return key.startswith(want) if want.endswith(":") else key == want
