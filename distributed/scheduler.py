"""Master scheduler: fan out a parameter grid to Ray workers.

Sharding is by **parameter space** (and, in principle, by cross-sectional
asset), *never* by time: strategies are stateful (moving averages, rolling
position), so time-slicing would break carry-over state or leak look-ahead.
Workers each re-run the full, shared price series with their own parameters.
"""

from __future__ import annotations

import numpy as np
import ray

from distributed import aggregator
from distributed.cluster import init_cluster, shutdown
from distributed.shared_memory import put
from distributed.worker import backtest_worker


class DistributedBacktestEngine:
    """Fan a parameter grid over a Ray cluster and aggregate by Sharpe."""

    def __init__(self, num_cpus: int | None = None) -> None:
        self.resources = init_cluster(num_cpus=num_cpus)

    def run_grid_search(self, prices: np.ndarray, param_grid: list[dict],
                        risk_config: dict | None = None,
                        strategy: str = "ma_crossover",
                        include_equity: bool = False,
                        verified: bool = False) -> list[dict]:
        """Run every parameter combination and return results sorted by Sharpe.

        The price matrix is placed in the object store once; every worker reads
        it zero-copy (Ray auto-dereferences the ObjectRef to a shared-memory
        view on the same node). ``verified`` selects the event-driven backtest
        that routes every balance change through the Dafny-verified ledger.
        """
        prices_ref = put(prices)
        futures = [
            backtest_worker.remote(prices_ref, {**p, "strategy": strategy},
                                   risk_config, include_equity, verified)
            for p in param_grid
        ]
        results = ray.get(futures)
        return aggregator.sort_by_sharpe(results)

    def shutdown(self) -> None:
        shutdown()
