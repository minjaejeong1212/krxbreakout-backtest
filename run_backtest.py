"""수렴·돌파 전략 포트폴리오 백테스트 실행 (한 번).

예시
  python run_backtest.py --source fdr --limit 200              # v1 규칙, 앞 200종목
  python run_backtest.py --source fdr --preset v2               # v2 규칙, 전체 종목
  python run_backtest.py --source fdr --stage 4                 # 1~4단계까지 적용
  python run_backtest.py --source synthetic                     # 코드 동작 확인용 가짜 데이터
  python run_backtest.py --source csv --data-dir krx_csv        # 직접 받은 KRX CSV 폴더

단계별 비교와 최종 검증은 validate.py 를 쓴다.
"""
import argparse
import json
import os

import pandas as pd

from krxbt.config import STAGES, preset, stage_params
from krxbt.data import coverage_table
from krxbt.pipeline import load_dataset, run_one
from krxbt.report import plot_equity, to_markdown


def diagnostics(summary, ds, data, sig_rows, skipped, p):
    summary["[진단] 데이터 수집 성공 종목"] = len(data)
    summary["[진단] 데이터 수집 실패 종목"] = len(ds.failed)
    if len(ds.failed):
        summary["[진단] 실패 예시"] = ds.failed.head(3).to_dict("records")
    summary["[진단] 매수 신호 수"] = len(sig_rows)
    if not skipped.empty:
        summary["[진단] 진입 안 한 이유"] = skipped["reason"].value_counts().to_dict()
    if data:
        lens = [len(df) for df in data.values()]
        summary["[진단] 종목당 일봉 수(최소/중앙/최대)"] = f"{min(lens)} / {int(pd.Series(lens).median())} / {max(lens)}"
        cond = {"수렴(범위)": 0, "수렴(ATR)": 0, "추세": 0, "돌파가격": 0, "거래량": 0, "거래대금": 0, "캔들품질": 0}
        for df in data.values():
            w = df[(df.index >= p.start) & (df.index <= p.end)]
            cond["수렴(범위)"] += int((w["range_ratio"] <= p.range_ratio_max).sum())
            cond["수렴(ATR)"] += int((w["atr_ratio"] <= p.atr_ratio_max).sum())
            cond["추세"] += int((w["Close"] > w["ma_trend"]).sum())
            cond["돌파가격"] += int((w["Close"] >= w["resistance"] * p.breakout_buffer).sum())
            cond["거래량"] += int((w["vol_ratio"] >= p.vol_mult).sum())
            cond["거래대금"] += int((w["avg_value_prev"] >= p.min_avg_value).sum())
            cond["캔들품질"] += int(((w["close_location"] >= p.min_close_location) & (w["day_return"] <= p.max_day_return)).sum())
        summary["[진단] 조건별 충족 일수(종목 합계)"] = cond


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["fdr", "csv", "synthetic"], default="fdr")
    ap.add_argument("--preset", choices=["v1", "v2"], default="v1")
    ap.add_argument("--stage", type=int, help=f"1~{len(STAGES)} 단계까지 누적 적용 (preset 보다 우선)")
    ap.add_argument("--data-dir", default="krx_csv")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--exclude", default=None, help="관리종목 등 제외 기간 CSV (code,start,end)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-delisted", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    p = stage_params(args.stage) if args.stage else preset(args.preset)
    if args.source == "synthetic":
        p.start, p.end, p.min_avg_value, p.min_marcap = "2022-03-01", "2024-04-30", 1e8, 0
    if args.start:
        p.start = args.start
    if args.end:
        p.end = args.end
    os.makedirs(args.out, exist_ok=True)

    ds = load_dataset(args.source, p.start, p.end, p.warmup_days, args.limit, not args.no_delisted,
                      args.cache_dir, args.data_dir, args.exclude)
    if not ds.universe.empty:
        ds.universe.to_csv(os.path.join(args.out, "universe.csv"), index=False)
    data, eq, trades, skipped, summary = run_one(ds, p)
    summary = {"규칙": f"{args.preset}" if not args.stage else STAGES[args.stage - 1][0], **summary}

    coverage_table(data).to_csv(os.path.join(args.out, "coverage.csv"), index=False)
    ds.failed.to_csv(os.path.join(args.out, "failed_tickers.csv"), index=False)
    sig_rows = []
    for t, df in data.items():
        s = df[df["signal"] & (df.index >= p.start) & (df.index <= p.end)]
        for d, r in s.iterrows():
            sig_rows.append({"code": t, "date": d.date(), "close": r["Close"], "resistance": r["resistance"],
                             "atr": r["atr"], "range_ratio": r["range_ratio"], "atr_ratio": r["atr_ratio"],
                             "vol_ratio": r["vol_ratio"], "close_location": r["close_location"],
                             "avg_value_prev": r["avg_value_prev"]})
    pd.DataFrame(sig_rows).to_csv(os.path.join(args.out, "signals.csv"), index=False)
    diagnostics(summary, ds, data, sig_rows, skipped, p)

    eq.to_csv(os.path.join(args.out, "equity.csv"))
    trades.to_csv(os.path.join(args.out, "trades.csv"), index=False)
    skipped.to_csv(os.path.join(args.out, "skipped_signals.csv"), index=False)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(summary, p))
    plot_equity(eq, os.path.join(args.out, "equity.png"), ds.index_close.get("KOSDAQ"))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
