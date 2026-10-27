"""Config loading. All tunable numbers come from YAML — nothing hard-coded in modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_DEFAULT = Path(__file__).with_name("default.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the YAML config. Defaults to ``config/default.yaml``."""
    p = Path(path) if path else _DEFAULT
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
