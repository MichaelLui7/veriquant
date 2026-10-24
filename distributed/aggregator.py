"""Aggregation, validation, and Pareto pruning of distributed backtest results."""

from __future__ import annotations

import json
import math

REQUIRED_SCALAR_KEYS = (
    "total_return",
    "annualized_return",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "calmar_ratio",
)


def is_valid_result(r: dict) -> bool:
    """Check that all core performance metrics are finite numbers (no NaN / Inf)
    and max_drawdown adheres to the non-positive convention (<= 0.0).
    """
    for k in REQUIRED_SCALAR_KEYS:
        val = r.get(k)
        if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
            return False
    if r["max_drawdown"] > 1e-12:
        return False
    return True


def _canonical_tie_key(r: dict) -> str:
    if "job_id" in r:
        return str(r["job_id"])
    return json.dumps(r.get("params", {}), sort_keys=True)


def sort_by_sharpe(results: list[dict], strict: bool = False) -> list[dict]:
    """Return valid results sorted by (sharpe_ratio DESC, max_drawdown DESC, tie_key ASC).

    Filters out NaN/Inf results so they never corrupt rankings (or raises ValueError
    when ``strict=True``).
    """
    valid: list[dict] = []
    for r in results:
        if is_valid_result(r):
            valid.append(r)
        elif strict:
            raise ValueError(f"Invalid metric (NaN/Inf/positive MDD) in result: {r}")

    return sorted(
        valid,
        key=lambda r: (-float(r["sharpe_ratio"]), -float(r["max_drawdown"]), _canonical_tie_key(r)),
    )


def _dominates(a: dict, b: dict) -> bool:
    """True if `a` dominates `b` on (Sharpe >=, MaxDrawdown >=) with at least one strict >."""
    return (
        a["sharpe_ratio"] >= b["sharpe_ratio"]
        and a["max_drawdown"] >= b["max_drawdown"]
        and (
            a["sharpe_ratio"] > b["sharpe_ratio"]
            or a["max_drawdown"] > b["max_drawdown"]
        )
    )


def pareto_frontier(results: list[dict], strict: bool = False) -> list[dict]:
    """Keep non-dominated valid results on (Sharpe, MaxDrawdown), sorted deterministically."""
    ordered = sort_by_sharpe(results, strict=strict)
    frontier: list[dict] = []
    for r in ordered:
        if any(
            _dominates(f, r)
            or (f["sharpe_ratio"] == r["sharpe_ratio"] and f["max_drawdown"] == r["max_drawdown"])
            for f in frontier
        ):
            continue
        frontier = [f for f in frontier if not _dominates(r, f)]
        frontier.append(r)
    return frontier


def verify_grid_completeness(expected_job_ids: list[str], raw_results: list[dict]) -> dict[str, dict]:
    """Idempotent deduplication (Exactly-Once Effect) and completeness verification.

    Ensures:
      1. Duplicate task completions (e.g. from worker retries) are deduplicated
         and verified to be identical.
      2. ExpectedJobIDs == CompletedJobIDs (no missing or phantom tasks).
    """
    deduped: dict[str, dict] = {}
    for res in raw_results:
        jid = res.get("job_id")
        if not jid:
            raise ValueError("Worker result missing canonical 'job_id'")
        if jid in deduped:
            # Verify retry idempotency: scalar metrics must match
            for k in REQUIRED_SCALAR_KEYS:
                if deduped[jid][k] != res[k]:
                    raise RuntimeError(f"Non-deterministic retry detected for job_id={jid} on {k}")
        else:
            deduped[jid] = res

    expected_set = set(expected_job_ids)
    completed_set = set(deduped.keys())
    missing = expected_set - completed_set
    unexpected = completed_set - expected_set
    if missing or unexpected:
        raise RuntimeError(
            f"Grid completeness violation! Missing jobs: {sorted(missing)}, "
            f"Unexpected jobs: {sorted(unexpected)}"
        )
    return deduped


def top_k(results: list[dict], k: int) -> list[dict]:
    return sort_by_sharpe(results)[:k]