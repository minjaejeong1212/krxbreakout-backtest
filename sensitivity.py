"""민감도 테스트: 핵심 파라미터를 조금씩 바꿔도 성과가 무너지지 않는지 본다.
'가장 좋은 값'을 고르는 게 목적이 아니라, 주변 값에서도 비슷한지(안정성) 확인하는 용도.

  python sensitivity.py --source fdr --limit 500
  python sensitivity.py --source csv --data-dir krx_csv
"""
import argparse
import itertools
import os
from dataclasses import replace

import pandas as pd

from krxbt.backtest import Backtester
from krxbt.config import Params
from krxbt.data import get_universe, load_csv_dir, load_fdr
from krxbt.report import summarize
from krxbt.signals import compute_signals

GRID = {
    "range_ratio_max": [0.6, 0.7, 0.8],
    "atr_ratio_max": [0.65, 0.75, 0.85],
    "vol_mult": [1.3, 1.5, 2.0],
    "take_profit_r": [1.5, 2.0, 3.0],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["fdr", "csv", "synthetic"], default="fdr")
    ap.add_argument("--data-dir", default="krx_csv")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default="results/sensitivity.csv")
    args = ap.parse_args()

    base = Params()
    fetch_start = (pd.Timestamp(base.start) - pd.Timedelta(days=base.warmup_days)).strftime("%Y-%m-%d")
    if args.source == "fdr":
        uni = get_universe()
        if args.limit:
            uni = uni.head(args.limit)
        raw, _ = load_fdr(uni["code"].tolist(), fetch_start, base.end, args.cache_dir)
    elif args.source == "csv":
        raw, _ = load_csv_dir(args.data_dir)
    else:
        from krxbt.synthetic import make_universe
        raw = make_universe()
        base = replace(base, start="2022-03-01", end="2024-05-31", min_avg_value=1e8)

    keys = list(GRID)
    rows = []
    combos = list(itertools.product(*GRID.values()))
    for n, vals in enumerate(combos, 1):
        p = replace(base, **dict(zip(keys, vals)))
        data = {t: compute_signals(df, p) for t, df in raw.items()}
        eq, trades, _ = Backtester(data, p).run()
        s = summarize(eq, trades, p)
        rows.append({**dict(zip(keys, vals)), **{k: s.get(k) for k in
                     ["거래 수", "승률(%)", "평균 R", "CAGR(TWR)", "MDD(TWR)", "Profit Factor", "최대 연속 손실 횟수"]}})
        print(f"[{n}/{len(combos)}] {dict(zip(keys, vals))} → CAGR {s.get('CAGR(TWR)')} MDD {s.get('MDD(TWR)')}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
