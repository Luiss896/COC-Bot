from __future__ import annotations

from pathlib import Path

import yaml

from cocbot.config.models import Config

__all__ = ["Config", "load_config"]


def load_config(path: str | Path) -> Config:
    """Carica e valida un file YAML di configurazione."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config: il file YAML deve contenere una mappa")
    return Config.model_validate(raw)
