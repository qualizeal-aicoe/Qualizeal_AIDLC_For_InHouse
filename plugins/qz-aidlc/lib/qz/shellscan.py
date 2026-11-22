"""Reads a Bash line the way the shell will, so the guard can check every command on it.

`date -u; git push origin x` is two commands, and `echo $(git push)` runs the push too. The guard used to read only the
whole line, so an allowed first command hid what came after it. This scanner splits the line into the simple commands
it runs: across ; && || | & and new lines, inside $( ), backticks and process substitutions, in subshells and { }
groups, in here-documents fed to a shell, in `sh -c '...'`, `eval '...'`, `watch` and `env -S` with literal text, in
`find -exec`, and behind wrappers such as env, nohup, timeout, nice, stdbuf and xargs. It also marks what no rule can
read in advance:

  feeds_shell       a shell or interpreter reads its program from a pipe, a here-string or a process substitution
  dynamic           the program is named by a variable or a substitution, or eval / sh -c / python -c runs text that
                    is not written out
  unresolved_write  a write whose target the guard cannot tell: a variable path, a write run by xargs or find -exec,
                    find -delete, or any write after a cd to a folder that is not written out

Concept from opencode's shell scanner (MIT); written fresh for the Studio. Standard library only; nothing is run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_DEPTH = 6          # sh -c inside sh -c ... deeper than this is not read: treated as dynamic
MAX_NEST = 60          # $( $( ... ) ) nesting inside one line

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "yash", "rbash"}
PWSH = {"pwsh", "powershell"}
PY = re.compile(r"^(?:python[0-9.]*|py|pypy[0-9.]*)$")
INTERP = {"node", "nodejs", "bun", "tsx", "deno", "perl", "ruby", "php", "lua", "rscript"}
STDIN_PATHS = {"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
WRITE_VERBS = {"mv", "cp", "rm", "ln", "truncate", "chmod", "chown", "chgrp", "install", "rsync", "dd", "unlink",
               "shred", "touch", "mkdir", "rmdir", "tee", "rename"}
PS_WRITE = {"set-content", "add-content", "out-file", "remove-item", "move-item", "copy-item", "new-item",
            "rename-item", "clear-content"}
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "select", "case", "esac", "{",
            "}", "!", "function"}
OPENERS = {"if", "while", "until", "for", "select", "case", "{"}
CLOSERS = {"fi", "done", "esac", "}"}
# wrapper: (short options that take a value, long options that take a value)
WRAP = {
    "sudo": ("ugpCDrtThUR", {"--user", "--group", "--prompt", "--close-from", "--chdir", "--role", "--type", "--host",
                             "--other-user", "--command-timeout"}),
    "doas": ("uC", set()),
    "exec": ("a", set()),
    "builtin": ("", set()),
    "time": ("fo", {"--format", "--output"}),
    "nohup": ("", set()),
    "nice": ("n", {"--adjustment"}),
    "timeout": ("sk", {"--signal", "--kill-after"}),
    "stdbuf": ("ioe", {"--input", "--output", "--error"}),
    "setsid": ("", set()),
    "ionice": ("cnpPu", {"--class", "--classdata", "--pid", "--pgid", "--uid"}),
    "xargs": ("ILnPsdEa", {"--replace", "--max-lines", "--max-args", "--max-procs", "--max-chars", "--delimiter",
                           "--eof", "--arg-file", "--process-slot-var"}),
    "busybox": ("", set()),
    "watch": ("nd", {"--interval", "--differences"}),
}
REDIR = re.compile(r"(\d*)(<<<|<<-|<<|<>|<&|>&|>>|>\||&>>|&>|<|>)")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VAR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]|[@*#?$!\-]")
SINKS = re.compile(r"^(?:/dev/(?:null|stdout|stderr|tty|fd/\d+)|nul)$", re.I)
KNOWN = ("HOME", "USERPROFILE", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT")
KNOWN_LEAD = re.compile(r"^(?:\$\{?(HOME|USERPROFILE|CLAUDE_PROJECT_DIR|CLAUDE_PLUGIN_ROOT)\}?|\$env:(USERPROFILE|HOME))(?=$|[\\/])")
KNOWN_ANY = re.compile(r"\$\{?(?:HOME|USERPROFILE|CLAUDE_PROJECT_DIR|CLAUDE_PLUGIN_ROOT)\}?(?![A-Za-z0-9_])")
LEFT = re.compile(r"\$[A-Za-z_{(0-9@*#?!-]|`")
WORD_END = set(" \t\r\n;&|()<>")
ANSI = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "e": "\x1b", "E": "\x1b",
        "\\": "\\", "'": "'", '"': '"', "?": "?"}
ANSI_NUM = re.compile(r"x([0-9A-Fa-f]{1,2})|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})|([0-7]{1,3})|c(.)", re.S)
# an interpreter one-liner that writes files (moved here from the guard, which imports it)
WRITE_API = re.compile(r"\b(?:write\w*file\w*|append\w*file\w*|copy_?file(?:sync)?|rename(?:sync)?\s*\(|unlink(?:sync)?\s*\(|rm(?:sync)?\s*\(|create_?write_?stream|write_text|write_bytes|writealltext|writeallbytes|bun\.write|file\.write|file_put_contents|shutil\.(?:copy\w*|move|rmtree)|os\.(?:rename|replace|remove|unlink)|set-content|add-content|out-file|\[io\.file\]::write)|\bopen(?:sync)?\s*\([^)]*['\"](?:[wax]b?\+?|\+?[>]{1,2}|\+<)['\"]", re.I)


class _Unreadable(Exception):
    pass


@dataclass
class Word:
    raw: str
    text: str                 # quotes and escapes removed; expansions kept as written
    expands: bool = False     # $x, ${x}, $(...), `...`, $((...)) outside single quotes
    escaped: bool = False     # $'...' with a backslash escape in it
    procsub: bool = False     # <(...) or >(...)


@dataclass
class Part:
    raw: str = ""
    words: list = field(default_factory=list)
    assigns: list = field(default_factory=list)
    redirs: list = field(default_factory=list)        # (operator, Word or None)
    targets: list = field(default_factory=list)       # files written by redirections
    piped: bool = False                               # stdin comes from a pipe
    depth: int = 0
    start: int = 0
    heredocs: list = field(default_factory=list)      # (body, delimiter quoted)
    herestring: bool = False
    header: bool = False      # for/select/case/function headers, [[ ]] and (( )): no program runs
    fn: bool = False
    cmdpos: bool = True
    via: list = field(default_factory=list)           # wrappers in front of the program
    cmd: str = ""             # program name, lower-case base name; "?" when it is not written out
    args: list = field(default_factory=list)
    writes: bool = False
    code: str = ""            # program text given to an interpreter or shell

    @property
    def plain(self) -> str:
        bits = [w.text for w in self.assigns + self.words]
        bits += [op + (" " + w.text if w is not None else "") for op, w in self.redirs]
        return " ".join(b for b in bits if b)


@dataclass
class Scan:
    parts: list = field(default_factory=list)
    error: str = ""
    feeds_shell: str = ""
    dynamic: str = ""
    unresolved_write: str = ""
    loop: bool = False
    chdir: str = ""
    cds: list = field(default_factory=list)           # folders a cd / pushd / env -C changes to, written out
    codes: list = field(default_factory=list)
    assigned: set = field(default_factory=set)
    nest: int = 0

    @property
    def opaque(self) -> bool:
        return bool(self.feeds_shell or self.dynamic or self.unresolved_write or self.error)

    def note(self, what: str, part) -> None:
        if not getattr(self, what):
            setattr(self, what, (part.raw if isinstance(part, Part) else str(part)) or "(empty)")


class _Lex:
    def __init__(self, src: str, scan: Scan, depth: int = 0):
        self.s, self.n, self.i = src, len(src), 0
        self.scan, self.depth = scan, depth
        self.pending: list = []

    # ---------------------------------------------------------------- command lists
    def run(self, piped: bool = False) -> None:
        self.parse_list(None, piped)
        self.heredocs()

    def _part(self, piped: bool) -> Part:
        return Part(piped=piped, depth=self.depth, start=self.i)

    def _end(self, p: Part) -> None:
        if p.words or p.assigns or p.redirs:
            p.raw = self.s[p.start:self.i].strip()
            self.scan.parts.append(p)

    def parse_list(self, stop: str | None, piped_in: bool) -> None:
        groups: list[bool] = []      # piped flag of each open compound ({ }, loops, if, case)
        case: list[str] = []         # subject | pattern | body, one per open case
        inherit = lambda: piped_in or any(groups)  # noqa: E731
        p = self._part(piped_in)
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r":
                self.i += 1
                continue
            if case and case[-1] == "pattern":           # case labels are not commands
                if c == "\n":
                    self.i += 1
                    self.heredocs()
                elif c in "(|;":
                    self.i += 1
                elif c == ")":
                    self.i += 1
                    case[-1] = "body"
                    p = self._part(inherit())
                else:
                    w = self.read_word()
                    if not w.raw:
                        self.i += 1
                    elif w.raw == "esac":
                        case.pop()
                        if groups:
                            groups.pop()
                continue
            if c == "\n":
                self._end(p)
                self.i += 1
                self.heredocs()
                p = self._part(inherit())
                continue
            if c == "#":
                j = s.find("\n", self.i)
                self.i = self.n if j < 0 else j
                continue
            if c == ")":
                self._end(p)
                self.i += 1
                if stop == ")":
                    return
                p = self._part(inherit())             # a stray ) : bash reports a syntax error
                continue
            if c == ";":
                k = 3 if s.startswith(";;&", self.i) else 2 if s.startswith((";;", ";&"), self.i) else 1
                self._end(p)
                self.i += k
                if k > 1 and case and case[-1] == "body":
                    case[-1] = "pattern"
                p = self._part(inherit())
                continue
            if c == "&" and not s.startswith(("&>", "&>>"), self.i):
                self._end(p)
                self.i += 2 if s.startswith("&&", self.i) else 1
                p = self._part(inherit())
                continue
            if c == "|":
                self._end(p)
                if s.startswith("||", self.i):
                    self.i += 2
                    p = self._part(inherit())
                else:
                    self.i += 2 if s.startswith("|&", self.i) else 1
                    p = self._part(True)
                continue
            if c == "(" and p.cmdpos:
                if s.startswith("((", self.i):            # arithmetic command
                    self.i += 2
                    self._nest(self._arith)
                    p.words.append(Word("((", "(("))
                    p.header, p.cmdpos = True, False
                else:                                     # subshell: shares stdin with this part
                    self.i += 1
                    self._nest(lambda: self.parse_list(")", p.piped))
                    p.words.append(Word("(", "("))
                    p.header, p.cmdpos = True, False
                continue
            if c == "(":
                j = self.i + 1
                while j < self.n and s[j] in " \t":
                    j += 1
                if j < self.n and s[j] == ")":            # name() : a function definition
                    self.i = j + 1
                    p.header = p.fn = True
                    continue
                self.i += 1                               # a syntax error in bash: read it as a subshell
                self._nest(lambda: self.parse_list(")", p.piped))
                continue
            if (c in "<>" and not s.startswith(("<(", ">("), self.i)) or c == "&" or (c.isdigit() and self._is_redir()):
                self._redir(p)
                continue
            # a word
            if p.cmdpos and s.startswith("[[", self.i) and (self.i + 2 >= self.n or s[self.i + 2] in " \t\r\n"):
                self.i += 2
                self._nest(self._test)
                p.words.append(Word("[[", "[["))
                p.header, p.cmdpos = True, False
                continue
            w = self.read_word()
            if not w.raw:
                self.i += 1
                continue
            if p.fn and w.raw == "{":                     # function f { ... } / f() { ... } on one line
                self._end(p)
                p = self._part(inherit())
            if p.cmdpos:
                if w.raw in RESERVED:
                    p.words.append(w)
                    self._reserved(w.raw, p, groups, case)
                    continue
                if ASSIGN.match(w.raw):
                    p.assigns.append(w)
                    self.scan.assigned.add(re.split(r"[\[+=]", w.raw, maxsplit=1)[0])
                    if w.raw.endswith("=") and s.startswith("(", self.i):
                        self.i += 1
                        self._nest(self._array)
                    continue
                p.cmdpos = False
            p.words.append(w)
            if case and case[-1] == "subject" and w.raw == "in":
                case[-1] = "pattern"
                self._end(p)
                p = self._part(inherit())
        if stop == ")":
            raise _Unreadable("an unclosed ( or $(")
        self._end(p)

    def _reserved(self, r: str, p: Part, groups: list, case: list) -> None:
        if r in OPENERS:
            groups.append(p.piped)
        if r in ("while", "until", "for", "select"):
            self.scan.loop = True
        if r in ("for", "select", "case", "function"):
            p.header, p.cmdpos = True, False
            p.fn = r == "function"
        if r == "case":
            case.append("subject")
        if r in CLOSERS and groups:
            groups.pop()
        if r == "esac" and case:
            case.pop()

    def _is_redir(self) -> bool:
        m = REDIR.match(self.s, self.i)
        return bool(m and m.group(1))

    def _redir(self, p: Part) -> None:
        m = REDIR.match(self.s, self.i)
        if not m:
            raise _Unreadable("a redirection")
        op = m.group(2)
        self.i = m.end()
        while self.i < self.n and self.s[self.i] in " \t":
            self.i += 1
        w = self.read_word() if self.i < self.n and self.s[self.i] not in "\n;&|)" else None
        if op in ("<<", "<<-"):
            if w is None:
                raise _Unreadable("a here-document without a delimiter")
            self.pending.append((w.text, op == "<<-", any(q in w.raw for q in "'\"\\"), p))
        elif op == "<<<":
            p.herestring = True
        elif op in (">&", "<&") and w is not None and re.fullmatch(r"\d+-?|-", w.text):
            p.redirs.append((op, None))                   # duplicating a descriptor writes no file
            return
        p.redirs.append((op, w))
        if op in (">", ">>", ">|", "&>", "&>>", "<>", ">&") and w is not None and not SINKS.match(w.text):
            p.targets.append(w)

    def heredocs(self) -> None:
        while self.pending:
            delim, strip, quoted, p = self.pending.pop(0)
            lines = []
            while self.i < self.n:
                j = self.s.find("\n", self.i)
                end = self.n if j < 0 else j
                line = self.s[self.i:end]
                self.i = self.n if j < 0 else j + 1
                if (line.lstrip("\t") if strip else line).rstrip("\r") == delim:
                    break
                lines.append(line)
            body = "\n".join(lines)
            p.heredocs.append((body, quoted))
            if not quoted:
                self._expansions(body)

    # ---------------------------------------------------------------- words
    def read_word(self) -> Word:
        s, start = self.s, self.i
        if s.startswith(("<(", ">("), self.i):
            self.i += 2
            self._nest(lambda: self.parse_list(")", False))
            return Word(s[start:self.i], s[start:self.i], True, False, True)
        out: list[str] = []
        expands = escaped = False
        while self.i < self.n:
            c = s[self.i]
            if c in WORD_END:
                break
            if c == "\\":
                if self.i + 1 < self.n and s[self.i + 1] != "\n":
                    out.append(s[self.i + 1])
                self.i += 2
                continue
            if c == "'":
                j = s.find("'", self.i + 1)
                if j < 0:
                    raise _Unreadable("an unclosed '")
                out.append(s[self.i + 1:j])
                self.i = j + 1
                continue
            if c == '"':
                self.i += 1
                expands |= self._dquote(out)
                continue
            if c == "$":
                kind, text, esc = self._dollar(False)
                out.append(text)
                expands |= kind != "plain"
                escaped |= esc
                continue
            if c == "`":
                out.append(self._backtick())
                expands = True
                continue
            out.append(c)
            self.i += 1
        return Word(s[start:self.i], "".join(out), expands, escaped)

    def _dquote(self, out: list) -> bool:
        exp = False
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c == '"':
                self.i += 1
                return exp
            if c == "\\" and self.i + 1 < self.n:
                nx = s[self.i + 1]
                if nx in '$`"\\\n':
                    if nx != "\n":
                        out.append(nx)
                    self.i += 2
                    continue
                out.append(c)
                self.i += 1
                continue
            if c == "$":
                kind, text, _ = self._dollar(True)
                out.append(text)
                exp |= kind != "plain"
                continue
            if c == "`":
                out.append(self._backtick())
                exp = True
                continue
            out.append(c)
            self.i += 1
        raise _Unreadable('an unclosed "')

    def _dollar(self, in_dq: bool):
        s, i = self.s, self.i
        nx = s[i + 1:i + 2]
        if nx == "(":
            if s.startswith("((", i + 1):
                self.i = i + 3
                self._nest(self._arith)
                return "arith", s[i:self.i], False
            self.i = i + 2
            self._nest(lambda: self.parse_list(")", False))
            return "cmd", s[i:self.i], False
        if nx == "{":
            self.i = i + 2
            self._nest(self._param)
            return "param", s[i:self.i], False
        if nx == "'" and not in_dq:
            self.i, text, esc = self._ansi(i + 2)
            return "plain", text, esc
        if nx == '"' and not in_dq:
            self.i = i + 1
            return "plain", "", False
        m = VAR.match(s, i + 1)
        if m:
            self.i = m.end()
            return "var", s[i:self.i], False
        self.i = i + 1
        return "plain", "$", False

    def _ansi(self, j: int):
        s, out, esc = self.s, [], False
        while j < self.n:
            c = s[j]
            if c == "'":
                return j + 1, "".join(out), esc
            if c == "\\" and j + 1 < self.n:
                esc = True
                nx = s[j + 1]
                if nx in ANSI:
                    out.append(ANSI[nx])
                    j += 2
                    continue
                m = ANSI_NUM.match(s, j + 1)
                if m:
                    g = m.groups()
                    try:
                        out.append(chr(int(g[0], 16)) if g[0] else chr(int(g[1], 16)) if g[1] else
                                   chr(int(g[2], 16)) if g[2] else chr(int(g[3], 8)) if g[3] else chr(ord(g[4]) & 31))
                    except (ValueError, OverflowError):
                        out.append("?")
                    j = m.end()
                    continue
                out.append(nx)
                j += 2
                continue
            out.append(c)
            j += 1
        raise _Unreadable("an unclosed $'")

    def _param(self) -> None:
        depth, s = 1, self.s
        while self.i < self.n:
            c = s[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "'":
                j = s.find("'", self.i + 1)
                if j < 0:
                    raise _Unreadable("an unclosed '")
                self.i = j + 1
                continue
            if c == '"':
                self.i += 1
                self._dquote([])
                continue
            if c == "$":
                self._dollar(True)
                continue
            if c == "`":
                self._backtick()
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return
            self.i += 1
        raise _Unreadable("an unclosed ${")

    def _arith(self) -> None:
        depth, s = 2, self.s
        while self.i < self.n:
            c = s[self.i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return
            elif c == "$":
                self._dollar(True)
                continue
            elif c == "`":
                self._backtick()
                continue
            elif c == '"':
                self.i += 1
                self._dquote([])
                continue
            elif c == "'":
                j = s.find("'", self.i + 1)
                if j < 0:
                    raise _Unreadable("an unclosed '")
                self.i = j + 1
                continue
            self.i += 1
        raise _Unreadable("an unclosed ((")

    def _test(self) -> None:
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
                continue
            if s.startswith("]]", self.i) and (self.i + 2 >= self.n or s[self.i + 2] in " \t\r\n;&|)"):
                self.i += 2
                return
            if c in "()<>&|!;":
                self.i += 1
                continue
            if not self.read_word().raw:
                self.i += 1
        raise _Unreadable("an unclosed [[")

    def _array(self) -> None:
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
                continue
            if c == ")":
                self.i += 1
                return
            if c == "#":
                j = s.find("\n", self.i)
                self.i = self.n if j < 0 else j
                continue
            if not self.read_word().raw:
                self.i += 1
        raise _Unreadable("an unclosed (")

    def _backtick(self) -> str:
        s, start, j, buf = self.s, self.i, self.i + 1, []
        while j < self.n:
            c = s[j]
            if c == "\\" and j + 1 < self.n and s[j + 1] in "`\\$":
                buf.append(s[j + 1])
                j += 2
                continue
            if c == "`":
                break
            buf.append(c)
            j += 1
        else:
            raise _Unreadable("an unclosed `")
        self.i = j + 1
        self.sub("".join(buf), None)
        return s[start:self.i]

    def _expansions(self, body: str) -> None:
        """An unquoted here-document still runs the $( ) and backticks in it."""
        if self.depth + 1 > MAX_DEPTH:
            self.scan.note("dynamic", "a here-document nested deeper than the guard reads")
            return
        lx = _Lex(body, self.scan, self.depth + 1)
        while lx.i < lx.n:
            c = body[lx.i]
            if c == "\\":
                lx.i += 2
            elif c == "$":
                lx._dollar(True)
            elif c == "`":
                lx._backtick()
            else:
                lx.i += 1

    def _nest(self, fn) -> None:
        self.scan.nest += 1
        if self.scan.nest > MAX_NEST:
            raise _Unreadable("nesting deeper than the guard reads")
        try:
            fn()
        finally:
            self.scan.nest -= 1

    def sub(self, text: str, parent: Part | None, piped: bool = False) -> None:
        if self.depth + 1 > MAX_DEPTH:
            self.scan.note("dynamic", parent or "text nested deeper than the guard reads")
            return
        _Lex(text, self.scan, self.depth + 1).run(piped)


# -------------------------------------------------------------------- what each command does

def _base(text: str) -> str:
    b = re.split(r"[\\/]", text)[-1].lower()
    return re.sub(r"\.(exe|cmd|bat|com)$", "", b)


def _resolved(w: Word, sc: Scan) -> bool:
    """A word the guard can read before it runs: no expansion, or only a leading $HOME-like known folder."""
    if not w.expands:
        return True
    m = KNOWN_LEAD.match(w.text)
    if not m or (m.group(1) or m.group(2)) in sc.assigned:
        return False
    return not LEFT.search(w.text[m.end():])


def _literal(w: Word, sc: Scan) -> bool:
    """Program text with nothing the shell fills in, apart from known folders."""
    if not w.expands:
        return True
    if any(k in sc.assigned for k in KNOWN):
        return False
    return not LEFT.search(KNOWN_ANY.sub("", w.text))


def _opts(ws: list, i: int, short_val: str, long_val: set) -> int:
    while i < len(ws):
        t = ws[i].text
        if t == "--":
            return i + 1
        if t.startswith("--") and len(t) > 2:
            i += 1 if ("=" in t or t not in long_val) else 2
            continue
        if t.startswith("-") and len(t) > 1:
            j, takes_next = 1, False
            while j < len(t):
                if t[j] in short_val:
                    takes_next = j == len(t) - 1
                    break
                j += 1
            i += 2 if takes_next else 1
            continue
        return i
    return i


def _env(ws: list, i: int, p: Part, sc: Scan, lx: _Lex) -> tuple[int, bool]:
    while i < len(ws):
        w, t = ws[i], ws[i].text
        if t in ("-", "-i", "--ignore-environment", "-0", "--null", "-v", "--debug"):
            i += 1
        elif t in ("-u", "--unset"):
            i += 2
        elif t.startswith(("--unset=", "-u")):
            i += 1
        elif t in ("-C", "--chdir") or t.startswith("--chdir="):
            d = Word(t[8:], t[8:], w.expands) if "=" in t else (ws[i + 1] if i + 1 < len(ws) else None)
            if d is not None and not _resolved(d, sc):
                sc.note("chdir", p)
            elif d is not None:
                sc.cds.append(d.text)
            i += 1 if "=" in t else 2
        elif t in ("-S", "--split-string") or t.startswith("--split-string="):
            rest = ws[i + 1:] if "=" not in t else [Word(t[15:], t[15:], w.expands)] + ws[i + 1:]
            if rest and all(_literal(x, sc) for x in rest):
                lx.sub(" ".join(x.text for x in rest), p, p.piped)
            elif rest:
                sc.note("dynamic", p)
            p.cmd = "env"
            return len(ws), True
        elif t.startswith("-"):
            i += 1
        elif ASSIGN.match(w.raw):
            sc.assigned.add(re.split(r"[\[+=]", w.raw, maxsplit=1)[0])
            i += 1
        else:
            return i, False
    return i, False


def _shell_args(a: list):
    """(program word for -c, reads its program from stdin, the words after the options)"""
    i, c_flag, s_flag = 0, False, False
    while i < len(a):
        t = a[i].text
        if t in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 2
            continue
        if t == "--":
            i += 1
            break
        if t.startswith("--"):
            i += 1
            continue
        if len(t) > 1 and t[0] in "-+":
            if t[0] == "-" and "c" in t[1:]:
                c_flag = True
            if t[0] == "-" and "s" in t[1:]:
                s_flag = True
            i += 1
            continue
        break
    rest = a[i:]
    if c_flag:
        return (rest[0] if rest else None), False, rest[1:]
    return None, s_flag or not rest or rest[0].text in STDIN_PATHS, rest


def _interp_args(kind: str, a: list):
    """(code word, reads its program from stdin, edits files in place, the words after the options)"""
    i, code, inplace = 0, None, False
    while i < len(a):
        t = a[i].text
        nxt = a[i + 1] if i + 1 < len(a) else None
        if t == "--":
            i += 1
            break
        if t in ("--version", "-v", "-V", "--help", "-h") and kind in ("python", "node", "nodejs", "bun", "deno", "tsx", "ruby", "php", "lua"):
            return None, False, False, []                  # prints and exits: no program runs
        if kind == "python":
            if t.startswith("-") and not t.startswith("--") and len(t) > 1:
                j, step = 1, 1
                while j < len(t):
                    ch = t[j]
                    if ch == "c":
                        if j + 1 < len(t):
                            return Word(t[j + 1:], t[j + 1:], a[i].expands), False, False, a[i + 1:]
                        return nxt, False, False, a[i + 2:]
                    if ch == "m":
                        return None, False, False, []      # a module is named: not a program from stdin
                    if ch in "WXQ":
                        step = 1 if j + 1 < len(t) else 2
                        break
                    j += 1
                i += step
                continue
            if t.startswith("--"):
                i += 1
                continue
            break
        if kind in ("node", "nodejs", "bun", "tsx"):
            if t in ("-e", "--eval", "-p", "--print"):
                return nxt, False, False, a[i + 2:]
            if t.startswith(("--eval=", "--print=")):
                v = t.split("=", 1)[1]
                return Word(v, v, a[i].expands), False, False, a[i + 1:]
            if t in ("-r", "--require", "--import", "--loader", "-C", "--conditions"):
                i += 2
                continue
            if t.startswith("-"):
                i += 1
                continue
            break
        if kind == "deno":
            if t == "eval":
                return nxt, False, False, a[i + 2:]
            if t == "run" or t.startswith("-"):
                i += 1
                continue
            break
        if kind in ("perl", "ruby"):
            if t.startswith("-") and not t.startswith("--") and len(t) > 1:
                j, took = 1, False
                while j < len(t):
                    ch = t[j]
                    if ch == "i":
                        inplace = True
                        break
                    if ch in "eE":
                        if j + 1 < len(t):
                            code = Word(t[j + 1:], t[j + 1:], a[i].expands)
                        else:
                            code, took = nxt, True
                        break
                    if ch in "l0":                         # optional octal digits follow
                        j += 1
                        while j < len(t) and t[j] in "01234567":
                            j += 1
                        continue
                    if ch in "IMmxdDC":                    # the rest of the cluster is a value
                        break
                    j += 1
                i += 2 if took else 1
                continue
            break
        if kind == "php":
            if t in ("-r", "-B", "-R", "-E"):
                code = nxt
                i += 2
                continue
            if t == "-f":
                return None, False, False, a[i + 1:]
            if t.startswith("-"):
                i += 1
                continue
            break
        if kind in ("lua", "rscript"):
            if t == "-e":
                code = nxt
                i += 2
                continue
            if t.startswith("-") and t != "-":
                i += 1
                continue
            break
        break
    rest = a[i:]
    stdin = code is None and (not rest or rest[0].text in STDIN_PATHS)
    return code, stdin, inplace, rest


def _pwsh_args(a: list):
    """(code word, reads its program from stdin, encoded)"""
    i = 0
    while i < len(a):
        t = a[i].text.lower()
        nxt = a[i + 1] if i + 1 < len(a) else None
        if t in ("-encodedcommand", "-enc", "-e", "-ec", "-en", "-encoded"):
            return None, False, True
        if t in ("-command", "-c", "-com", "-comm"):
            if nxt is None or nxt.text == "-":
                return None, True, False
            return nxt, False, False
        if t in ("-file", "-f"):
            return None, bool(nxt is not None and nxt.text == "-"), False
        if t.startswith("-"):
            i += 2 if t in ("-executionpolicy", "-ex", "-ep", "-workingdirectory", "-wd", "-configurationname", "-settingsfile") else 1
            continue
        return None, False, False                          # a script path
    return None, True, False


def _non_options(a: list) -> list:
    out, opts = [], True
    for w in a:
        if opts and w.text == "--":
            opts = False
        elif opts and w.text.startswith("-") and len(w.text) > 1:
            continue
        else:
            out.append(w)
    return out


def _write(p: Part, sc: Scan, targets: list) -> None:
    p.writes = True
    p.targets.extend(targets)
    if "xargs" in p.via or "find" in p.via:
        sc.note("unresolved_write", p)                   # the targets come from the pipe or from find
    elif any(not _resolved(t, sc) for t in targets):
        sc.note("unresolved_write", p)


def _analyse(p: Part, sc: Scan, lx: _Lex) -> None:
    for t in p.targets:
        p.writes = True
        if not _resolved(t, sc):
            sc.note("unresolved_write", p)
    if p.header:
        if p.words and p.words[0].raw in ("for", "select") and len(p.words) > 1:
            sc.assigned.add(p.words[1].text)
        return
    ws, i = p.words, 0
    while i < len(ws) and ws[i].raw in RESERVED:
        i += 1
    while i < len(ws):                                   # wrappers in front of the program
        w = ws[i]
        if w.expands or w.escaped:
            break
        name = _base(w.text)
        if name == "env":
            p.via.append("env")
            i, done = _env(ws, i + 1, p, sc, lx)
            if done:
                return
            continue
        if name == "command":
            if i + 1 < len(ws) and ws[i + 1].text in ("-v", "-V"):
                p.cmd = "command"                        # a lookup: nothing runs
                return
            p.via.append("command")
            i = _opts(ws, i + 1, "", set())
            continue
        if name in WRAP:
            short_val, long_val = WRAP[name]
            i = _opts(ws, i + 1, short_val, long_val)
            if name == "timeout" and i < len(ws):
                i += 1                                   # the duration
            if name == "watch":
                rest = ws[i:]
                if rest and all(_literal(x, sc) for x in rest):
                    lx.sub(" ".join(x.text for x in rest), p)
                elif rest:
                    sc.note("dynamic", p)
                p.cmd = "watch"
                return
            p.via.append(name)
            continue
        break
    if i >= len(ws):
        return
    w, a = ws[i], ws[i + 1:]
    p.args = a
    if w.escaped or not _resolved(w, sc):
        p.cmd = "?"
        sc.note("dynamic", p)
        return
    name = p.cmd = _base(w.text)
    xargs = "xargs" in p.via
    if name in SHELLS:
        prog, stdin, rest = _shell_args(a)
        if p.piped and xargs:
            sc.note("feeds_shell", p)
        if prog is not None:
            p.code = prog.text
            if _literal(prog, sc):
                lx.sub(prog.text, p, p.piped)
            else:
                sc.note("dynamic", p)
        elif rest and rest[0].procsub:
            sc.note("feeds_shell", p)
        elif stdin:
            if p.piped or p.herestring:
                sc.note("feeds_shell", p)
            for body, _ in p.heredocs:
                p.code = body
                lx.sub(body, p)
        return
    kind = "python" if PY.match(name) else name if name in INTERP else ""
    if kind:
        code, stdin, inplace, rest = _interp_args(kind, a)
        if code is not None:
            p.code = code.text
            sc.codes.append(code.text)
            if not _literal(code, sc):
                sc.note("dynamic", p)
            if WRITE_API.search(code.text):
                p.writes = True
        if rest and rest[0].procsub:
            sc.note("feeds_shell", p)
        elif xargs and code is None:
            sc.note("dynamic", p)                          # xargs names the script: it comes from the pipe
        elif stdin:
            if p.piped or p.herestring:
                sc.note("feeds_shell", p)
            for body, _ in p.heredocs:
                p.code = body
                sc.codes.append(body)
                if WRITE_API.search(body):
                    p.writes = True
        if inplace:
            _write(p, sc, _non_options(rest))
        return
    if name in PWSH:
        code, stdin, encoded = _pwsh_args(a)
        if encoded:
            sc.note("dynamic", p)
        if stdin and (p.piped or p.herestring):
            sc.note("feeds_shell", p)
        if code is not None:
            p.code = code.text
            sc.codes.append(code.text)
            if not _literal(code, sc):
                sc.note("dynamic", p)
        return
    if name in ("iex", "invoke-expression"):
        if p.piped:
            sc.note("feeds_shell", p)
        elif a and not all(_literal(x, sc) for x in a):
            sc.note("dynamic", p)
        return
    if name == "eval":
        if a and all(_literal(x, sc) for x in a):
            lx.sub(" ".join(x.text for x in a), p, p.piped)
        elif a:
            sc.note("dynamic", p)
        return
    if name in ("source", "."):
        if a and (a[0].procsub or (p.piped and a[0].text in STDIN_PATHS)):
            sc.note("feeds_shell", p)
        elif a and not _resolved(a[0], sc):
            sc.note("dynamic", p)
        return
    if name == "su":
        for k, x in enumerate(a):
            if x.text in ("-c", "--command") and k + 1 < len(a):
                if _literal(a[k + 1], sc):
                    lx.sub(a[k + 1].text, p, p.piped)
                else:
                    sc.note("dynamic", p)
        return
    if name == "find":
        j = 0
        while j < len(a):
            t = a[j].text
            if t in ("-exec", "-execdir", "-ok", "-okdir"):
                k, inner = j + 1, []
                while k < len(a) and a[k].text not in (";", "+"):
                    inner.append(a[k])
                    k += 1
                if inner:
                    sc.parts.append(Part(raw=" ".join(x.raw for x in inner), words=inner, depth=p.depth, via=["find"], cmdpos=False))
                j = k + 1
                continue
            if t == "-delete":
                p.writes = True
                sc.note("unresolved_write", p)
            if t in ("-fprint", "-fprint0", "-fprintf", "-fls") and j + 1 < len(a):
                _write(p, sc, [a[j + 1]])
            j += 1
        return
    if name in ("cd", "pushd"):
        t = _non_options(a)
        if (t and not _resolved(t[0], sc)) or (t and t[0].text == "-") or (name == "pushd" and t and t[0].text[:1] in "+-"):
            sc.note("chdir", p)
        elif t:
            sc.cds.append(t[0].text)
        return
    if name in ("export", "declare", "typeset", "local", "readonly", "read"):
        for x in _non_options(a):
            nm = re.split(r"[\[+=]", x.text, maxsplit=1)[0]
            if NAME.match(nm):
                sc.assigned.add(nm)
        return
    if name == "sed":
        files, script_given, inplace, k = [], False, False, 0
        while k < len(a):
            t = a[k].text
            if t in ("-e", "-f", "--expression", "--file"):
                script_given = True
                k += 2
                continue
            if t.startswith(("--expression=", "--file=")):
                script_given = True
            elif t.startswith("--in-place"):
                inplace = True
            elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
                head = t[1:].split("e")[0].split("f")[0]
                inplace |= "i" in head
                script_given |= len(head) < len(t) - 1     # -ne 'script' / -nf file: the script is in the option
                if len(head) == len(t) - 2 and t[-1] in "ef":
                    k += 2                                 # -ne 'script': the next word is the script
                    continue
            else:
                files.append(a[k])
            k += 1
        if inplace:
            _write(p, sc, files if script_given else files[1:])
        return
    if name == "dd":
        outs = [Word(x.text[3:], x.text[3:], x.expands) for x in a if x.text.startswith("of=")]
        if outs:
            _write(p, sc, outs)
        return
    if name in WRITE_VERBS or name in PS_WRITE:
        if name in ("cp", "ln", "install", "rsync"):         # these write only to their destination
            k = next((j for j, x in enumerate(a) if x.text in ("-t", "--target-directory")), None)
            eq = next((x for x in a if x.text.startswith("--target-directory=")), None)
            if k is not None and k + 1 < len(a):
                dest = [a[k + 1]]
            elif eq is not None:
                dest = [Word(eq.text.split("=", 1)[1], eq.text.split("=", 1)[1], eq.expands)]
            else:
                dest = _non_options(a)[-1:]
            _write(p, sc, dest)
        else:
            _write(p, sc, _non_options(a))


def scan(cmd: str) -> Scan:
    """Split one Bash line into the commands it runs and mark what cannot be read in advance."""
    sc = Scan()
    try:
        lx = _Lex(cmd, sc, 0)
        lx.run(False)
        i = 0
        while i < len(sc.parts):                         # reading sh -c / eval / find -exec adds parts
            _analyse(sc.parts[i], sc, _Lex("", sc, sc.parts[i].depth))
            i += 1
        if sc.chdir and not sc.unresolved_write:
            w = next((q for q in sc.parts if q.writes), None)
            if w is not None:
                sc.note("unresolved_write", w)
    except _Unreadable as e:
        sc.error = str(e)
    except RecursionError:
        sc.error = "nesting deeper than the guard reads"
    return sc


def explain(cmd: str) -> dict:
    """What the scanner sees, for `qz guard --explain` and tests."""
    sc = scan(cmd)
    return {"parts": [{"raw": q.raw, "cmd": q.cmd, "via": q.via, "piped": q.piped, "writes": q.writes, "depth": q.depth}
                      for q in sc.parts if not q.header and (q.cmd or q.writes)],
            "feeds_shell": sc.feeds_shell, "dynamic": sc.dynamic, "unresolved_write": sc.unresolved_write,
            "chdir": sc.chdir, "error": sc.error}
