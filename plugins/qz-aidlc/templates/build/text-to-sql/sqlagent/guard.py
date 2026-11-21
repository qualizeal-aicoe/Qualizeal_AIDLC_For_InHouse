"""The SQL guard, before anything reaches the database. It parses the SQL into a tree (sqlglot) and checks the tree,
not the text, so a comment, a string or an odd spelling cannot hide a write:

- exactly one statement, and it is a query: no INSERT, UPDATE, DELETE, DDL, PRAGMA, ATTACH, VACUUM, SELECT INTO
- only tables this role may read, never the database's own catalogue or a table function
- only columns this role may read: a personal column stays out of the SELECT, the filter, the join and `SELECT *`
- no function that touches files or memory
- a LIMIT no higher than max_rows (one more row is fetched, to tell when there were more)

Blocked means a rule was broken: the agent refuses and never retries. Invalid means the SQL is wrong (it does not
parse, or names a column that does not exist): the model is told why and may try again. The database's authorizer
(db.py) enforces the same rules again inside the engine, so a gap between this parser and SQLite's cannot open one."""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

WRITES = tuple(t for t in (getattr(exp, n, None) for n in (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterColumn", "Command", "Pragma", "Attach",
    "Detach", "Transaction", "Commit", "Rollback", "Set", "Use", "Into", "LoadData", "Copy", "Grant", "Revoke",
    "TruncateTable", "Analyze", "Cache", "Uncache", "Refresh")) if isinstance(t, type))
BAD_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "randomblob", "zeroblob",
                 "sqlite_compileoption_get", "sqlite_compileoption_used", "sqlite_offset"}


class Blocked(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class Invalid(Exception):
    pass


@dataclass
class Checked:
    sql: str                                    # what will run: the model's SQL, with a LIMIT wrapped round it if needed
    tree: exp.Expression                        # qualified: every column names its table
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    limited: bool = False


def check(sql: str, schema: dict[str, dict[str, str]], allowed: set[str], deny: set[str], max_rows: int) -> Checked:
    """schema: every table in the database with its columns and types; allowed: the role's tables; deny: table.column."""
    text = (sql or "").strip()
    if not text:
        raise Invalid("No SQL was written.")
    try:
        stmts = [s for s in sqlglot.parse(text, read="sqlite") if s is not None]
    except ParseError as e:
        raise Invalid(f"The SQL does not parse: {str(e).splitlines()[0][:200]}") from None
    if len(stmts) != 1:
        raise Blocked("multi", "One statement at a time: this would run several.")
    root = stmts[0]
    for node in root.walk():
        if isinstance(node, WRITES):
            raise Blocked("write", f"This database is read-only here: {type(node).__name__.upper()} is not allowed.")
    if not isinstance(root, exp.Query):
        raise Blocked("write", f"Only queries are allowed, not {type(root).__name__.upper()}.")
    ctes = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    tables: list[str] = []
    for t in root.find_all(exp.Table):
        if isinstance(t.this, exp.Func) or not t.name:
            raise Blocked("catalogue", "Table functions are not allowed.")
        name = t.name.lower()
        if name in ctes:
            continue
        if name.startswith(("sqlite_", "pragma_")):
            raise Blocked("catalogue", "The database's own catalogue is not open to questions.")
        if name not in schema:
            raise Invalid(f"There is no table '{t.name}'. Tables: {', '.join(sorted(allowed))}.")
        if name not in allowed:
            raise Blocked("table", f"{name} is not available to this role.")
        if name not in tables:
            tables.append(name)
    for f in root.find_all(exp.Anonymous):
        if str(f.name).lower() in BAD_FUNCTIONS:
            raise Blocked("function", f"{f.name}() is not allowed.")
    try:
        tree = qualify(root.copy(), schema={t: schema[t] for t in allowed}, dialect="sqlite", validate_qualify_columns=True,
                       quote_identifiers=False)
    except OptimizeError as e:
        raise Invalid(f"{e}. Use only the columns in the schema card.") from None
    columns: list[str] = []
    for scope in traverse_scope(tree):
        for col in scope.columns:
            real = _source(scope, col.table)
            if real is None:
                continue
            ref = f"{real}.{col.name}".lower()
            if ref in deny:
                raise Blocked("personal", f"{ref} is personal data and not available to this role, not even in a filter or a join.")
            if ref not in columns:
                columns.append(ref)
    lim = root.args.get("limit")
    n = lim.expression if isinstance(lim, exp.Limit) else None
    ok = (isinstance(n, exp.Literal) and not n.is_string and int(n.this) <= max_rows) or _one_row(root)
    run = text.rstrip().rstrip(";").rstrip()
    if not ok:                                   # one row over the limit, so the agent can say there were more
        run = f"SELECT * FROM (\n{run}\n) LIMIT {int(max_rows) + 1}"
    return Checked(run, tree, tables, columns, not ok)


def _one_row(root: exp.Expression) -> bool:
    """An aggregate with no GROUP BY returns one row: it needs no LIMIT."""
    if not isinstance(root, exp.Select) or root.args.get("group") or root.args.get("distinct") or root.find(exp.Window):
        return False
    return bool(root.expressions) and all(e.find(exp.AggFunc) is not None for e in root.expressions)


def _source(scope, alias: str):
    """The real table a column comes from, looking out through the scopes for a correlated column."""
    s = scope
    while s is not None:
        src = s.sources.get(alias)
        if isinstance(src, exp.Table):
            return src.name
        if src is not None:
            return None                      # a CTE or a subquery: its own scope checked its columns
        s = s.parent
    return None


def masked(sql: str) -> str:
    """The SQL with its text values replaced by ?, for the audit log and traces: a filter can hold personal data."""
    try:
        t = sqlglot.parse_one(sql, read="sqlite")
        return t.transform(lambda n: exp.Placeholder() if isinstance(n, exp.Literal) and n.is_string else n).sql(dialect="sqlite")
    except Exception:
        return "<unparsed>"
