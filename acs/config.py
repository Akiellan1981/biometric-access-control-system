"""Configuration loader: reads config/config.yaml, supports dotted lookups."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


class Config:
    def __init__(self, data: dict, base_dir: Path):
        self._d = data or {}
        self.base_dir = base_dir

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        p = Path(path or os.environ.get("ACS_CONFIG") or DEFAULT_PATH).resolve()
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # config.yaml lives at <root>/config/config.yaml -> base_dir is <root>
        return cls(data, p.parent.parent)

    def get(self, dotted: str, default=None):
        cur = self._d
        for key in dotted.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    def path(self, dotted: str, default=None) -> Path | None:
        """Resolve a configured path relative to the project root."""
        v = self.get(dotted, default)
        if v is None:
            return None
        p = Path(v)
        return p if p.is_absolute() else (self.base_dir / p)

    def __getitem__(self, key):
        return self._d[key]
