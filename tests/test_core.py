"""Unit tests for metrics and result aggregation (no Ray required)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np

from core_engine.metrics import max_drawdown, sharpe_ratio, sortino_ratio
from distributed.aggregator import pareto_frontier, sort_by_sharpe


def test_max_drawdown():
    eq = np.array([1.0, 1.2, 0.9, 1.1, 0.7, 0.8])
    assert max_drawdown(eq) == 0.7 / 1.2 - 1.0


def test_sharpe_zero_variance():
    assert sharpe_ratio(np.array([0.01, 0.01, 0.01])) == 0.0


def test_sortino_ignores_upside():
    rets = np.array([0.01, -0.02, 0.01, -0.03])
    assert sortino_ratio(rets) < 0


def test_sort_by_sharpe():
    results = [
        {"sharpe_ratio": 0.5, "max_drawdown": -0.1},
        {"sharpe_ratio": 1.2, "max_drawdown": -0.3},
        {"sharpe_ratio": 0.9, "max_drawdown": -0.2},
    ]
    ordered = sort_by_sharpe(results)
    assert [r["sharpe_ratio"] for r in ordered] == [1.2, 0.9, 0.5]


def test_pareto_frontier():
    results = [
        {"sharpe_ratio": 1.0, "max_drawdown": -0.10},   # dominates (0.8,-0.20)
        {"sharpe_ratio": 0.8, "max_drawdown": -0.20},   # dominated
        {"sharpe_ratio": 1.5, "max_drawdown": -0.50},   # higher sharpe but worse dd
        {"sharpe_ratio": 0.9, "max_drawdown": -0.05},   # non-dominated (best dd)
    ]
    frontier = pareto_frontier(results)
    sharpe_values = {r["sharpe_ratio"] for r in frontier}
    assert sharpe_values == {1.0, 1.5, 0.9}
    assert 0.8 not in sharpe_values


if __name__ == "__main__":
    test_max_drawdown()
    test_sharpe_zero_variance()
    test_sortino_ignores_upside()
    test_sort_by_sharpe()
    test_pareto_frontier()
    print("Core unit tests passed.")
