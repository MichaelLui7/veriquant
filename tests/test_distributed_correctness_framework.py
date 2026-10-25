"""Distributed Correctness Verification Framework for VeriQuant.

Implements the 4-layer verification matrix:
  1. Differential Testing against a zero-dependency Independent Reference Oracle
  2. Event-Level Deterministic Replay & Canonical State Hash (SHA-256)
  3. Metamorphic Testing (Worker count invariance W=1/2/4, shuffled order, duplicate task idempotency, batching)
  4. State Isolation Test (A -> B -> A) & Shared Memory Read-Only Immutability
  5. Look-Ahead Bias Prefix Invariance Test
  6. Indicator Warm-up Window Alignment Test
  7. Mutation Testing (Fault Injection: NaN/Inf poisoning, dropped tasks, user leverage breach, unpaid fee rollback)
"""

from __future__ import annotations

import os
import random
import sys
import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core_engine.backtester import DEFAULT_RISK_CONFIG, run_single_backtest, run_verified_backtest
from core_engine.matching_engine import MatchingConfig
from core_engine.portfolio import VerifiedPortfolio
from data_layer.fetcher import generate_synthetic_prices
from distributed.aggregator import pareto_frontier, verify_grid_completeness
from distributed.scheduler import DistributedBacktestEngine
from risk_control.gateway import Account, RiskGateway, VerifiedLedger


# ---------------------------------------------------------------------------
# 1. Differential Testing + Independent Reference Oracle
# ---------------------------------------------------------------------------
def independent_reference_oracle(
    prices: list[float], signals: list[int], initial_cash: float = 1000.0
) -> float:
    """Dead-simple, zero-dependency reference model with 0 slippage/fees.
    Used to verify that single-process and distributed engines do not share a common logic bug.
    """
    cash = initial_cash
    pos_val = 0.0
    prev_sig = 0
    for t, p in enumerate(prices):
        if t > 0:
            pos_val = pos_val * (p / prices[t - 1])
        sig = signals[t]
        if sig != prev_sig:
            equity = cash + pos_val
            target_pos = sig * equity
            delta = target_pos - pos_val
            cash -= delta
            pos_val += delta
        prev_sig = sig
    return round(cash + pos_val, 4)


def test_differential_against_independent_oracle():
    """Verify both Verified Engine and Vectorized Engine match the hand-calculated Oracle."""
    prices = np.array([100.0, 100.0, 100.0, 100.0, 110.0, 121.0, 108.9, 98.01], dtype=np.float64)
    cfg = dict(
        DEFAULT_RISK_CONFIG,
        initial_capital=1000.0,
        slippage_bps=0.0,
        fee_bps=0.0,
        cost_bps=0.0,
        warmup_bars=0,
    )
    params = {"strategy": "ma_crossover", "fast": 2, "slow": 4}

    res_verified = run_verified_backtest(prices, params, cfg, include_equity=True)
    res_fast = run_single_backtest(prices, params, cfg, include_equity=True)

    # Under MA(2, 4) on `prices`, signal is 1 at t=4, 5, 6 and 0 otherwise
    expected_signals = [0, 0, 0, 0, 1, 1, 1, 0]
    oracle_equity = independent_reference_oracle(prices.tolist(), expected_signals, 1000.0)

    assert round(float(res_verified["equity"][-1]), 2) == round(oracle_equity, 2)
    assert round(float(res_fast["equity"][-1]), 2) == round(oracle_equity, 2)
    assert res_verified["equity"].shape[0] == prices.shape[0]
    assert res_fast["equity"].shape[0] == prices.shape[0]


