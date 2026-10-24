"""Stateless Ray backtest worker supporting single tasks and batched chunks."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import ray  # noqa: E402
from core_engine.backtester import run_single_backtest, run_verified_backtest  # noqa: E402


def _execute_one(prices, params: dict, risk_config: dict | None,
                 include_equity: bool, verified: bool,
                 job_id: str | None = None,
                 include_events: bool = False) -> dict:
    # Enforce read-only view so no worker can mutate shared market data in-place.
    prices_view = prices.view()
    prices_view.flags.writeable = False

    if verified:
        res = run_verified_backtest(
            prices_view, params, risk_config, include_equity, include_events
        )
    else:
        res = run_single_backtest(prices_view, params, risk_config, include_equity)
    if job_id is not None:
        res["job_id"] = job_id
    return res


@ray.remote
def backtest_worker(prices, params: dict, risk_config: dict | None,
                    include_equity: bool = False, verified: bool = False,
                    job_id: str | None = None,
                    include_events: bool = False) -> dict:
    return _execute_one(prices, params, risk_config, include_equity, verified, job_id, include_events)


@ray.remote
def backtest_batch_worker(prices, batch: list[tuple[str, dict]], risk_config: dict | None,
                          include_equity: bool = False, verified: bool = False,
                          include_events: bool = False) -> list[dict]:
    return [
        _execute_one(prices, params, risk_config, include_equity, verified, job_id, include_events)
        for job_id, params in batch
    ]