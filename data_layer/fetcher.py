"""Data loading: deterministic synthetic series and optional Yahoo Finance.

The synthetic generator (geometric Brownian motion with a fixed seed) exists so
tests, benchmarks and demos are fully self-contained and reproducible — no
network, no non-determinism.
"""

from __future__ import annotations

import numpy as np


def generate_synthetic_prices(n_assets: int = 1, n_days: int = 1500,
                              seed: int = 42, s0: float = 100.0,
                              mu: float = 0.08, sigma: float = 0.25,
                              freq: int = 252) -> np.ndarray:
    """Generate deterministic GBM prices.

    ``freq`` is the number of bars per year (252 = daily, 252*390 = minute), so
    annualised drift/volatility are scaled to the bar length. Returns a float64
    array of shape (n_days, n_assets).
    """
    rng = np.random.default_rng(seed)
    dt = 1.0 / freq
    drift = (mu - 0.5 * sigma ** 2) * dt
    shocks = rng.normal(0.0, 1.0, size=(n_days - 1, n_assets)) * sigma * np.sqrt(dt)
    log_path = np.concatenate(
        [np.zeros((1, n_assets)), drift + shocks], axis=0
    ).cumsum(axis=0)
    prices = s0 * np.exp(log_path)
    return prices.astype(np.float64)


def fetch_yahoo(tickers: list[str], start: str, end: str) -> np.ndarray:
    """Optional Yahoo Finance loader (requires ``yfinance``).

    Returns float64 prices of shape (n_days, n_assets) aligned across tickers.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("yfinance is not installed; pip install yfinance") from exc

    df = yf.download(tickers, start=start, end=end, auto_adjust=True)["Close"]
    if isinstance(df, np.ndarray) or (hasattr(df, "ndim") and df.ndim == 1):
        df = df.to_frame()
    return df.ffill().dropna().to_numpy(dtype=np.float64)