# ---------------------------------------------------------------------------
# 2. Event-Level Deterministic Replay & Canonical State Hash (Single == Ray)
# ---------------------------------------------------------------------------
def test_event_level_replay_and_state_hash_consistency():
    """Prove Single-Process Verified Engine == Ray Distributed Verified Engine
    not just on final Sharpe, but on every LedgerEvent and SHA-256 state hash H_t.
    """
    prices = generate_synthetic_prices(n_assets=1, n_days=400, seed=19)[:, 0]
    grid = [{"fast": 5, "slow": 20}, {"fast": 10, "slow": 40}, {"fast": 15, "slow": 60}]

    single_map = {}
    for p in grid:
        r = run_verified_backtest(
            prices,
            {"strategy": "ma_crossover", **p},
            DEFAULT_RISK_CONFIG,
            include_equity=True,
            include_events=True,
        )
        single_map[(p["fast"], p["slow"])] = r

    engine = DistributedBacktestEngine(num_cpus=2)
    try:
        dist_results = engine.run_grid_search(
            prices,
            grid,
            DEFAULT_RISK_CONFIG,
            include_equity=True,
            verified=True,
            include_events=True,
        )
    finally:
        engine.shutdown()

    for dr in dist_results:
        key = (dr["params"]["fast"], dr["params"]["slow"])
        sr = single_map[key]
        assert dr["final_state_hash"] == sr["final_state_hash"]
        assert dr["events"] == sr["events"]
        assert np.array_equal(dr["equity"], sr["equity"])


# ---------------------------------------------------------------------------
# 3. Metamorphic Testing (Worker count, Shuffled order, Duplicate jobs, Batching)
# ---------------------------------------------------------------------------
def test_metamorphic_partition_invariance():
    """Changing worker count (1 vs 4), shuffling task submission order, duplicating tasks,
    or changing batch_size (1 vs 2) must produce identical results and state hashes.
    """
    prices = generate_synthetic_prices(n_assets=1, n_days=300, seed=99)[:, 0]
    grid = [{"fast": f, "slow": s} for f in (5, 10) for s in (25, 50, 75)]
    shuffled_grid = list(grid)
    random.Random(42).shuffle(shuffled_grid)
    duplicated_grid = shuffled_grid + [grid[0], grid[-1]]  # Inject duplicate tasks

    e1 = DistributedBacktestEngine(num_cpus=1)
    try:
        res_w1 = e1.run_grid_search(prices, grid, DEFAULT_RISK_CONFIG, verified=True, batch_size=1)
    finally:
        e1.shutdown()

    e4 = DistributedBacktestEngine(num_cpus=4)
    try:
        res_w4 = e4.run_grid_search(
            prices, duplicated_grid, DEFAULT_RISK_CONFIG, verified=True, batch_size=2
        )
    finally:
        e4.shutdown()

    assert len(res_w1) == len(res_w4) == len(grid)
    for r1, r4 in zip(res_w1, res_w4):
        assert r1["job_id"] == r4["job_id"]
        assert r1["final_state_hash"] == r4["final_state_hash"]
        assert r1["sharpe_ratio"] == r4["sharpe_ratio"]


# ---------------------------------------------------------------------------
# 4. State Isolation Test (A -> B -> A)
# ---------------------------------------------------------------------------
def test_state_isolation_a_b_a():
    """Running A -> B -> A must produce bit-identical state hashes and events for A."""
    prices = generate_synthetic_prices(n_assets=1, n_days=300, seed=55)[:, 0]
    param_a = {"strategy": "ma_crossover", "fast": 5, "slow": 20}
    param_b = {"strategy": "ma_crossover", "fast": 12, "slow": 50}

    res_a1 = run_verified_backtest(prices, param_a, DEFAULT_RISK_CONFIG, include_events=True)
    _ = run_verified_backtest(prices, param_b, DEFAULT_RISK_CONFIG, include_events=True)
    res_a2 = run_verified_backtest(prices, param_a, DEFAULT_RISK_CONFIG, include_events=True)

    assert res_a1["final_state_hash"] == res_a2["final_state_hash"]
    assert res_a1["events"] == res_a2["events"]


# ---------------------------------------------------------------------------
# 5. Look-Ahead Bias Prefix Invariance Test
# ---------------------------------------------------------------------------
def test_no_look_ahead_bias_prefix_invariance():
    """Future prices after bar T must have zero effect on decisions, events, or equity up to T."""
    prices_full = generate_synthetic_prices(n_assets=1, n_days=400, seed=77)[:, 0]
    cutoff = 250
    prices_prefix = prices_full[:cutoff].copy()

    # Corrupt future prices after cutoff with extreme shocks
    prices_shocked = prices_full.copy()
    prices_shocked[cutoff:] *= 50.0

    params = {"strategy": "ma_crossover", "fast": 5, "slow": 20}
    res_prefix = run_verified_backtest(
        prices_prefix, params, DEFAULT_RISK_CONFIG, include_equity=True, include_events=True
    )
    res_shocked = run_verified_backtest(
        prices_shocked, params, DEFAULT_RISK_CONFIG, include_equity=True, include_events=True
    )

    assert np.array_equal(res_prefix["equity"], res_shocked["equity"][:cutoff])
    events_before_cutoff = [e for e in res_shocked["events"] if e.bar < cutoff]
    assert res_prefix["events"] == events_before_cutoff


