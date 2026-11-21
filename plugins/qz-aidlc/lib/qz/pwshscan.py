"""A small reader of PowerShell command lines, for the guard.

On a Windows laptop without Git Bash, Claude Code runs commands with its PowerShell tool instead of Bash, so the guard
must read PowerShell too. This reader splits a line into its commands (at `;`, `|`, `&&`, `||` and line ends that are
outside quotes and brackets), names each command's program with aliases resolved, and lists the files a command
writes: cmdlet paths such as `Set-Content -Path x`, copy and move destinations, `-OutFile`, .NET file writes and
redirections. What it cannot read in advance is reported so the guard asks: unbalanced quotes or brackets, a program
named by a variable, a write whose target is a variable. It never runs anything.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field

ALIASES = {
    "rm": "remove-item", "del": "remove-item", "erase": "remove-item", "rd": "remove-item", "rmdir": "remove-item",
    "ri": "remove-item", "cp": "copy-item", "copy": "copy-item", "cpi": "copy-item", "mv": "move-item",
    "move": "move-item", "mi": "move-item", "ren": "rename-item", "rni": "rename-item", "ni": "new-item",
    "mkdir": "new-item", "md": "new-item", "ac": "add-content", "clc": "clear-content", "tee": "tee-object",
    "epcsv": "export-csv", "gc": "get-content", "cat": "get-content", "type": "get-content", "iwr": "invoke-webrequest",
    "irm": "invoke-restmethod", "iex": "invoke-expression", "icm": "invoke-command", "ls": "get-childitem",
    "dir": "get-childitem", "gci": "get-childitem", "cd": "set-location", "chdir": "set-location", "sl": "set-location",
    "pushd": "push-location", "popd": "pop-location", "echo": "write-output", "write": "write-output",
    "sp": "set-itemproperty", "si": "set-item", "saps": "start-process", "start": "start-process",
}
# cmdlet -> (named parameters that name a written path, positional index of the written path or None)
WRITERS = {
    "set-content": (("path", "literalpath"), 0), "add-content": (("path", "literalpath"), 0),
    "clear-content": (("path", "literalpath"), 0), "out-file": (("filepath", "literalpath", "path"), 0),
    "new-item": (("path",), 0), "remove-item": (("path", "literalpath"), 0), "rename-item": (("path", "literalpath"), 0),
    "copy-item": (("destination",), 1), "move-item": (("destination",), 1),
    "expand-archive": (("destinationpath",), 1), "compress-archive": (("destinationpath",), 1),
    "export-csv": (("path", "literalpath"), 0), "export-clixml": (("path", "literalpath"), 0),
    "tee-object": (("filepath", "literalpath"), 0), "invoke-webrequest": (("outfile",), None),
    "invoke-restmethod": (("outfile",), None), "start-bitstransfer": (("destination",), 1),
}
ALSO_SOURCE = {"move-item": ("path", "literalpath")}          # a move removes its source as well
LOCATION = {"set-location", "push-location"}
NOT_FILES = re.compile(r"^(?:\$null|nul|env:|variable:|function:|alias:|cert:|wsman:|hk(?:lm|cu|cr|u|cc):|registry::)", re.I)
DOTNET_WRITE = re.compile(r"\[(?:system\.)?io\.(?:file|directory)\]::(?:write\w*|append\w*|create\w*|delete|move|copy|replace|open\w*)\s*\(\s*(['\"]?)([^'\",)]*)\1", re.I)
REDIRECT = re.compile(r"^(?:[1-6*]?>>?|[1-6]>&[12])$")
SWITCHES = {"recurse", "force", "whatif", "confirm", "passthru", "nonewline", "append", "noclobber", "container",
            "verbose", "debug", "file", "directory", "hidden", "usebasicparsing", "asbytestream", "raw", "update",
            "skipheader", "notypeinformation", "useculture", "erroraction", "erroractionpreference"}
VALUES = {"path", "literalpath", "filepath", "destination", "destinationpath", "outfile", "value", "encoding", "name",
          "itemtype", "filter", "include", "exclude", "newname", "uri", "method", "body", "headers", "inputobject",
          "delimiter", "stream", "credential", "infile", "contenttype", "depth", "width", "source", "compressionlevel"}


def _param(key: str) -> tuple[str, bool]:
    """A parameter name as PowerShell resolves an abbreviation, and whether it takes a value."""
    k = key.lower()
    if k in VALUES or k in SWITCHES:
        return k, k in VALUES
    cands = [n for n in VALUES | SWITCHES if n.startswith(k)]
    vals = [n for n in cands if n in VALUES]
    if len(cands) == 1:
        return cands[0], cands[0] in VALUES
    if len(vals) == 1:
        return vals[0], True
    return k, False


@dataclass
class Part:
    raw: str
    cmd: str = ""                 # lower-case cmdlet or program, alias resolved; "?" when named by a variable
    args: list = field(default_factory=list)
    targets: list = field(default_factory=list)


@dataclass
class Scan:
    parts: list = field(default_factory=list)
    error: str = ""
    dynamic: str = ""
    unresolved_write: str = ""
    cds: list = field(default_factory=list)


def _split(line: str) -> tuple[list[str], str]:
    """Split at command separators outside quotes and brackets. Returns the pieces and an error, if any."""
    out, buf, depth, i, q = [], [], 0, 0, ""
    while i < len(line):
        c = line[i]
        if q == "'":
            buf.append(c)
            if c == "'":
                if i + 1 < len(line) and line[i + 1] == "'":
                    buf.append("'"); i += 1
                else:
                    q = ""
        elif q == '"':
            buf.append(c)
            if c == "`" and i + 1 < len(line):
                buf.append(line[i + 1]); i += 1
            elif c == '"':
                q = ""
        elif c in "'\"":
            q = c; buf.append(c)
        elif c == "`" and i + 1 < len(line):
            if line[i + 1] in "\r\n":                    # a line continuation
                buf.append(" "); i += 1
            else:
                buf.append(c); buf.append(line[i + 1]); i += 1
        elif c in "({":
            depth += 1; buf.append(c)
        elif c in ")}":
            depth -= 1; buf.append(c)
            if depth < 0:
                return out, "a closing bracket has no opening one"
        elif depth == 0 and (c in ";\n" or line.startswith("&&", i) or line.startswith("||", i) or c == "|"):
            out.append("".join(buf)); buf = []
            if line.startswith("&&", i) or line.startswith("||", i):
                i += 1
        else:
            buf.append(c)
        i += 1
    if q:
        return out, "a quote is not closed"
    if depth:
        return out, "a bracket is not closed"
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()], ""


def _words(seg: str) -> list[tuple[str, bool]]:
    """Words of one command, with quotes removed, and whether each was quoted."""
    words, buf, q, quoted, depth = [], [], "", False, 0
    for i, c in enumerate(seg):
        if q:
            if c == q:
                q = ""
            else:
                buf.append(c)
            continue
        if c in "'\"" and depth == 0:
            q, quoted = c, True
            continue
        if c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
        if c.isspace() and depth == 0:
            if buf or quoted:
                words.append(("".join(buf), quoted))
            buf, quoted = [], False
            continue
        buf.append(c)
    if buf or quoted:
        words.append(("".join(buf), quoted))
    # a redirection written against its target (">out.txt", "2>>log") becomes two words
    out = []
    for w, qd in words:
        m = re.match(r"^([1-6*]?>>?)(.+)$", w) if not qd else None
        if m and not REDIRECT.match(w):
            out += [(m.group(1), False), (m.group(2), False)]
        else:
            out.append((w, qd))
    return out


def _resolve(path: str) -> tuple[str, bool]:
    """A written path as the guard can check it, and whether it could be read in advance."""
    p = path.strip()
    if not p or NOT_FILES.match(p):
        return "", True
    p = re.sub(r"^\$env:(?:TEMP|TMP)(?=$|[\\/])", lambda m: tempfile.gettempdir(), p, flags=re.I)
    if re.search(r"\$(?!env:(?:USERPROFILE|HOME)\b|HOME\b)|\$\(|@\(", p, re.I) and not p.startswith(tempfile.gettempdir()):
        return p, False
    return p, True


HERE_STRING = re.compile(r"@([\"'])[ \t]*\r?\n.*?\r?\n\1@", re.S)
COMMENT = re.compile(r"<#.*?#>|(?:(?<=\s)|^)#[^\n]*", re.S)


def _strip_literals(line: str) -> str:
    """Here-strings become one quoted word and comments go: neither runs anything, and both may hold any characters."""
    line = HERE_STRING.sub("'here-string'", line)
    out, q = [], ""
    for chunk in re.split(r"('(?:[^']|'')*'|\"(?:[^\"`]|`.)*\")", line):
        out.append(chunk if chunk[:1] in ("'", '"') else COMMENT.sub("", chunk))
    return "".join(out)


def scan(line: str) -> Scan:
    sc = Scan()
    segs, err = _split(_strip_literals(line or ""))
    if err:
        sc.error = err
        return sc
    for seg in segs:
        part = Part(raw=seg)
        words = _words(seg)
        if not words:
            continue
        first, firstq = words[0]
        rest = words[1:]
        if first in ("&", ".") and rest:                         # the call and dot-source operators
            first, firstq = rest[0]
            rest = rest[1:]
            if first.startswith(("$", "(")):
                part.cmd = "?"
                sc.dynamic = sc.dynamic or seg
        if not part.cmd:
            if first.startswith("$") and not rest:
                part.cmd = ""                                    # a bare expression, nothing runs
            elif first.startswith("$") and rest and rest[0][0] == "=":
                part.cmd = ""                                    # an assignment
            elif first.startswith("["):
                part.cmd = ""                                    # a .NET call, read below
            else:
                base = re.split(r"[\\/]", first)[-1].lower()
                base = re.sub(r"\.(exe|cmd|bat|com)$", "", base)
                part.cmd = ALIASES.get(base, base)
        part.args = rest
        _targets(part, sc)
        for m in DOTNET_WRITE.finditer(seg):
            target, ok = _resolve(m.group(2))
            if not ok or not target:
                sc.unresolved_write = sc.unresolved_write or seg
            else:
                part.targets.append(target)
        sc.parts.append(part)
    return sc


def _targets(part: Part, sc: Scan) -> None:
    args = part.args
    names, pos_index = WRITERS.get(part.cmd, ((), None))
    positional, named, i = [], {}, 0
    while i < len(args):
        w, quoted = args[i]
        if not quoted and REDIRECT.match(w):
            if i + 1 < len(args) and not w.endswith("&1") and not w.endswith("&2"):
                t, ok = _resolve(args[i + 1][0])
                if not ok:
                    sc.unresolved_write = sc.unresolved_write or part.raw
                elif t:
                    part.targets.append(t)
                i += 2
            else:
                i += 1
            continue
        if not quoted and re.match(r"^-[A-Za-z][\w-]*:?$", w):
            key, takes = _param(w.lstrip("-").rstrip(":"))
            if takes and i + 1 < len(args):
                named[key] = args[i + 1][0]
                i += 2
            else:
                named[key] = True
                i += 1
            continue
        if not quoted and re.match(r"^-[A-Za-z][\w-]*:.+$", w):
            k, v = w.lstrip("-").split(":", 1)
            named[_param(k)[0]] = v
            i += 1
            continue
        positional.append(w)
        i += 1
    written = [named[n] for n in names if isinstance(named.get(n), str)]
    if not written and pos_index is not None and len(positional) > pos_index:
        written.append(positional[pos_index])
    if part.cmd in ALSO_SOURCE:
        src = [named[n] for n in ALSO_SOURCE[part.cmd] if isinstance(named.get(n), str)]
        written += src or positional[:1]
    if part.cmd in LOCATION:
        v = named.get("path") or named.get("literalpath") or (positional[0] if positional else "")
        if isinstance(v, str) and v:
            sc.cds.append(v)
    for w in written:
        for one in re.split(r",(?![^(]*\))", w):              # Remove-Item a, b
            t, ok = _resolve(one)
            if not ok:
                sc.unresolved_write = sc.unresolved_write or part.raw
            elif t:
                part.targets.append(t)
