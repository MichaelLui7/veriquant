"""Master scheduler: canonical job_id assignment, batching, and completeness verification."""

from __future__ import annotations

import hashlib
import json
import numpy as np
import ray

from distributed import aggregator
from distributed.cluster import init_cluster, shutdown
from distributed.shared_memory import put
from distributed.worker import backtest_batch_worker, backtest_worker


def make_job_id(params: dict, strategy: str, verified: bool, risk_config: dict | None) -> str:
    """Generate a deterministic, canonical job_id from task specifications."""
    spec = {
        "strategy": strategy,
        "verified": bool(verified),
        "params": {k: params[k] for k in sorted(params)},
        "risk": {k: risk_config[k] for k in sorted(risk_config)} if risk_config else {},
    }
    raw = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class DistributedBacktestEngine:
    """Fan a parameter grid over a Ray cluster with completeness & idempotency guarantees."""

    def __init__(self, num_cpus: int | None = None) -> None:
        self.resources = init_cluster(num_cpus=num_cpus)

    def run_grid_search(self, prices: np.ndarray, param_grid: list[dict],
                        risk_config: dict | None = None,
                        strategy: str = "ma_crossover",
                        include_equity: bool = False,
                        verified: bool = False,
                        batch_size: int = 1,
                        include_events: bool = False) -> list[dict]:
        """Run every parameter combination, verify job completeness, and sort by Sharpe."""
        prices_ref = put(prices)

        jobs: list[tuple[str, dict]] = []
        expected_ids: list[str] = []
        for idx, p in enumerate(param_grid):
            full_params = {**p, "strategy": strategy}
            jid = make_job_id(p, strategy, verified, risk_config)
            jobs.append((jid, full_params))
            if jid not in expected_ids:
                expected_ids.append(jid)

        if batch_size <= 1:
            futures = [
                backtest_worker.remote(
                    prices_ref, full_params, risk_config, include_equity, verified, jid, include_events
                )
                for jid, full_params in jobs
            ]
            raw_results = ray.get(futures)
        else:
            batches = [jobs[i:i + batch_size] for i in range(0, len(jobs), batch_size)]
            futures = [
                backtest_batch_worker.remote(
                    prices_ref, b, risk_config, include_equity, verified, include_events
                )
                for b in batches
            ]
            nested = ray.get(futures)
            raw_results = [item for sublist in nested for item in sublist]

        deduped_map = aggregator.verify_grid_completeness(expected_ids, raw_results)
        return aggregator.sort_by_sharpe(list(deduped_map.values()))

    def shutdown(self) -> None:
        shutdown()