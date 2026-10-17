"""Strategy abstraction and registry."""

from __future__ import annotations

import numpy as np

_REGISTRY: dict[str, type["BaseStrategy"]] = {}


def register(cls: type["BaseStrategy"]) -> type["BaseStrategy"]:
    _REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: str) -> type["BaseStrategy"]:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy '{name}'. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


class BaseStrategy:
    """Base class for deterministic, vectorized strategies.

    A strategy maps a 1-D price series (float64, ordered oldest->newest) to a
    target-position series of the same length. Positions are in units of
    account equity fraction (0.0 = flat, 1.0 = fully invested).
    """

    name = "base"

    def __init__(self, **params: float) -> None:
        self.params = params

    def generate_positions(self, prices: np.ndarray) -> np.ndarray:
        raise NotImplementedError
