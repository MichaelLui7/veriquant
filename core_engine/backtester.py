"""Deterministic single-task backtest runner (Vectorized & Dafny-Verified Event-Driven)."""

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
    "warmup_bars": 0,       # common indicator warm-up window before evaluation
}


def run_single_backtest(prices: np.ndarray, params: dict,
                        risk_config: dict | None = None,
                        include_equity: bool = False) -> dict:
    """Run one vectorized backtest and return a dict of scalar metrics."""
    cfg = dict(DEFAULT_RISK_CONFIG)
    if risk_config:
        cfg.update(risk_config)

    prices = np.asarray(prices, dtype=np.float64)
    if prices.size < 2:
        raise ValueError("Need at least 2 price observations")

    warmup = int(cfg.get("warmup_bars", 0))
    if warmup < 0 or warmup >= prices.size - 1:
        raise ValueError(f"Invalid warmup_bars={warmup} for series of length {prices.size}")

    strategy_name = params.get("strategy", "ma_crossover")
    strategy_params = {k: v for k, v in params.items() if k != "strategy"}
    strategy = get_strategy(strategy_name)(**strategy_params)

    target = strategy.generate_positions(prices).astype(np.float64)
    target = np.clip(target, 0.0, float(cfg["max_leverage"]))
    if warmup > 0:
        target[:warmup] = 0.0

    price_returns = np.diff(prices) / prices[:-1]
    held = target[:-1]

    prev_held = np.concatenate([[0.0], held[:-1]])
    turnover = np.abs(held - prev_held)
    costs = turnover * (float(cfg["cost_bps"]) / 10000.0)
    net = held * price_returns - costs

    init_cap = float(cfg["initial_capital"])
    equity = np.empty(prices.size, dtype=np.float64)
    equity[0] = init_cap
    equity[1:] = init_cap * np.cumprod(1.0 + net)

    eval_equity = equity[warmup:]
    eval_returns = net[warmup:]

    m = metrics.summarize(eval_equity, eval_returns, risk_free=float(cfg["risk_free"]))
    m["num_trades"] = int(np.count_nonzero(np.diff(target[warmup:])))
    m["exposure"] = float(np.mean(target[warmup:]))
    result = {"params": params, **m}
    if include_equity:
        result["equity"] = eval_equity
    return result


def run_verified_backtest(prices: np.ndarray, params: dict,
                          risk_config: dict | None = None,
                          include_equity: bool = False,
                          include_events: bool = False) -> dict:
    """Event-driven backtest whose every balance change goes through the
    Dafny-verified ledger (``risk_control``) and emits a SHA-256 state hash.
    """
    cfg = dict(DEFAULT_RISK_CONFIG)
    if risk_config:
        cfg.update(risk_config)

    prices = np.asarray(prices, dtype=np.float64)
    if prices.size < 2:
        raise ValueError("Need at least 2 price observations")

    warmup = int(cfg.get("warmup_bars", 0))
    if warmup < 0 or warmup >= prices.size - 1:
        raise ValueError(f"Invalid warmup_bars={warmup} for series of length {prices.size}")

    strategy_name = params.get("strategy", "ma_crossover")
    strategy_params = {k: v for k, v in params.items() if k != "strategy"}
    strategy = get_strategy(strategy_name)(**strategy_params)

    signals = strategy.generate_positions(prices).astype(np.float64)
    signals = np.clip(signals, 0.0, float(cfg["max_leverage"]))
    if warmup > 0:
        signals[:warmup] = 0.0

    matching = MatchingConfig(
        slippage_bps=float(cfg["slippage_bps"]),
        fee_bps=float(cfg["fee_bps"]),
        limit_pct=float(cfg["limit_pct"]),
    )
    portfolio = VerifiedPortfolio(
        cash=float(cfg["initial_capital"]),
        matching=matching,
        max_leverage=float(cfg["max_leverage"]),
        record_events=include_events,
    )

    n = prices.shape[0]
    equity = np.empty(n, dtype=np.float64)
    actual_exposure = np.zeros(n, dtype=np.float64)
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
                bar=t,
            )
        prev_signal = signal
        eq = portfolio.equity
        equity[t] = eq
        actual_exposure[t] = portfolio.account.position_value / eq if eq > 0 else 0.0
        portfolio.update_state_hash(t)

    eval_equity = equity[warmup:]
    returns = np.diff(eval_equity) / eval_equity[:-1]
    m = metrics.summarize(eval_equity, returns, risk_free=float(cfg["risk_free"]))
    m["num_trades"] = portfolio.executed_trades
    m["exposure"] = float(np.mean(actual_exposure[warmup:]))
    m["rejections"] = portfolio.rejections
    m["final_state_hash"] = portfolio.state_hash

    result = {"params": params, **m}
    if include_equity:
        result["equity"] = eval_equity
    if include_events:
        result["events"] = portfolio.events
    return result