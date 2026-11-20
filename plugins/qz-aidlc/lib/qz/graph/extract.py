"""Read one source file and say what is in it: symbols, imports, calls, inheritance and routes.

Python is parsed with the standard library's own parser, so definitions, line ranges and imports are exact.
JavaScript, TypeScript, C# and Go are read with a comment-and-string-aware scanner and patterns: good for
functions, classes, methods, imports and calls by name; it does not understand types or dynamic dispatch.
Nothing here executes the file it reads."""
from __future__ import annotations

import ast
import re

LANGS = {".py": "python", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js", ".cs": "csharp", ".go": "go"}
TEST = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e|testing)/|(^|/)test_[\w-]+\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.cs$")
ROUTE_VERBS = {"get", "post", "put", "delete", "patch", "route", "websocket", "head", "options"}
KEYWORDS = set("if for while switch catch function return typeof new await yield else do try finally throw case in of delete void instanceof import export default class extends super this "
               "var let const async static get set using lock foreach fixed checked unchecked sizeof nameof when where select from go defer func range chan map make len cap append panic "
               "print println require module constructor".split())


def _sym(kind, name, qual, line, end, sig="", doc="", exported=True, default=False):
    return {"kind": kind, "name": name, "qual": qual, "line": line, "end": max(end, line), "sig": sig[:160], "doc": doc[:160], "exported": exported, "default": default}


# ---------------------------------------------------------------- Python
def _py_module(path: str, level: int, module: str | None) -> str:
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    pkg = parts[:-1] if not path.endswith("__init__.py") else parts
    base = pkg[: len(pkg) - (level - 1)] if level else []
    return ".".join([*base, *(module.split(".") if module else [])]) if level else (module or "")


def python(path: str, text: str) -> dict:
    out = {"symbols": [], "imports": [], "calls": [], "extends": [], "routes": []}
    tree = ast.parse(text)

    def calls_in(body_nodes, src):
        stack = list(body_nodes)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue                                   # its own symbol collects its own calls
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    out["calls"].append({"src": src, "name": f.id, "recv": "", "line": n.lineno})
                elif isinstance(f, ast.Attribute):
                    out["calls"].append({"src": src, "name": f.attr, "recv": f.value.id if isinstance(f.value, ast.Name) else "?", "line": n.lineno})   # "?": a method call on something unnamed
            stack.extend(ast.iter_child_nodes(n))

    def visit(nodes, prefix, in_class):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{n.name}"
                try:
                    sig = f"def {n.name}({ast.unparse(n.args)})"
                except Exception:
                    sig = f"def {n.name}(...)"
                out["symbols"].append(_sym("method" if in_class else "function", n.name, qual, n.lineno, n.end_lineno or n.lineno, sig, (ast.get_docstring(n) or "").split("\n")[0], not n.name.startswith("_")))
                for d in n.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_VERBS and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                        out["routes"].append({"method": d.func.attr.upper(), "path": d.args[0].value, "handler": qual, "line": d.lineno})
                calls_in(n.body, qual)
                visit(n.body, qual + ".", False)
            elif isinstance(n, ast.ClassDef):
                qual = f"{prefix}{n.name}"
                out["symbols"].append(_sym("class", n.name, qual, n.lineno, n.end_lineno or n.lineno, f"class {n.name}", (ast.get_docstring(n) or "").split("\n")[0], not n.name.startswith("_")))
                for b in n.bases:
                    name = b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
                    if name:
                        out["extends"].append({"src": qual, "name": name, "line": n.lineno})
                calls_in([x for x in n.body if not isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], qual)
                visit(n.body, qual + ".", True)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    out["imports"].append({"module": a.name, "name": "", "alias": a.asname or a.name.split(".")[0], "line": n.lineno})
            elif isinstance(n, ast.ImportFrom):
                mod = _py_module(path, n.level, n.module)
                for a in n.names:
                    out["imports"].append({"module": mod, "name": a.name, "alias": a.asname or a.name, "line": n.lineno})
            elif isinstance(n, (ast.If, ast.Try, ast.With)) and not prefix:        # imports and definitions under "if TYPE_CHECKING", try/except
                visit([c for c in ast.iter_child_nodes(n) if isinstance(c, ast.stmt)], prefix, in_class)

    visit(tree.body, "", False)
    calls_in([n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))], "")
    return out


