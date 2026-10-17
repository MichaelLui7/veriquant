"""Sanitization: alignment, forward-fill and validation of price series."""

from __future__ import annotations

import numpy as np


def forward_fill(prices: np.ndarray) -> np.ndarray:
    """Forward-fill NaNs along the time axis (rows)."""
    arr = np.asarray(prices, dtype=np.float64)
    if arr.ndim == 1:
        mask = np.isnan(arr)
        idx = np.where(~mask, np.arange(arr.size), 0)
        np.maximum.accumulate(idx, out=idx)
        return arr[idx]
    return pd_fill(arr)


def pd_fill(arr: np.ndarray) -> np.ndarray:
    import pandas as pd
    return pd.DataFrame(arr).ffill().to_numpy(dtype=np.float64)


def validate(prices: np.ndarray) -> np.ndarray:
    """Drop leading NaN rows and raise on non-finite values or non-positive prices."""
    arr = np.asarray(prices, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.shape[0] < 2:
        raise ValueError("Not enough observations")
    if not np.all(np.isfinite(arr)):
        raise ValueError("Non-finite values remain after fill")
    if np.any(arr <= 0):
        raise ValueError("Prices must be strictly positive")
    return arr
