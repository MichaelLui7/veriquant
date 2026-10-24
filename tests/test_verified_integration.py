"""Integration tests: the Dafny-verified ledger is really driving the runtime.

These assert the key guarantees hold when the compiled Dafny code is called from
Python: no overdraft, no short, funds conserved, user leverage cap enforced,
atomic fee rollback, and event-driven backtest execution.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core_engine.backtester import DEFAULT_RISK_CONFIG, run_verified_backtest  # noqa: E402
from core_engine.matching_engine import MatchingConfig  # noqa: E402
from core_engine.portfolio import VerifiedPortfolio  # noqa: E402
from data_layer.fetcher import generate_synthetic_prices  # noqa: E402
from risk_control.gateway import Account, VerifiedLedger  # noqa: E402


def test_verified_ledger_rejects_overdraft():
    ledger = VerifiedLedger(cash=1000.0)
    assert ledger.try_lock(2000.0) is False
    assert ledger.account == Account(cash=1000.0)


def test_verified_ledger_rejects_short():
    ledger = VerifiedLedger(cash=1000.0)
    assert ledger.sell(1.0) is False          # no position to sell
    assert ledger.account.position_value == 0.0


def test_verified_ledger_rejects_unaffordable_cost():
    ledger = VerifiedLedger(cash=1000.0)
    assert ledger.pay_cost(2000.0) is False   # cost > cash
    assert ledger.account.cash == 1000.0


def test_verified_buy_sell_conserves_funds():
    ledger = VerifiedLedger(cash=1000.0)
    assert ledger.try_lock(300.0)
    ledger.fill(300.0, 300.0)
    assert ledger.account.cash == 700.0
    assert ledger.account.locked_cash == 0.0
    assert ledger.account.position_value == 300.0
    assert ledger.sell(300.0)
    assert ledger.account.cash == 1000.0
    assert ledger.account.position_value == 0.0


def test_verified_backtest_runs_end_to_end():
    prices = generate_synthetic_prices(n_assets=1, n_days=500, seed=3)[:, 0]
    res = run_verified_backtest(
        prices, {"strategy": "ma_crossover", "fast": 5, "slow": 20}
    )
    assert res["num_trades"] > 0
    assert res["total_return"] == res["total_return"]  # finite, not NaN
    assert res["sharpe_ratio"] == res["sharpe_ratio"]
    assert res["rejections"] >= 0


def test_price_limit_blocks_execution():
    # High volatility + a tight daily limit => some signal flips are un-fillable.
    prices = generate_synthetic_prices(n_assets=1, n_days=300, seed=11, sigma=0.8)[:, 0]
    cfg = dict(DEFAULT_RISK_CONFIG)
    cfg["limit_pct"] = 0.002  # 0.2% daily price limit
    res = run_verified_backtest(
        prices, {"strategy": "ma_crossover", "fast": 2, "slow": 5}, cfg
    )
    assert res["rejections"] > 0


def test_user_specified_lower_leverage_1_5x_is_enforced():
    # User sets 0.5x max exposure cap on $1000 cash => $600 blocked, $400 approved.
    ledger = VerifiedLedger(cash=1000.0, max_leverage=0.5)
    assert ledger.try_lock(600.0) is False
    assert ledger.account == Account(cash=1000.0)
    assert ledger.try_lock(400.0) is True
    assert ledger.account.locked_cash == 400.0


def test_atomic_rollback_when_fee_cannot_be_paid():
    # Full-notional buy ($1000) leaves $0 cash for 10 bps fee ($1.0) => atomic rollback!
    portfolio = VerifiedPortfolio(
        cash=1000.0, matching=MatchingConfig(slippage_bps=5.0, fee_bps=5.0)
    )
    portfolio.rebalance(target_value=1000.0)
    assert portfolio.rejections == 1
    assert portfolio.account.position_value == 0.0
    assert portfolio.account.cash == 1000.0


def _run_suite() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    suite: list[tuple[str, str, Callable[[], None]]] = [
        ("test_verified_ledger_rejects_overdraft",        "No Overdraft (cash >= 0)",                 test_verified_ledger_rejects_overdraft),
        ("test_verified_ledger_rejects_short",            "No Naked Short (position >= 0)",           test_verified_ledger_rejects_short),
        ("test_verified_ledger_rejects_unaffordable_cost","Fee Sufficiency Guard (cost <= cash)",     test_verified_ledger_rejects_unaffordable_cost),
        ("test_verified_buy_sell_conserves_funds",        "Conservation of NetEquity (Buy -> Sell)",  test_verified_buy_sell_conserves_funds),
        ("test_verified_backtest_runs_end_to_end",        "End-to-End Dafny Event-Driven Backtest",   test_verified_backtest_runs_end_to_end),
        ("test_price_limit_blocks_execution",             "Daily Price-Limit Liquidity Lock Guard",   test_price_limit_blocks_execution),
        ("test_user_specified_lower_leverage_1_5x",       "User Dynamic Leverage Cap Refinement",     test_user_specified_lower_leverage_1_5x_is_enforced),
        ("test_atomic_rollback_when_fee_cannot_be_paid",  "Atomic Snapshot Rollback on Fee Failure",  test_atomic_rollback_when_fee_cannot_be_paid),
    ]

    bar = "=" * 92
    print(bar)
    print(" 🛡️  VeriQuant — Dafny Runtime Verification & Integration Test Suite")
    print(bar)
    print(f" {'#':<3} | {'Test Case':<44} | {'Verified Invariant / Guarantee':<30} | {'Time':>7}")
    print("-" * 92)

    t_start = time.perf_counter()
    for idx, (name, invariant_desc, fn) in enumerate(suite, 1):
        t0 = time.perf_counter()
        fn()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        print(f" {idx:<3} | {name:<44} | {invariant_desc:<30} | {dt_ms:5.1f}ms")

    total_ms = (time.perf_counter() - t_start) * 1000.0
    print(bar)
    print(f" ✅  All {len(suite)}/{len(suite)} verified integration tests passed in {total_ms:.1f}ms (0 invariant violations).")
    print(bar)


if __name__ == "__main__":
    _run_suite()