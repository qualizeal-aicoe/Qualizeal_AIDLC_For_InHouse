"""Every test keeps its runs in a scratch state database of its own, never the project's .agent/state.db: each test
starts with no waiting runs and an empty sample payment system."""
import os
import tempfile

import pytest

os.environ.setdefault("AGENT_STATE_DB", os.path.join(tempfile.mkdtemp(prefix="agent-tests-"), "state.db"))
os.environ.setdefault("AGENT_MODE", "stub")


@pytest.fixture(autouse=True)
def _state_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATE_DB", str(tmp_path / "state.db"))
