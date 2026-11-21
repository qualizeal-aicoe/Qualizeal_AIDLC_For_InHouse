"""Settings: defaults here, a team's changes in harness.toml, and the environment for what moves between machines."""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "target": {"base_url": "http://127.0.0.1:8080", "allowed_hosts": ["127.0.0.1", "localhost"], "timeout_s": 10},
    "limits": {"max_items": 1000, "max_turns": 200},
    "store": {"dir": ".mockctl"},
}


def load(path: str | Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = Path(path) if path else ROOT / "harness.toml"
    if p.is_file():
        with p.open("rb") as f:
            for section, values in tomllib.load(f).items():
                cfg.setdefault(section, {}).update(values)
    if os.environ.get("MOCKCTL_URL"):
        cfg["target"]["base_url"] = os.environ["MOCKCTL_URL"]
    home = os.environ.get("MOCKCTL_HOME")
    d = Path(home) if home else Path(cfg["store"]["dir"])
    cfg["store"]["dir"] = str(d if d.is_absolute() else ROOT / d)
    return cfg
