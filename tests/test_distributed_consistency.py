"""Distributed consistency test: single-process == Ray, bit-exact.

The distributed engine must reproduce the single-process results exactly
(same float64 arithmetic, same ordering). This is the assertion to cite in
interviews for "deterministic distributed backtesting".
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np

from core_engine.backtester import DEFAULT_RISK_CONFIG, run_single_backtest
from data_layer.fetcher import generate_synthetic_prices
from distributed.scheduler import DistributedBacktestEngine

PARAM_GRID = [
    {"fast": f, "slow": s}
    for f in (5, 10, 20)
    for s in (30, 60, 120)
    if f < s
]


def _assert_identical(a: dict, b: dict) -> None:
    assert a["params"] == b["params"]
    for key in ("total_return", "annualized_return", "sharpe_ratio",
                "sortino_ratio", "max_drawdown", "calmar_ratio",
                "num_trades", "exposure"):
        assert a[key] == b[key], f"metric {key} differs: {a[key]} != {b[key]}"
    assert np.array_equal(a["equity"], b["equity"]), "equity curve differs"


def test_single_vs_distributed_identical():
    prices = generate_synthetic_prices(n_assets=1, n_days=750, seed=7)[:, 0]

    single = [
        run_single_backtest(prices, {"strategy": "ma_crossover", **p},
                            DEFAULT_RISK_CONFIG, include_equity=True)
        for p in PARAM_GRID
    ]
    single_sorted = sorted(single, key=lambda r: r["sharpe_ratio"], reverse=True)

    engine = DistributedBacktestEngine(num_cpus=2)
    try:
        distributed = engine.run_grid_search(prices, PARAM_GRID, DEFAULT_RISK_CONFIG,
                                             include_equity=True)
    finally:
        engine.shutdown()

    assert len(single_sorted) == len(distributed) == len(PARAM_GRID)
    for a, b in zip(single_sorted, distributed):
        _assert_identical(a, b)


if __name__ == "__main__":
    test_single_vs_distributed_identical()
    print(f"Consistency test passed: {len(PARAM_GRID)} params, single == distributed (bit-exact).")
