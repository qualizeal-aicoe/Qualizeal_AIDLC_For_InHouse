"""The Claude Code skill for this CLI, written from the catalogue: `mockctl skill` writes it, `mockctl skill --check`
fails when a command changed and the file did not."""
from __future__ import annotations

DESCRIPTION = ("Drive the team's WireMock-style mock server from the command line - list, add, change and remove stubs, "
               "check which calls an app under test made, and reset scenarios - with dry runs, undo and an audit log. "
               "Use when a test needs a stubbed HTTP API, or to check the requests an app sent.")


def _opt(p: dict) -> str:
    if p["kind"] == "argument":
        return f"`{p['name'].upper()}`" + ("" if p.get("required") else " (optional)")
    bits = [p["type"]] if p.get("type") else []
    if p.get("default") is not None:
        bits.append(f"default {p['default']}")
    if p.get("required"):
        bits.append("required")
    if p.get("repeatable"):
        bits.append("repeatable")
    return f"`{p['name']}`" + (f" ({', '.join(bits)})" if bits else "") + (f": {p['help']}" if p.get("help") else "")


def render(cat: dict) -> str:
    c = cat["contract"]
    lines = ["---", "name: mockctl", f"description: {DESCRIPTION}", "---", "", "# mockctl", "",
             "<!-- Written by `uv run mockctl skill` from the commands themselves. Do not edit it by hand: "
             "CI runs `uv run mockctl skill --check`. -->", "",
             cat["about"], "",
             "Run every command from the project folder as `uv run mockctl ...`. `uv run mockctl describe --json` prints all of "
             "this as data.", "", "## Rules", ""]
    lines += [f"{i}. {r}" for i, r in enumerate(c["rules"], 1)]
    lines += ["", "## Commands", "", "| Command | Effect | Undo | What it does |", "|---|---|---|---|"]
    for x in cat["commands"]:
        undo = "" if x["undo"] is None else ("yes" if x["undo"] else "no")
        lines.append(f"| `{x['path']}` | {x['effect']} | {undo} | {x['help']} |")
    lines += ["", "Effects: " + " · ".join(f"**{k}** {v}" for k, v in c["effects"].items()) + ".", "",
              "## Options and an example for each command", ""]
    for x in cat["commands"]:
        lines += [f"### `{x['path']}`", "", f"`uv run {x['example']}`" if x["example"] else "", ""]
        opts = [_opt(p) for p in x["params"] if p["name"] != "--json"]
        lines += [f"- {o}" for o in opts] + ([""] if opts else [])
    lines += ["## Output", "", c["output"], "", "## Exit codes", "", "| Code | Meaning |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in c["exit_codes"].items()]
    lines += ["", "## Environment", ""] + [f"- `{k}`: {v}" for k, v in c["environment"].items()]
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.rstrip() + "\n"
