"""Stateless Ray backtest worker.

Ray automatically dereferences an ObjectRef argument: when the scheduler passes
``ray.put(prices)`` to this task, the worker receives the array directly. On a
single node Ray hands over a read-only *shared-memory* view (zero-copy, no
per-task serialization), which is what keeps the grid search near-linear.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import ray  # noqa: E402
from core_engine.backtester import run_single_backtest, run_verified_backtest  # noqa: E402


@ray.remote
def backtest_worker(prices, params: dict, risk_config: dict | None,
                    include_equity: bool = False, verified: bool = False) -> dict:
    # `prices` is the auto-dereferenced array from the Plasma object store.
    if verified:
        return run_verified_backtest(prices, params, risk_config, include_equity)
    return run_single_backtest(prices, params, risk_config, include_equity)
