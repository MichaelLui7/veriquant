"""Configuration loading (YAML).

The ``configs/`` directory holds the editable risk / cluster settings. The
engine's ``DEFAULT_RISK_CONFIG`` in ``backtester`` are code-level fallbacks; call
``load_risk_config()`` to override them from disk.
"""

from __future__ import annotations

import os

import yaml

_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs"
)


def load_risk_config(path: str | None = None) -> dict:
    """Load a risk config dict from YAML (defaults to configs/default_risk.yaml)."""
    path = path or os.path.join(_CONFIG_DIR, "default_risk.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_ray_config(path: str | None = None) -> dict:
    """Load the Ray cluster config (defaults to configs/ray_cluster.yaml)."""
    path = path or os.path.join(_CONFIG_DIR, "ray_cluster.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
