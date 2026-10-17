"""FastMCP Server exposing VeriQuant verified tools to external AI Agents."""

from __future__ import annotations

from core_engine.config import load_risk_config
from data_layer.fetcher import generate_synthetic_prices
from distributed.scheduler import DistributedBacktestEngine
from risk_control.gateway import Account, RiskGateway

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("VeriQuant-Verified-Engine")
except ImportError:
    mcp = None  # Allows importing module without `mcp` extra installed


def check_order_safety(cash: float, order_notional: float) -> dict:
    """Dafny-verified pre-trade check (guarantees no overdraft & <=2.0x leverage)."""
    gw = RiskGateway(Account(cash=cash))
    approved, acc = gw.pre_trade_check(order_notional)
    return {
        "approved": approved,
        "cash_after": acc.cash,
        "locked_cash_after": acc.locked_cash,
        "equity_conserved": acc.equity == cash,
    }


def distributed_ma_scan(n_days: int = 500, verified: bool = True) -> dict:
    """Run Ray zero-copy parameter scan and return the top configuration."""
    prices = generate_synthetic_prices(n_assets=1, n_days=n_days, seed=42)[:, 0]
    grid = [{"fast": f, "slow": s} for f in (5, 10, 20) for s in (30, 60, 120) if f < s]
    engine = DistributedBacktestEngine(num_cpus=2)
    try:
        res = engine.run_grid_search(prices, grid, load_risk_config(), verified=verified)
    finally:
        engine.shutdown()
    return res[0]


if mcp is not None:
    mcp.tool()(check_order_safety)
    mcp.tool()(distributed_ma_scan)

if __name__ == "__main__" and mcp is not None:
    mcp.run()