"""Integration tests: the Dafny-verified ledger is really driving the runtime.

These assert the key guarantees hold when the compiled Dafny code is called from
Python: no overdraft, no short, funds conserved, and the event-driven backtest
runs end-to-end through the verified ledger.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core_engine.backtester import DEFAULT_RISK_CONFIG, run_verified_backtest  # noqa: E402
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


if __name__ == "__main__":
    test_verified_ledger_rejects_overdraft()
    test_verified_ledger_rejects_short()
    test_verified_ledger_rejects_unaffordable_cost()
    test_verified_buy_sell_conserves_funds()
    test_verified_backtest_runs_end_to_end()
    test_price_limit_blocks_execution()
    print("Verified integration tests passed.")
