"""Performance metrics for backtest results.

All functions are pure and deterministic (numpy float64, no RNG, no reduction
order dependence), which is a prerequisite for the bit-exact single-process vs.
distributed consistency guarantee.
"""

from __future__ import annotations

import numpy as np

TRADING_DAYS_PER_YEAR = 252


def total_return(equity: np.ndarray) -> float:
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size == 0 or equity[0] == 0:
        return 0.0
    return float(equity[-1] / equity[0] - 1.0)


def annualized_return(equity: np.ndarray, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size <= 1:
        return 0.0
    years = equity.size / periods
    total = equity[-1] / equity[0]
    if total <= 0:
        return -1.0
    return float(total ** (1.0 / years) - 1.0)


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0,
                 periods: int = TRADING_DAYS_PER_YEAR) -> float:
    returns = np.asarray(returns, dtype=np.float64)
    if returns.size == 0:
        return 0.0
    excess = returns - risk_free / periods
    std = np.std(excess)
    if std == 0.0:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(periods))


def sortino_ratio(returns: np.ndarray, risk_free: float = 0.0,
                  periods: int = TRADING_DAYS_PER_YEAR) -> float:
    returns = np.asarray(returns, dtype=np.float64)
    if returns.size == 0:
        return 0.0
    excess = returns - risk_free / periods
    downside = excess[excess < 0]
    if downside.size == 0:
        return 0.0
    dd = np.sqrt(np.mean(downside ** 2))
    if dd == 0.0:
        return 0.0
    return float(np.mean(excess) / dd * np.sqrt(periods))


def max_drawdown(equity: np.ndarray) -> float:
    equity = np.asarray(equity, dtype=np.float64)
    if equity.size == 0:
        return 0.0
    running_max = np.maximum.accumulate(equity)
    drawdowns = equity / running_max - 1.0
    return float(np.min(drawdowns))


def calmar_ratio(equity: np.ndarray, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0.0:
        return 0.0
    ann = annualized_return(equity, periods)
    return float(ann / abs(mdd))


def summarize(equity: np.ndarray, returns: np.ndarray,
              risk_free: float = 0.0) -> dict[str, float]:
    """Return the standard metric bundle for a backtest."""
    return {
        "total_return": total_return(equity),
        "annualized_return": annualized_return(equity),
        "sharpe_ratio": sharpe_ratio(returns, risk_free),
        "sortino_ratio": sortino_ratio(returns, risk_free),
        "max_drawdown": max_drawdown(equity),
        "calmar_ratio": calmar_ratio(equity),
    }