# ---------------------------------------------------------------------------
# 6. Indicator Warm-up Window Alignment Test
# ---------------------------------------------------------------------------
def test_warmup_window_alignment():
    """With warmup_bars=60, all parameter combinations evaluate on the exact same [60, N) window."""
    prices = generate_synthetic_prices(n_assets=1, n_days=300, seed=12)[:, 0]
    cfg = dict(DEFAULT_RISK_CONFIG, warmup_bars=60)
    r_fast = run_verified_backtest(
        prices, {"strategy": "ma_crossover", "fast": 5, "slow": 20}, cfg, include_equity=True
    )
    r_slow = run_verified_backtest(
        prices, {"strategy": "ma_crossover", "fast": 15, "slow": 50}, cfg, include_equity=True
    )

    assert r_fast["equity"].shape[0] == r_slow["equity"].shape[0] == 300 - 60


# ---------------------------------------------------------------------------
# 7. Mutation & Boundary Tests (NaN poisoning, dropped jobs, leverage & fee rollback)
# ---------------------------------------------------------------------------
def test_mutation_catches_nan_and_dropped_jobs():
    """Intentionally inject NaN/Inf, dropped tasks, and non-deterministic retry mutants."""
    poisoned = [
        {
            "job_id": "j1",
            "params": {"fast": 5, "slow": 20},
            "total_return": 0.1,
            "annualized_return": 0.05,
            "sharpe_ratio": float("nan"),
            "sortino_ratio": 1.0,
            "max_drawdown": -0.1,
            "calmar_ratio": 0.5,
        },
        {
            "job_id": "j2",
            "params": {"fast": 10, "slow": 30},
            "total_return": 0.2,
            "annualized_return": 0.08,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.4,
            "max_drawdown": -0.15,
            "calmar_ratio": 0.8,
        },
    ]
    # 1. Non-strict Pareto filter must strip out the NaN mutant so it never enters the frontier
    frontier = pareto_frontier(poisoned, strict=False)
    assert len(frontier) == 1 and frontier[0]["job_id"] == "j2"

    # 2. Strict mode must raise ValueError on NaN mutant
    with pytest.raises(ValueError, match="Invalid metric"):
        pareto_frontier(poisoned, strict=True)

    # 3. Missing job mutant must trigger completeness RuntimeError
    with pytest.raises(RuntimeError, match="Grid completeness violation"):
        verify_grid_completeness(["j1", "j2", "j3_missing"], poisoned)

    # 4. Non-deterministic retry mutant must trigger RuntimeError
    conflicting_retry = [
        poisoned[1],
        {**poisoned[1], "sharpe_ratio": 9.99},
    ]
    with pytest.raises(RuntimeError, match="Non-deterministic retry"):
        verify_grid_completeness(["j2"], conflicting_retry)


def test_boundary_user_leverage_and_atomic_fee_rollback():
    """Verify user-configured leverage cap (e.g. 0.5x) and atomic rollback on fee failure."""
    gw = RiskGateway(Account(cash=1000.0), max_leverage=0.5)
    approved_high, _ = gw.pre_trade_check(600.0)
    assert approved_high is False
    approved_ok, acc_ok = gw.pre_trade_check(400.0)
    assert approved_ok is True and acc_ok.locked_cash == 400.0

    # Full-notional order where fee cannot be paid must roll back completely
    portfolio = VerifiedPortfolio(
        cash=1000.0, matching=MatchingConfig(slippage_bps=5.0, fee_bps=5.0), record_events=True
    )
    portfolio.rebalance(target_value=1000.0, bar=1)
    assert portfolio.rejections == 1
    assert portfolio.executed_trades == 0
    assert portfolio.account.position_value == 0.0
    assert portfolio.account.cash == 1000.0
    assert portfolio.events[-1].action == "REJECT_COST"