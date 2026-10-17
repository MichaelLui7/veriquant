"""Rich terminal UI components for VeriQuant CLI."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def render_verification_badge(approved: bool, cash: float, locked: float, notional: float) -> None:
    status = "[bold green]PASSED (Dafny Pre-Trade Gateway Approved)[/bold green]" if approved else (
        "[bold red]BLOCKED (Invariant Violation Prevented)[/bold red]"
    )
    body = (
        f"• Formal SpecModule : [cyan]VerifiedRisk.PreTradeGateway[/cyan] (Fixed-Point SCALE=10,000)\n"
        f"• Order Notional    : [yellow]${notional:,.2f}[/yellow]\n"
        f"• Gateway Decision  : {status}\n"
        f"• Post-Check State  : Cash=[green]${cash:,.2f}[/green] | Locked=[yellow]${locked:,.2f}[/yellow]"
    )
    console.print(Panel(body, title="🛡️ Dafny Formal Verification Gate", border_style="green" if approved else "red"))


def render_results_table(results: list[dict], pareto: list[dict], target_sharpe: float, elapsed: float) -> None:
    table = Table(
        title=f"🚀 Ray Distributed Backtest Top-5 Results (Elapsed: {elapsed:.2f}s | Pareto Frontier: {len(pareto)})",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Rank", justify="center")
    table.add_column("Params (Fast/Slow)", justify="center")
    table.add_column("Sharpe Ratio", justify="right")
    table.add_column("Sortino", justify="right")
    table.add_column("Annual Return", justify="right")
    table.add_column("Max Drawdown", justify="right")
    table.add_column("Trades / Rejections", justify="center")
    table.add_column("Target Met", justify="center")

    for idx, r in enumerate(results[:5], 1):
        p = r["params"]
        sharpe = r["sharpe_ratio"]
        met = "✅" if sharpe >= target_sharpe else "⚠️"
        rej = r.get("rejections", 0)
        table.add_row(
            f"#{idx}",
            f"fast={p.get('fast')}, slow={p.get('slow')}",
            f"[bold cyan]{sharpe:.3f}[/bold cyan]",
            f"{r['sortino_ratio']:.3f}",
            f"{r['annualized_return'] * 100:.2f}%",
            f"[red]{r['max_drawdown'] * 100:.2f}%[/red]",
            f"{r['num_trades']} / {rej}",
            met,
        )
    console.print(table)