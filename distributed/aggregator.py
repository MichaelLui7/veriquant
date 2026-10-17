"""Aggregation of distributed backtest results."""

from __future__ import annotations


def sort_by_sharpe(results: list[dict]) -> list[dict]:
    """Return results sorted by Sharpe ratio, descending."""
    return sorted(results, key=lambda r: r["sharpe_ratio"], reverse=True)


def _dominates(a: dict, b: dict) -> bool:
    """True if `a` is at least as good as `b` on both objectives and strictly
    better on one. Objectives: maximize Sharpe, minimize drawdown (drawdown is
    negative, so "smaller drawdown" means a *larger* ``max_drawdown`` value)."""
    return (
        a["sharpe_ratio"] >= b["sharpe_ratio"] and
        a["max_drawdown"] >= b["max_drawdown"] and
        (a["sharpe_ratio"] > b["sharpe_ratio"] or
         a["max_drawdown"] > b["max_drawdown"])
    )


def pareto_frontier(results: list[dict]) -> list[dict]:
    """Keep the non-dominated results on (Sharpe, MaxDrawdown).

    A result `a` dominates `b` when ``a.sharpe >= b.sharpe`` and
    ``a.max_drawdown >= b.max_drawdown`` (i.e. `a` has higher risk-adjusted
    return *and* a smaller drawdown), with at least one strict inequality.
    This is the 2-D efficient frontier used to prune a large parameter grid.
    """
    frontier: list[dict] = []
    for r in results:
        if any(_dominates(f, r) for f in frontier):
            continue
        frontier = [f for f in frontier if not _dominates(r, f)]
        frontier.append(r)
    return frontier


def top_k(results: list[dict], k: int) -> list[dict]:
    return sort_by_sharpe(results)[:k]
