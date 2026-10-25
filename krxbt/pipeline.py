"""데이터 로드 → 신호 → 백테스트 → 요약을 한 번에. run_backtest.py · validate.py 공용."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .backtest import Backtester, index_trend_ok
from .config import Params
from .report import summarize
from .signals import compute_signals


@dataclass
class Dataset:
    raw: dict
    failed: pd.DataFrame = field(default_factory=pd.DataFrame)
    universe: pd.DataFrame = field(default_factory=pd.DataFrame)
    ticker_market: dict = field(default_factory=dict)
    index_close: dict = field(default_factory=dict)
    source: str = "fdr"


def load_dataset(source: str, start: str, end: str, warmup_days: int = 120, limit=None,
                 include_delisted=True, cache_dir="cache", data_dir="krx_csv", exclude=None) -> Dataset:
    from .data import apply_exclusions, attach_shares, get_universe, load_csv_dir, load_fdr

    fetch_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")
    if source == "fdr":
        import FinanceDataReader as fdr

        uni = get_universe(include_delisted=include_delisted)
        if limit:
            uni = uni.head(limit)
        raw, failed = load_fdr(uni["code"].tolist(), fetch_start, end, cache_dir)
        raw = attach_shares(raw, uni)
        tm = dict(zip(uni["code"], uni["market"].astype(str)))
        idx = {}
        try:
            idx = {"KOSPI": fdr.DataReader("KS11", fetch_start, end)["Close"],
                   "KOSDAQ": fdr.DataReader("KQ11", fetch_start, end)["Close"]}
        except Exception as e:  # noqa: BLE001
            print(f"[경고] 지수 수집 실패 → 시장 필터·벤치마크 불가: {e}")
        ds = Dataset(raw, failed, uni, tm, idx, source)
    elif source == "csv":
        raw, failed = load_csv_dir(data_dir)
        ds = Dataset(raw, failed, source=source)
    else:
        from .synthetic import make_universe, make_index

        raw = make_universe()
        tm = {t: ("KOSPI" if i % 2 else "KOSDAQ") for i, t in enumerate(raw)}
        ds = Dataset(raw, ticker_market=tm, index_close=make_index(), source=source)
    ds.raw = apply_exclusions(ds.raw, exclude)
    return ds


def run_one(ds: Dataset, p: Params):
    data = {t: compute_signals(df, p) for t, df in ds.raw.items()}
    index_ok = {k: index_trend_ok(v, p) for k, v in ds.index_close.items()} if p.market_filter else {}
    eq, trades, skipped = Backtester(data, p, ds.ticker_market, index_ok).run()
    bench = ds.index_close.get("KOSDAQ")
    summary = summarize(eq, trades, p, bench)
    if "KOSPI" in ds.index_close and not eq.empty:
        b = ds.index_close["KOSPI"].reindex(eq.index).ffill().dropna()
        if len(b) > 1:
            summary["KOSPI 누적수익률(%)"] = round(float(b.iloc[-1] / b.iloc[0] - 1) * 100, 2)
    return data, eq, trades, skipped, summary


# 문서 '합격 기준' (검증 구간, 비용 반영 후)
CRITERIA = [
    ("거래 수 40건 이상", lambda s, ins: (s.get("거래 수") or 0) >= 40),
    ("거래당 평균 +0.15R 이상", lambda s, ins: (s.get("평균 R") or -9) >= 0.15),
    ("Profit Factor 1.3 이상", lambda s, ins: (s.get("Profit Factor") or 0) >= 1.3),
    ("최대 낙폭 10% 이하", lambda s, ins: (s.get("MDD(TWR)") or -100) >= -10),
    ("설정 구간 대비 평균 R 절반 이상 유지",
     lambda s, ins: ins is not None and (ins.get("평균 R") or 0) > 0 and (s.get("평균 R") or -9) >= 0.5 * ins["평균 R"]),
]


def check_criteria(oos: dict, ins: dict | None):
    rows = [{"기준": name, "통과": bool(fn(oos, ins))} for name, fn in CRITERIA]
    return rows, all(r["통과"] for r in rows)
