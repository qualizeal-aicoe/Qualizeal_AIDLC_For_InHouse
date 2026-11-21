"""Checks on a query that ran: does it double count, does a filter name a value the data does not have, and do the
rows hold text aimed at an AI. The first two send the model back with a precise note; the third keeps that text from
ever reaching the answer step."""
from __future__ import annotations

import difflib
import re

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

INSTRUCTION = re.compile(
    r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|earlier)\b.{0,30}\b(instructions?|rules?|prompts?)\b"
    r"|\byou are now\b|\bsystem prompt\b|\bnew instructions?\b|\bact as\b.{0,20}\b(admin|system|developer)\b"
    r"|\b(tell|ask|instruct)\b.{0,20}\b(the )?user\b.{0,30}\b(send|email|share|give|enter)\b"
    r"|\b(password|api key|secret|credentials?)\b.{0,40}\b(send|email|share|reveal)\b|\b(send|email|share|reveal)\b.{0,40}\b(password|api key|credentials?)\b"
    r"|<\s*/?\s*(script|system|instructions?)\b", re.I | re.S)


def looks_like_instruction(text: str) -> bool:
    return bool(INSTRUCTION.search(str(text or "")))


CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
NATIONAL_ID = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d) * (2 if alt else 1)
        total += n - 9 if n > 9 else n
        alt = not alt
    return total % 10 == 0


def mask(text: str) -> tuple[str, int]:
    """Payment card numbers and national ID numbers out of a question before the model, the trace or the audit see it
    (gate 1). A number that fails the card checksum stays: it is an order total, not a card."""
    n = 0

    def card(m: re.Match) -> str:
        nonlocal n
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            n += 1
            return "[card number removed]"
        return m.group(0)

    text = CARD.sub(card, str(text or ""))
    text, k = NATIONAL_ID.subn("[ID number removed]", text)
    return text, n + k


def withhold(rows: list[list]) -> tuple[list[list], int]:
    """Replace any cell that reads like an instruction to an AI. The person can still see it in the database; the
    model writing the answer never does."""
    n, out = 0, []
    for r in rows:
        row = []
        for v in r:
            if isinstance(v, str) and looks_like_instruction(v):
                row.append("[withheld: this text reads like instructions to an AI]")
                n += 1
            else:
                row.append(v)
        out.append(row)
    return out, n


def _real(scope, alias):
    s = scope
    while s is not None:
        src = s.sources.get(alias)
        if isinstance(src, exp.Table):
            return src.name.lower()
        if src is not None:
            return None
        s = s.parent
    return None


def fan_out(tree: exp.Expression, keys: list[tuple[str, str, str, str]]) -> list[str]:
    """A total of a parent's column over a join to its children counts each parent row once per child row
    (freight per order, summed over order lines). keys: (child, child_column, parent, parent_column)."""
    found = []
    for scope in traverse_scope(tree):
        sel = scope.expression
        if not isinstance(sel, exp.Select):
            continue
        present = {src.name.lower() for src in scope.sources.values() if isinstance(src, exp.Table)}
        fanned = {p: c for c, _, p, _ in keys if c in present and p in present and c != p}
        if not fanned:
            continue
        for agg in sel.find_all(exp.Sum, exp.Avg, exp.Count):
            if agg.find_ancestor(exp.Select) is not sel:
                continue
            arg = agg.this
            if isinstance(agg, exp.Count) and (isinstance(arg, (exp.Star, exp.Distinct)) or arg is None):
                continue
            if isinstance(arg, exp.Distinct):
                continue
            owners = {_real(scope, c.table) for c in agg.find_all(exp.Column)}
            if len(owners) == 1:
                owner = owners.pop()
                if owner in fanned:
                    found.append(f"{agg.sql(dialect='sqlite')} counts each {owner} row once for every {fanned[owner]} row it joins to, "
                                 f"so the total is too high. Total {owner} on its own (a subquery, or join only the tables that "
                                 f"have one row per {owner}), then join.")
    return found


def values(tree: exp.Expression, lookup) -> list[dict]:
    """Filters on text that match nothing as written. lookup(table, column, literal) returns (exists, suggestions)."""
    out = []
    for scope in traverse_scope(tree):
        sel = scope.expression
        for cmp in sel.find_all(exp.EQ, exp.In):
            if cmp.find_ancestor(exp.Select) is not sel:
                continue
            col, lits = None, []
            if isinstance(cmp, exp.EQ):
                a, b = cmp.this, cmp.expression
                if isinstance(b, exp.Column) and isinstance(a, exp.Literal):
                    a, b = b, a
                if isinstance(a, exp.Column) and isinstance(b, exp.Literal) and b.is_string:
                    col, lits = a, [b.this]
            elif isinstance(cmp.this, exp.Column):
                col, lits = cmp.this, [e.this for e in cmp.expressions if isinstance(e, exp.Literal) and e.is_string]
            if col is None or not lits:
                continue
            table = _real(scope, col.table)
            if not table:
                continue
            for lit in lits:
                exists, near = lookup(table, col.name, lit)
                if not exists:
                    out.append({"column": f"{table}.{col.name}", "value": lit, "suggest": near})
    return out


def suggest(value: str, known: list[str]) -> list[str]:
    same = [k for k in known if k.lower() == value.lower()]
    return same or difflib.get_close_matches(value, known, n=3, cutoff=0.6)
