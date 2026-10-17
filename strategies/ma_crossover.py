"""Dual moving-average crossover strategy."""

from __future__ import annotations

import numpy as np

from strategies.base import BaseStrategy, register


def sma(values: np.ndarray, window: int) -> np.ndarray:
    """Simple moving average; entries before `window` are NaN."""
    values = np.asarray(values, dtype=np.float64)
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if window <= 0 or values.size < window:
        return out
    cum = np.cumsum(np.insert(values, 0, 0.0))
    out[window - 1:] = (cum[window:] - cum[:-window]) / window
    return out


@register
class MACrossover(BaseStrategy):
    """Long when the fast MA is above the slow MA, otherwise flat."""

    name = "ma_crossover"

    def __init__(self, fast: int = 10, slow: int = 30) -> None:
        super().__init__(fast=int(fast), slow=int(slow))

    def generate_positions(self, prices: np.ndarray) -> np.ndarray:
        fast_ma = sma(prices, self.params["fast"])
        slow_ma = sma(prices, self.params["slow"])
        with np.errstate(invalid="ignore"):
            positions = np.where(fast_ma > slow_ma, 1.0, 0.0)
        positions[np.isnan(fast_ma) | np.isnan(slow_ma)] = 0.0
        return positions
