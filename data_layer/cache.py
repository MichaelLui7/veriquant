"""Local Parquet cache for price series."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd


def save_parquet(prices: np.ndarray, path: str, columns: list[str] | None = None) -> None:
    df = pd.DataFrame(prices)
    if columns is not None:
        df.columns = columns
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    df.to_parquet(path)


def load_parquet(path: str) -> np.ndarray:
    return pd.read_parquet(path).to_numpy(dtype=np.float64)
