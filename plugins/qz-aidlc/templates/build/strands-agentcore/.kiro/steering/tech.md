---
inclusion: always
---
# Technology

- Python 3.12, Strands Agents (`strands-agents`), Amazon Bedrock for models, Amazon Bedrock AgentCore Runtime for hosting (`runtime.py`).
- Limits live in `agent/policy.py`: model id, turn limit, token limits, and the tools that need approval. Change them there only.
- Offline runs use `agent/stub.py` (`AGENT_MODE=stub`): a scripted model that needs no credentials.
- Tests: `python3 -m pytest -q tests`. Gold set: `uv run -q --no-project --python ">=3.11,<3.14" python -I -X utf8 .claude/qz/scripts/qz.py eval run`.