# ---------------------------------------------------------------- C-family scanner
def mask(text: str, go: bool = False) -> tuple[str, str]:
    """Return (code with comments and string contents blanked, code with only comments blanked). Lengths and line breaks are kept."""
    a, b = list(text), list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//" and (i == 0 or text[i - 1] != "\\"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                a[k] = b[k] = " "
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != "\n":
                    a[k] = b[k] = " "
            i = j
        elif go and c == "'":                              # a Go rune literal
            j = text.find("'", i + 1, i + 8)
            i = j + 1 if j > 0 else i + 1
        elif c in "\"'`":
            raw = go and c == "`"
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\" and not raw:
                    j += 1
                elif text[j] == "\n" and c != "`":
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                if text[k] != "\n":
                    a[k] = " "
            i = j + 1
        else:
            i += 1
    return "".join(a), "".join(b)


def _close(code: str, open_at: int) -> int:
    depth = 0
    for i in range(open_at, len(code)):
        ch = code[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(code) - 1


def _line(starts: list[int], pos: int) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


IDENT = r"[A-Za-z_$][\w$]*"
JS_FUNC = re.compile(rf"(?P<exp>export\s+(?P<def>default\s+)?)?(?:async\s+)?function\s*\*?\s*(?P<name>{IDENT})\s*(?:<[^>(]*>)?\s*\(")
JS_ARROW = re.compile(rf"(?P<exp>export\s+)?(?:const|let|var)\s+(?P<name>{IDENT})\s*(?::[^=;]+)?=\s*(?:async\s*)?(?:function\b|(?:<[^>(]*>\s*)?(?:\([^()]*(?:\([^()]*\)[^()]*)*\)|{IDENT})\s*(?::\s*[^=;{{]+?)?=>)")
JS_CLASS = re.compile(rf"(?P<exp>export\s+(?P<def>default\s+)?)?(?:abstract\s+)?class\s+(?P<name>{IDENT})(?:\s*<[^>{{]*>)?(?:\s+extends\s+(?P<base>[\w$.]+))?(?:\s*<[^>{{]*>)?(?:\s+implements\s+(?P<impl>[\w$.,\s<>]+?))?\s*\{{")
JS_TYPE = re.compile(rf"(?P<exp>export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+(?P<name>{IDENT})")
JS_METHOD = re.compile(rf"(?:^|[;{{}}])\s*(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*\*?\s*(?P<name>#?{IDENT})\s*(?:<[^>(]*>)?\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*(?::\s*[^{{;=]+?)?\s*\{{", re.M)
CALL = re.compile(rf"(?:(?P<recv>{IDENT})\s*\??\.\s*)?(?P<name>{IDENT})\s*(?:<[\w$,\s.<>\[\]]*>)?\s*\(")
JSX = re.compile(r"<([A-Z][\w$]*)[\s/>]")
JS_IMPORT = [re.compile(r"\bimport\s+(?:type\s+)?(?P<what>[^'\";]+?)\s+from\s*['\"](?P<mod>[^'\"]+)['\"]"), re.compile(r"\bimport\s*['\"](?P<mod>[^'\"]+)['\"]"),
             re.compile(r"\bexport\s+(?P<what>\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s*from\s*['\"](?P<mod>[^'\"]+)['\"]"),
             re.compile(r"\b(?:const|let|var)\s+(?P<what>\{[^}]*\}|[\w$]+)\s*=\s*(?:await\s+)?require\(\s*['\"](?P<mod>[^'\"]+)['\"]\s*\)"), re.compile(r"\bimport\(\s*['\"](?P<mod>[^'\"]+)['\"]\s*\)")]
JS_ROUTE = re.compile(r"\b(?:app|router|\w*[Rr]outer|api|server)\.(get|post|put|delete|patch|all)\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*(?:[\w$.]+\s*,\s*)*([\w$]+)?")
CS_TYPE = re.compile(r"\b(?P<kind>class|interface|record|struct)\s+(?P<name>[A-Z_]\w*)(?:\s*<[^>{]*>)?(?:\s*\([^)]*\))?(?:\s*:\s*(?P<bases>[^{]+?))?\s*(?:where\b[^{]*)?\{")
CS_METHOD = re.compile(r"(?:^|[;{}\]])\s*(?:(?:public|private|protected|internal|static|async|override|virtual|abstract|sealed|partial|new|extern|unsafe)\s+)+(?:[\w<>\[\],.?()\s]+?\s+)?(?P<name>[A-Za-z_]\w*)\s*(?:<[^>(]*>)?\s*\((?P<args>[^()]*(?:\([^()]*\)[^()]*)*)\)\s*(?:where\b[^{;=]*)?(?:\{|=>)", re.M)
GO_FUNC = re.compile(r"^func\s+(?:\(\s*\w*\s*\*?(?P<recv>\w+)[^)]*\)\s*)?(?P<name>\w+)\s*(?:\[[^\]]*\])?\s*\(", re.M)
GO_TYPE = re.compile(r"^type\s+(?P<name>\w+)\s+(?P<kind>struct|interface)\b", re.M)


def _names(what: str) -> list[tuple[str, str]]:
    """Parse the names of a JavaScript import: default, { a, b as c }, * as ns."""
    out = []
    what = what.strip()
    m = re.search(r"\{([^}]*)\}", what)
    if m:
        for part in m.group(1).split(","):
            p = re.sub(r"^\s*type\s+", "", part).strip()
            if p:
                bits = re.split(r"\s+as\s+|\s*:\s*", p)
                out.append((bits[0].strip(), bits[-1].strip()))
        what = (what[:m.start()] + what[m.end():]).strip(" ,")
    m = re.search(r"\*\s+as\s+([\w$]+)", what)
    if m:
        out.append(("*", m.group(1)))
        what = (what[:m.start()] + what[m.end():]).strip(" ,")
    if re.fullmatch(IDENT, what or ""):
        out.append(("default", what))
    return out


def clike(path: str, text: str, lang: str) -> dict:
    out = {"symbols": [], "imports": [], "calls": [], "extends": [], "routes": []}
    code, nocomment = mask(text, go=lang == "go")
    starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
    line = lambda pos: _line(starts, pos)  # noqa: E731
    ranges = []                                        # (start, end, qual) for attributing calls

    def add(kind, name, qual, at, body_open, sig, exported=True, default=False):
        if body_open is not None and 0 <= body_open < len(code) and code[body_open] == "{":
            end = _close(code, body_open)
        elif body_open is not None and 0 <= body_open < len(code) and code[body_open] == "(":      # an arrow function that returns an expression in brackets
            end = _paren_end(code, body_open, 60000)
        else:
            end = code.find("\n", at) if code.find("\n", at) > 0 else len(code) - 1
        out["symbols"].append(_sym(kind, name, qual, line(at), line(end), sig, "", exported, default))
        if kind != "type":
            ranges.append((at, end, qual))
        return end

    def brace_after(pos):
        j = pos
        while j < len(code) and code[j] in " \t\r\n":
            j += 1
        return j if j < len(code) and code[j] in "{(" else None

    if lang == "js":
        classes = []
        for m in JS_CLASS.finditer(code):
            end = add("class", m["name"], m["name"], m.start(), m.end() - 1, text[m.start():m.end() - 1].strip(), bool(m["exp"]) or True, bool(m["def"]))
            classes.append((m.end() - 1, end, m["name"]))
            for base in filter(None, [m["base"], *(re.split(r"\s*,\s*", re.sub(r"<[^>]*>", "", m["impl"])) if m["impl"] else [])]):
                out["extends"].append({"src": m["name"], "name": base.split(".")[-1].strip(), "line": line(m.start())})
        for m in JS_FUNC.finditer(code):
            add("function", m["name"], m["name"], m.start(), code.find("{", _paren_end(code, m.end() - 1)), text[m.start():m.end()].strip() + "…)", True, bool(m["def"]))
        for m in JS_ARROW.finditer(code):
            tail = m.end()
            fexpr = code[m.start():m.end()].rstrip().endswith("function")
            add("function", m["name"], m["name"], m.start(), code.find("{", _paren_end(code, max(code.find("(", tail), tail))) if fexpr else brace_after(tail), text[m.start():m.end()].strip()[:150], True)
        for m in JS_TYPE.finditer(code):
            add("type", m["name"], m["name"], m.start(), None, text[m.start():m.end()].strip(), True)
        for open_at, end, cname in classes:
            body = code[open_at + 1:end]
            for m in JS_METHOD.finditer(body):
                name = m["name"]
                if name in KEYWORDS and name != "constructor":
                    continue
                at = open_at + 1 + m.start("name")
                if body.count("{", 0, m.start("name")) - body.count("}", 0, m.start("name")) != 0:
                    continue                           # inside another method's body
                add("method", name, f"{cname}.{name}", at, open_at + 1 + m.end() - 1, text[at:open_at + 1 + m.end() - 1].strip(), not name.startswith(("_", "#")))
        for rx in JS_IMPORT:
            for m in rx.finditer(nocomment):
                if code[m.start()] == " " and nocomment[m.start()] != " ":
                    continue                           # the match starts inside a string
                names = _names(m.groupdict().get("what") or "") or [("", "")]
                for name, alias in names:
                    out["imports"].append({"module": m["mod"], "name": name, "alias": alias, "line": line(m.start())})
        for m in JS_ROUTE.finditer(nocomment):
            out["routes"].append({"method": m[1].upper(), "path": m[2], "handler": m[3] or "", "line": line(m.start())})
        for m in JSX.finditer(code):
            out["calls"].append({"pos": m.start(), "name": m[1], "recv": "", "line": line(m.start())})
    elif lang == "csharp":
        types = []
        for m in CS_TYPE.finditer(code):
            end = add("class", m["name"], m["name"], m.start(), m.end() - 1, text[m.start():m.end() - 1].strip(), True)
            types.append((m.end() - 1, end, m["name"]))
            for base in re.split(r"\s*,\s*", re.sub(r"<[^>]*>", "", m["bases"] or "")):
                if base.strip():
                    out["extends"].append({"src": m["name"], "name": base.strip().split(".")[-1], "line": line(m.start())})
        for open_at, end, cname in types:
            body = code[open_at + 1:end]
            for m in CS_METHOD.finditer(body):
                name = m["name"]
                if name in KEYWORDS or body.count("{", 0, m.start("name")) - body.count("}", 0, m.start("name")) != 0:
                    continue
                at = open_at + 1 + m.start("name")
                opener = open_at + 1 + m.end() - 1
                add("method", name, f"{cname}.{name}", at, opener if code[opener] == "{" else None, f"{name}({' '.join(m['args'].split())})", True)
        for m in re.finditer(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", nocomment, re.M):
            out["imports"].append({"module": m[1], "name": "", "alias": m[1].split(".")[-1], "line": line(m.start())})
        ns = re.search(r"\bnamespace\s+([\w.]+)", code)
        out["namespace"] = ns[1] if ns else ""
    elif lang == "go":
        for m in GO_TYPE.finditer(code):
            add("class", m["name"], m["name"], m.start(), code.find("{", m.end()), text[m.start():m.end()].strip(), m["name"][:1].isupper())
        for m in GO_FUNC.finditer(code):
            qual = f"{m['recv']}.{m['name']}" if m["recv"] else m["name"]
            add("method" if m["recv"] else "function", m["name"], qual, m.start(), code.find("{", _paren_end(code, m.end() - 1)), text[m.start():m.end()].strip() + "…)", m["name"][:1].isupper())
        for m in re.finditer(r"^import\s+(?:\w+\s+)?\"([^\"]+)\"", nocomment, re.M):
            out["imports"].append({"module": m[1], "name": "", "alias": m[1].split("/")[-1], "line": line(m.start())})
        for blk in re.finditer(r"^import\s*\(([^)]*)\)", nocomment, re.M | re.S):
            for m in re.finditer(r"(?:(\w+)\s+)?\"([^\"]+)\"", blk[1]):
                out["imports"].append({"module": m[2], "name": "", "alias": m[1] or m[2].split("/")[-1], "line": line(blk.start())})
        pk = re.search(r"^package\s+(\w+)", code, re.M)
        out["namespace"] = pk[1] if pk else ""

    declared = {(s["line"], s["name"]) for s in out["symbols"]}
    for m in CALL.finditer(code):
        name = m["name"]
        if name in KEYWORDS or (line(m.start("name")), name) in declared:
            continue
        recv = m["recv"] or ""
        if not recv and code[:m.start("name")].rstrip()[-1:] == ".":
            recv = "?"                                         # a method call on something unnamed: f().g(), a[i].g()
        out["calls"].append({"pos": m.start("name"), "name": name, "recv": recv, "line": line(m.start("name"))})
    ranges.sort(key=lambda r: r[1] - r[0])
    for c in out["calls"]:
        pos = c.pop("pos", None)
        c["src"] = next((q for s, e, q in ranges if pos is not None and s <= pos <= e), "")
    return out


def _paren_end(code: str, open_at: int, span: int = 4000) -> int:
    depth = 0
    for i in range(open_at, min(len(code), open_at + span)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return open_at


def extract(path: str, text: str) -> dict:
    lang = LANGS[path[path.rfind("."):].lower()]
    r = python(path, text) if lang == "python" else clike(path, text, lang)
    r["lang"] = lang
    return r
