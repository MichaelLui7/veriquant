"""Typer CLI entry point: `veriquant agent`, `veriquant verify-gate`, `veriquant benchmark`."""

from __future__ import annotations

import sys

# Windows consoles default to a legacy code page (GBK/cp936) that cannot encode
# the Unicode/emoji used by the Rich UI; force UTF-8 so the CLI never crashes.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

import time
import typer

from agent_cli.planner import parse_intent
from agent_cli.ui import console, render_results_table, render_verification_badge
from core_engine.config import load_risk_config
from data_layer.fetcher import generate_synthetic_prices
from distributed.aggregator import pareto_frontier
from distributed.scheduler import DistributedBacktestEngine
from risk_control.gateway import Account, RiskGateway

app = typer.Typer(help="VeriQuant: Dafny-Verified Distributed Quant Backtest & Agent Engine")


@app.command("agent")
def run_agent(
    prompt: str = typer.Argument(
        "用MA交叉策略回测过去3年数据，夏普比率目标1.2以上",
        help="自然语言回测与风控指令",
    ),
    cpus: int = typer.Option(4, "--cpus", "-c", help="Ray Worker 并发核数"),
) -> None:
    """解析自然语言指令 -> Dafny 形式化风控校验 -> Ray 零拷贝分布式网格回测。"""
    console.rule("[bold blue]VeriQuant Neuro-Symbolic Agent Workflow[/bold blue]")
    console.print(f"💬 [bold]User Prompt:[/bold] {prompt}")

    intent = parse_intent(prompt)
    risk_cfg = load_risk_config()
    risk_cfg["max_leverage"] = intent.max_leverage

    # Step 1: Dafny 事前风控网关校验
    gw = RiskGateway(Account(cash=float(risk_cfg["initial_capital"])))
    approved, post_acc = gw.pre_trade_check(intent.order_notional_check)
    render_verification_badge(approved, post_acc.cash, post_acc.locked_cash, intent.order_notional_check)

    # Step 2: 构造参数网格并启动 Ray 分布式回测
    grid = [
        {"fast": f, "slow": s}
        for f in intent.fast_grid
        for s in intent.slow_grid
        if f < s
    ]
    prices = generate_synthetic_prices(n_assets=1, n_days=intent.n_days, seed=42)[:, 0]

    t0 = time.perf_counter()
    engine = DistributedBacktestEngine(num_cpus=cpus)
    try:
        results = engine.run_grid_search(
            prices, grid, risk_cfg, strategy=intent.strategy, verified=intent.verified
        )
    finally:
        engine.shutdown()
    elapsed = time.perf_counter() - t0

    frontier = pareto_frontier(results)
    render_results_table(results, frontier, intent.target_sharpe, elapsed)


@app.command("verify-gate")
def verify_gate(
    cash: float = typer.Option(100_000.0, help="初始可用资金"),
    notional: float = typer.Option(30_000.0, help="拟下单冻结金额"),
) -> None:
    """直接调用 Dafny 编译生成的风控网关测试单笔订单拦截。"""
    gw = RiskGateway(Account(cash=cash))
    approved, acc = gw.pre_trade_check(notional)
    render_verification_badge(approved, acc.cash, acc.locked_cash, notional)


if __name__ == "__main__":
    app()