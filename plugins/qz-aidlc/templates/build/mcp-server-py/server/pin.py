"""Pin what each tool tells a model about itself: name, description, arguments and hints. A change fails the
tests until the pin is renewed in the same pull request, so a reviewer always sees it; a tool cannot change its
story quietly after people have approved it. Renew with: uv run -m server.pin"""
import asyncio
import hashlib
import json
from pathlib import Path

from mcp.client import Client

from .app import server

PINS = Path(__file__).resolve().parents[1] / "tests" / "tool_pins.json"


def fingerprint(tool) -> str:
    shown = {"name": tool.name, "title": tool.title, "description": tool.description, "input": tool.input_schema,
             "output": getattr(tool, "output_schema", None),
             "hints": tool.annotations.model_dump(mode="json", exclude_none=True) if tool.annotations else None}
    return hashlib.sha256(json.dumps(shown, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


async def current() -> dict[str, str]:
    async with Client(server) as c:
        return {t.name: fingerprint(t) for t in (await c.list_tools()).tools}


if __name__ == "__main__":
    PINS.write_text(json.dumps(asyncio.run(current()), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Pinned {PINS.name}. Commit it with the change that altered the tools.")
