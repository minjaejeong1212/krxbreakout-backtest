"""성과 지표·리포트."""
from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(series: pd.Series) -> float:
    peak = series.cummax()
    return float((series / peak - 1).min())


def max_consecutive(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def summarize(eq: pd.DataFrame, trades: pd.DataFrame, p, benchmark: pd.Series | None = None) -> dict:
    s: dict = {}
    if eq.empty:
        return {"error": "평가 데이터 없음"}
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    twr = eq["twr_index"]
    s["기간"] = f"{eq.index[0].date()} ~ {eq.index[-1].date()} ({years:.1f}년)"
    s["총입금액"] = int(eq["total_deposit"].iloc[-1])
    s["최종평가액"] = int(eq["equity"].iloc[-1])
    s["순손익(입금 제외)"] = int(eq["equity"].iloc[-1] - eq["total_deposit"].iloc[-1])
    s["전략 누적수익률(TWR)"] = round(float(twr.iloc[-1] - 1) * 100, 2)
    s["CAGR(TWR)"] = round(((twr.iloc[-1]) ** (1 / years) - 1) * 100, 2) if years > 0 and twr.iloc[-1] > 0 else None
    mdd = max_drawdown(twr)
    s["MDD(TWR)"] = round(mdd * 100, 2)
    s["MDD 경고(설정 한도 도달)"] = bool(-mdd >= p.mdd_alert)
    s["평균 보유 종목 수"] = round(float(eq["n_positions"].mean()), 2)
    s["주식 보유 비중 평균(%)"] = round(float((1 - eq["cash"] / eq["equity"]).mean()) * 100, 1)

    if trades is not None and not trades.empty:
        closed = trades[trades["exit_reason"] != "end_of_test"]
        r = closed["r_multiple"].dropna()
        wins, losses = closed[closed["pnl"] > 0], closed[closed["pnl"] <= 0]
        s["거래 수"] = int(len(closed))
        s["승률(%)"] = round(len(wins) / len(closed) * 100, 1) if len(closed) else None
        s["평균 R"] = round(float(r.mean()), 3) if len(r) else None
        s["평균 수익 R"] = round(float(wins["r_multiple"].mean()), 3) if len(wins) else None
        s["평균 손실 R"] = round(float(losses["r_multiple"].mean()), 3) if len(losses) else None
        gross_win, gross_loss = wins["pnl"].sum(), -losses["pnl"].sum()
        s["손익비(평균수익/평균손실)"] = (
            round(float(wins["pnl"].mean() / -losses["pnl"].mean()), 2) if len(wins) and len(losses) and losses["pnl"].mean() < 0 else None
        )
        if gross_loss > 0:
            s["Profit Factor"] = round(float(gross_win / gross_loss), 2)
        else:
            s["Profit Factor"] = 99.99 if gross_win > 0 else None  # 손실 거래 없음
        s["최대 연속 손실 횟수"] = max_consecutive((closed.sort_values("exit_date")["pnl"] <= 0).tolist())
        s["평균 보유일(영업일)"] = round(float(closed["holding_days"].mean()), 1) if len(closed) else None
        s["청산 사유별 건수"] = closed["exit_reason"].value_counts().to_dict()
        s["-1R보다 큰 손실(갭하락) 건수"] = int((r < -1.05).sum())

    yearly = (1 + eq["twr_ret"]).groupby(eq.index.year).prod() - 1
    s["연도별 수익률(%)"] = {int(k): round(float(v) * 100, 2) for k, v in yearly.items()}

    if benchmark is not None and len(benchmark):
        b = benchmark.reindex(eq.index).ffill().dropna()
        if len(b) > 1:
            s["벤치마크 누적수익률(%)"] = round(float(b.iloc[-1] / b.iloc[0] - 1) * 100, 2)
            s["벤치마크 MDD(%)"] = round(max_drawdown(b) * 100, 2)
            by = b.groupby(b.index.year).last() / b.groupby(b.index.year).first() - 1
            s["벤치마크 연도별(%)"] = {int(k): round(float(v) * 100, 2) for k, v in by.items()}
    return s


def to_markdown(summary: dict, p) -> str:
    lines = ["# 수렴·돌파 전략 백테스트 결과", ""]
    for k, v in summary.items():
        if isinstance(v, dict):
            lines.append(f"- **{k}**")
            for kk, vv in v.items():
                lines.append(f"  - {kk}: {vv}")
        else:
            lines.append(f"- **{k}**: {v}")
    lines += ["", "## 사용한 파라미터", "", "```"]
    lines += [f"{k} = {v}" for k, v in p.to_dict().items()]
    lines += ["```", "", "> 과거 성과가 미래 수익을 보장하지 않습니다. 거래대금이 근사치이거나 상장폐지 종목이 빠졌다면 결과가 낙관적으로 나올 수 있습니다."]
    return "\n".join(lines)


def plot_equity(eq: pd.DataFrame, path: str, benchmark: pd.Series | None = None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(eq.index, eq["twr_index"], label="Strategy (TWR)", color="#2b6cb0")
    if benchmark is not None and len(benchmark):
        b = benchmark.reindex(eq.index).ffill()
        axes[0].plot(eq.index, b / b.dropna().iloc[0], label="Benchmark", color="#a0aec0")
    axes[0].legend(frameon=False)
    axes[0].set_ylabel("Growth of 1")
    dd = eq["twr_index"] / eq["twr_index"].cummax() - 1
    axes[1].fill_between(eq.index, dd * 100, 0, color="#e53e3e", alpha=0.4)
    axes[1].set_ylabel("Drawdown %")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
