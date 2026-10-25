"""수렴·돌파 전략 포트폴리오 백테스트 실행.

예시
  python run_backtest.py --source fdr                     # 전체 종목 (처음엔 다운로드에 시간 걸림)
  python run_backtest.py --source fdr --limit 200         # 앞 200종목만 빠르게 시험
  python run_backtest.py --source csv --data-dir krx_csv  # 직접 받은 KRX CSV 폴더
  python run_backtest.py --source synthetic               # 코드 동작 확인용 가짜 데이터
  python run_backtest.py --source fdr --start 2021-10-25 --end 2024-10-25   # 기간 분리 (설정 구간)
"""
import argparse
import json
import os

import pandas as pd

from krxbt.backtest import Backtester
from krxbt.config import Params
from krxbt.data import apply_exclusions, coverage_table, get_universe, load_csv_dir, load_fdr
from krxbt.report import plot_equity, summarize, to_markdown
from krxbt.signals import compute_signals


def load_benchmark(start, end):
    try:
        import FinanceDataReader as fdr
        return {"KOSPI": fdr.DataReader("KS11", start, end)["Close"], "KOSDAQ": fdr.DataReader("KQ11", start, end)["Close"]}
    except Exception as e:  # noqa: BLE001
        print(f"[경고] 벤치마크 수집 실패: {e}")
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["fdr", "csv", "synthetic"], default="fdr")
    ap.add_argument("--data-dir", default="krx_csv")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--exclude", default=None, help="관리종목 등 제외 기간 CSV (code,start,end)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-delisted", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    p = Params()
    if args.start:
        p.start = args.start
    if args.end:
        p.end = args.end
    fetch_start = (pd.Timestamp(p.start) - pd.Timedelta(days=p.warmup_days)).strftime("%Y-%m-%d")
    os.makedirs(args.out, exist_ok=True)

    failed = pd.DataFrame()
    if args.source == "fdr":
        uni = get_universe(include_delisted=not args.no_delisted)
        if args.limit:
            uni = uni.head(args.limit)
        uni.to_csv(os.path.join(args.out, "universe.csv"), index=False)
        print(f"대상 종목 {len(uni)}개 (상장폐지 포함 {int(uni['delisted'].sum())}개)")
        raw, failed = load_fdr(uni["code"].tolist(), fetch_start, p.end, args.cache_dir)
    elif args.source == "csv":
        raw, failed = load_csv_dir(args.data_dir)
    else:
        from krxbt.synthetic import make_universe
        raw = make_universe()
        p.start, p.end = "2022-03-01", "2024-05-31"
        p.min_avg_value = 1e8

    raw = apply_exclusions(raw, args.exclude)
    data = {t: compute_signals(df, p) for t, df in raw.items()}

    # 1차 스캔 결과 (기존 스캐너와 같은 3개 파일)
    coverage_table(data).to_csv(os.path.join(args.out, "coverage.csv"), index=False)
    failed.to_csv(os.path.join(args.out, "failed_tickers.csv"), index=False)
    sig_rows = []
    for t, df in data.items():
        s = df[df["signal"] & (df.index >= p.start) & (df.index <= p.end)]
        for d, r in s.iterrows():
            sig_rows.append({"code": t, "date": d.date(), "close": r["Close"], "resistance": r["resistance"],
                             "atr": r["atr"], "range_ratio": r["range_ratio"], "atr_ratio": r["atr_ratio"],
                             "vol_ratio": r["vol_ratio"], "avg_value_prev": r["avg_value_prev"]})
    pd.DataFrame(sig_rows).to_csv(os.path.join(args.out, "signals.csv"), index=False)
    print(f"수집 성공 {len(data)} / 실패 {len(failed)} / 신호 {len(sig_rows)}건")

    eq, trades, skipped = Backtester(data, p).run()
    bench = load_benchmark(p.start, p.end) if args.source == "fdr" else {}
    summary = summarize(eq, trades, p, bench.get("KOSDAQ"))
    if "KOSPI" in bench:
        b = bench["KOSPI"]
        summary["KOSPI 누적수익률(%)"] = round(float(b.iloc[-1] / b.iloc[0] - 1) * 100, 2)

    eq.to_csv(os.path.join(args.out, "equity.csv"))
    trades.to_csv(os.path.join(args.out, "trades.csv"), index=False)
    skipped.to_csv(os.path.join(args.out, "skipped_signals.csv"), index=False)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(summary, p))
    plot_equity(eq, os.path.join(args.out, "equity.png"), bench.get("KOSDAQ"))

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
