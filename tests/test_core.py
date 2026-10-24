"""Unit tests for metrics and result aggregation (no Ray required)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np

from core_engine.metrics import max_drawdown, sharpe_ratio, sortino_ratio
from distributed.aggregator import (
    is_valid_result,
    pareto_frontier,
    sort_by_sharpe,
)

def makeresult(sharpe,mdd):
    return{
        "total_return": 0.15,
        "annualized_return": 0.12,
        "sharpe_ratio": sharpe,
        "sortino_ratio": 1.0,
        "max_drawdown": mdd,
        "calmar_ratio": 0.8,

    }
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
        makeresult(0.5, -0.1),
        makeresult(1.2, -0.3),
        makeresult(0.9, -0.2),
    ]

    ordered = sort_by_sharpe(results)
    assert [r["sharpe_ratio"] for r in ordered] == [1.2, 0.9, 0.5]


def test_pareto_frontier():
    results = [
        makeresult(1.0, -0.10),
        makeresult(0.8, -0.20),
        makeresult(1.5, -0.50),
        makeresult(0.9, -0.05),
    ]

    frontier = pareto_frontier(results)

    sharpe_values = {
        r["sharpe_ratio"] for r in frontier
    }

    assert sharpe_values == {1.0, 1.5, 0.9}
    assert 0.8 not in sharpe_values

def test_invalid_result_missing_metrics():
    incomplete = {
        "sharpe_ratio": 1.2,
        "max_drawdown": -0.3
    }

    assert is_valid_result(incomplete) is False


if __name__ == "__main__":
    test_max_drawdown()
    test_sharpe_zero_variance()
    test_sortino_ignores_upside()
    test_sort_by_sharpe()
    test_pareto_frontier()
    print("Core unit tests passed.")
