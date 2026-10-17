"""Benchmark: single-process vs Ray grid search, printing the speedup.

Ray only pays off when each task is heavy enough that scheduling/deserialization
overhead is amortised — for a few hundred tiny tasks, single-process wins. This
benchmark therefore uses minute-level data and a large parameter grid, which is
the regime a real multi-asset / parameter scan lives in.

Run from the project root:
    python tests/benchmark_ray.py
"""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core_engine.backtester import DEFAULT_RISK_CONFIG, run_single_backtest  # noqa: E402
from data_layer.fetcher import generate_synthetic_prices  # noqa: E402
from distributed.scheduler import DistributedBacktestEngine  # noqa: E402

N_BARS = 120_000      # ~1.2 years of minute bars
FREQ = 252 * 390      # minute bars per year
NUM_CPUS = 8


def build_grid() -> list[dict]:
    return [
        {"fast": f, "slow": s}
        for f in range(3, 60, 3)
        for s in range(60, 500, 10)
        if f < s
    ]


def main() -> None:
    prices = generate_synthetic_prices(n_assets=1, n_days=N_BARS, seed=123, freq=FREQ)[:, 0]
    grid = build_grid()
    print(f"data: {prices.shape[0]:,} bars | grid: {len(grid):,} parameter combos | cpus: {NUM_CPUS}")

    t0 = time.perf_counter()
    single = [
        run_single_backtest(prices, {"strategy": "ma_crossover", **p}, DEFAULT_RISK_CONFIG)
        for p in grid
    ]
    t_single = time.perf_counter() - t0

    engine = DistributedBacktestEngine(num_cpus=NUM_CPUS)
    t0 = time.perf_counter()
    distributed = engine.run_grid_search(prices, grid, DEFAULT_RISK_CONFIG)
    t_ray = time.perf_counter() - t0
    engine.shutdown()

    speedup = t_single / t_ray if t_ray > 0 else float("inf")
    print(f"single-process : {t_single:8.3f}s")
    print(f"ray ({NUM_CPUS} cpus)  : {t_ray:8.3f}s")
    print(f"speedup        : {speedup:8.2f}x  ({len(grid):,} tasks)")

    best = distributed[0]
    print("\nTop result:")
    print(f"  params      : {best['params']}")
    print(f"  sharpe_ratio: {best['sharpe_ratio']:.3f}")
    print(f"  max_drawdown: {best['max_drawdown']:.3f}")
    print(f"  total_return: {best['total_return']:.3f}")


if __name__ == "__main__":
    main()
