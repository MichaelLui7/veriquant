"""Natural-language intent parser (LLM with deterministic regex fallback)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


@dataclass
class BacktestIntent:
    strategy: str = "ma_crossover"
    n_days: int = 750
    target_sharpe: float = 1.0
    max_leverage: float = 2.0
    order_notional_check: float = 300_000.0
    verified: bool = True
    fast_grid: list[int] = field(default_factory=lambda: [5, 10, 15, 20])
    slow_grid: list[int] = field(default_factory=lambda: [30, 60, 90, 120])


def parse_intent(prompt: str) -> BacktestIntent:
    """Parse a natural-language prompt into a structured BacktestIntent.

    Uses OpenAI-compatible API if OPENAI_API_KEY is set; otherwise falls back to
    a deterministic heuristic parser so demos and tests work offline.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            return _parse_with_llm(prompt, api_key)
        except Exception:
            pass
    return _parse_heuristic(prompt)


def _parse_heuristic(prompt: str) -> BacktestIntent:
    intent = BacktestIntent()

    # 解析年份或天数，例如 "过去3年" / "过去三年" / "500天"
    cn_num = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    year_match = re.search(r"(\d+|[一二两三四五])\s*年", prompt)
    if year_match:
        val = year_match.group(1)
        years = int(val) if val.isdigit() else cn_num.get(val, 3)
        intent.n_days = years * 252

    day_match = re.search(r"(\d+)\s*(?:天|bars|days)", prompt, re.I)
    if day_match:
        intent.n_days = int(day_match.group(1))

    # 解析目标夏普比率，例如 "夏普比率目标1.5" / "sharpe > 1.2"
    sharpe_match = re.search(r"(?:夏普|sharpe)[^0-9]*([0-9]+(?:\.[0-9]+)?)", prompt, re.I)
    if sharpe_match:
        intent.target_sharpe = float(sharpe_match.group(1))

    # 解析杠杆或试探下单金额，例如 "杠杆1.5"
    lev_match = re.search(r"(?:杠杆|leverage)[^0-9]*([0-9]+(?:\.[0-9]+)?)", prompt, re.I)
    if lev_match:
        intent.max_leverage = float(lev_match.group(1))

    if "vector" in prompt.lower() or "向量" in prompt:
        intent.verified = False

    return intent


def _parse_with_llm(prompt: str, api_key: str) -> BacktestIntent:
    import urllib.request

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    system_msg = (
        "Extract backtest parameters from user prompt as JSON with keys: "
        "n_days (int), target_sharpe (float), max_leverage (float), verified (bool)."
    )
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parsed = json.loads(data["choices"][0]["message"]["content"])
    return BacktestIntent(
        n_days=int(parsed.get("n_days", 750)),
        target_sharpe=float(parsed.get("target_sharpe", 1.0)),
        max_leverage=float(parsed.get("max_leverage", 2.0)),
        verified=bool(parsed.get("verified", True)),
    )