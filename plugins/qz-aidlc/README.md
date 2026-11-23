# qz-aidlc · QualiZeal AI-DLC Studio plugin

The QualiZeal AI Center of Excellence's governed way to do agentic AI work in Claude Code: tested starters for
LangGraph, the OpenAI Agents SDK, the Claude Agent SDK (Python and TypeScript), an MCP (Model Context Protocol) server,
agent memory, read-only text-to-SQL, AWS Strands, Microsoft Agent Framework and Go; two RAG (retrieval-augmented
generation) kits, vectorless and hybrid, that also take web pages; a board for several agents on one job;
lanes that architect, spec, build, evaluate, test, audit, deliver, demo, bid and write office decks, workbooks and
mail; the Knowledge Fabric; and a harness around all of it - a policy guard that reads every command on a line,
per-turn undo, goal mode, routing that fits the model and effort to the task, an audit chain, a run ledger and report
cards.

Install in Claude Code 2.1.295 or later:

    /plugin install qz-aidlc --marketplace qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse

On a laptop, the repository's bootstrap (`setup\bootstrap.cmd` on Windows, `sh setup/bootstrap.sh` elsewhere) does
this and installs what the plugin needs: uv, and Python 3.11 to 3.13. Start with `/qz-aidlc:qz` and say what you need,
or `/qz-aidlc:qz-help` for every command; setup is `/qz-aidlc:qz-setup`. The README, setup guide, live-session plan
and credits are in the root of `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`, made for QualiZeal's own teams.
