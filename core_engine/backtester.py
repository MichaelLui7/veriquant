"""Deterministic single-task backtest runner.

`run_single_backtest` is the pure function distributed across Ray workers. It
takes a read-only price array (passed by ObjectRef for zero-copy access), a
strategy parameter dict, and a risk config, and returns a metrics bundle.

Determinism notes (needed for the single-vs-distributed consistency guarantee):
  * float64 throughout, no RNG, no per-machine reduction-order dependence;
  * vectorized numpy operations only;
  * the equity curve is produced by a plain cumulative product.
"""

from __future__ import annotations

import numpy as np

from core_engine import metrics
from core_engine.matching_engine import MatchingConfig
from core_engine.portfolio import VerifiedPortfolio
from strategies import get_strategy

DEFAULT_RISK_CONFIG = {
    "initial_capital": 1_000_000.0,
    "max_leverage": 2.0,
    "cost_bps": 1.0,        # 1 bp round-trip transaction cost per unit turnover
    "risk_free": 0.0,       # annualized risk-free rate
    "slippage_bps": 1.0,    # verified path only
    "fee_bps": 1.0,         # verified path only
    "limit_pct": 0.0,       # daily price limit (verified path only)
}


def run_single_backtest(prices: np.ndarray, params: dict,
                        risk_config: dict | None = None,
                        include_equity: bool = False) -> dict:
    """Run one backtest and return a dict of scalar metrics.

    ``params`` must contain ``strategy`` and the strategy's own parameters,
    e.g. ``{"strategy": "ma_crossover", "fast": 5, "slow": 20}``.

    The full equity curve is only returned when ``include_equity=True``; grid
    searches only need scalar metrics, and shipping per-task equity arrays back
    to the driver would dominate the distributed run's cost.
    """
    cfg = dict(DEFAULT_RISK_CONFIG)
    if risk_config:
        cfg.update(risk_config)

    prices = np.asarray(prices, dtype=np.float64)
    if prices.size < 2:
        raise ValueError("Need at least 2 price observations")

    strategy_name = params.get("strategy", "ma_crossover")
    strategy_params = {k: v for k, v in params.items() if k != "strategy"}
    strategy = get_strategy(strategy_name)(**strategy_params)

    target = strategy.generate_positions(prices).astype(np.float64)
    target = np.clip(target, 0.0, float(cfg["max_leverage"]))

    # Price returns and the position held over each interval (signal at t-1).
    price_returns = np.diff(prices) / prices[:-1]
    held = target[:-1]

    gross = held * price_returns
    turnover = np.abs(np.diff(target))
    costs = turnover * (float(cfg["cost_bps"]) / 10000.0)
    net = gross - costs

    equity = float(cfg["initial_capital"]) * np.cumprod(1.0 + net)

    m = metrics.summarize(equity, net, risk_free=float(cfg["risk_free"]))
    m["num_trades"] = int(np.count_nonzero(np.diff(target)))
    m["exposure"] = float(np.mean(target))
    result = {"params": params, **m}
    if include_equity:
        result["equity"] = equity
    return result


def run_verified_backtest(prices: np.ndarray, params: dict,
                          risk_config: dict | None = None,
                          include_equity: bool = False) -> dict:
    """Event-driven backtest whose every balance change goes through the
    Dafny-verified ledger (``risk_control``) and the matching engine.

    This is the runtime wiring: the proven invariants (no overdraft, no short,
    no leverage breach, funds conserved) are enforced by the same code that is
    formally verified — not a parallel re-implementation.
    """
    cfg = dict(DEFAULT_RISK_CONFIG)
    if risk_config:
        cfg.update(risk_config)

    prices = np.asarray(prices, dtype=np.float64)
    if prices.size < 2:
        raise ValueError("Need at least 2 price observations")

    strategy_name = params.get("strategy", "ma_crossover")
    strategy_params = {k: v for k, v in params.items() if k != "strategy"}
    strategy = get_strategy(strategy_name)(**strategy_params)

    signals = strategy.generate_positions(prices).astype(np.float64)

    matching = MatchingConfig(
        slippage_bps=float(cfg["slippage_bps"]),
        fee_bps=float(cfg["fee_bps"]),
        limit_pct=float(cfg["limit_pct"]),
    )
    portfolio = VerifiedPortfolio(cash=float(cfg["initial_capital"]), matching=matching)

    n = prices.shape[0]
    equity = np.empty(n, dtype=np.float64)
    prev_signal = 0.0
    for t in range(n):
        if t > 0:
            portfolio.mark_to_market(prices[t], prices[t - 1])
        signal = float(signals[t])
        if signal != prev_signal:
            portfolio.rebalance(
                signal * portfolio.equity,
                prev_price=prices[t - 1] if t > 0 else None,
                price=prices[t],
            )
        prev_signal = signal
        equity[t] = portfolio.equity

    returns = np.diff(equity) / equity[:-1]
    m = metrics.summarize(equity, returns, risk_free=float(cfg["risk_free"]))
    m["num_trades"] = int(np.count_nonzero(np.diff(signals)))
    m["exposure"] = float(np.mean(signals))
    m["rejections"] = portfolio.rejections
    result = {"params": params, **m}
    if include_equity:
        result["equity"] = equity
    return result
