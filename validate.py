"""v2 검증 (규칙 문서 '검증 방법과 합격 기준').

  python validate.py --mode ablation   # 설정 구간(2021.10~2024.10)에서 1~7단계 누적 비교
  python validate.py --mode final      # 검증 구간(2024.10~2026.10)에서 v2 한 번 실행 + 합격 판정
  (--source synthetic 으로 코드 동작만 확인 가능, --limit 으로 종목 수 제한)

final 은 규칙을 확정한 뒤 한 번만 돌린다. 결과를 보고 규칙을 다시 고치면 검증 구간의 의미가 없어진다.
"""
import argparse
import json
import os
from dataclasses import replace

import pandas as pd

from krxbt.config import IN_SAMPLE, OUT_SAMPLE, STAGES, stage_params
from krxbt.pipeline import check_criteria, load_dataset, run_one

COLS = ["거래 수", "승률(%)", "평균 R", "Profit Factor", "전략 누적수익률(TWR)", "CAGR(TWR)", "MDD(TWR)",
        "최대 연속 손실 횟수", "평균 보유 종목 수"]


def periods(source):
    if source == "synthetic":
        return ("2022-03-01", "2023-06-30"), ("2023-07-01", "2024-04-30")
    return IN_SAMPLE, OUT_SAMPLE


def adjust(p, source, start, end):
    p = replace(p, start=start, end=end)
    if source == "synthetic":
        p = replace(p, min_avg_value=min(p.min_avg_value, 1e8), min_marcap=0)
    return p


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["ablation", "final"], required=True)
    ap.add_argument("--source", choices=["fdr", "csv", "synthetic"], default="fdr")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--data-dir", default="krx_csv")
    ap.add_argument("--exclude")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    (is_s, is_e), (os_s, os_e) = periods(args.source)
    ds = load_dataset(args.source, is_s, os_e, 120, args.limit, True, args.cache_dir, args.data_dir, args.exclude)
    report = []

    if args.mode == "ablation":
        rows, prev_r = [], None
        for n, (name, _) in enumerate(STAGES, start=1):
            p = adjust(stage_params(n), args.source, is_s, is_e)
            _, eq, trades, skipped, s = run_one(ds, p)
            row = {"단계": name, **{c: s.get(c) for c in COLS}}
            r = s.get("평균 R")
            row["직전 대비 평균 R"] = None if (r is None or prev_r is None) else round(r - prev_r, 3)
            row["판정"] = "" if n == 1 else ("유지" if (r is not None and prev_r is not None and r >= prev_r) else "빼는 것 검토")
            rows.append(row)
            if r is not None:
                prev_r = r
            trades.to_csv(os.path.join(args.out, f"trades_stage{n}.csv"), index=False)
            print(f"[{n}/{len(STAGES)}] {name}: 거래 {s.get('거래 수')} / 평균R {r} / MDD {s.get('MDD(TWR)')}")
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(args.out, "ablation.csv"), index=False)
        report += [f"# 단계별 비교 (설정 구간 {is_s} ~ {is_e})", "",
                   "앞 단계 변경을 모두 적용한 상태에서 한 단계씩 더한 결과. 평균 R이 나빠진 단계는 빼는 것을 검토한다.", "",
                   md_table(df), "",
                   "> 거래 수가 적은 단계의 차이는 우연일 수 있다. 판정은 참고용이며, 검증 구간(final)은 규칙 확정 후 한 번만 돌린다."]
    else:
        p_is = adjust(stage_params(len(STAGES)), args.source, is_s, is_e)
        p_os = adjust(stage_params(len(STAGES)), args.source, os_s, os_e)
        _, _, _, _, s_is = run_one(ds, p_is)
        _, eq, trades, skipped, s_os = run_one(ds, p_os)
        crit, passed = check_criteria(s_os, s_is)
        comp = pd.DataFrame([{"구간": f"설정 {is_s}~{is_e}", **{c: s_is.get(c) for c in COLS}},
                             {"구간": f"검증 {os_s}~{os_e}", **{c: s_os.get(c) for c in COLS}}])
        comp.to_csv(os.path.join(args.out, "final_compare.csv"), index=False)
        trades.to_csv(os.path.join(args.out, "trades.csv"), index=False)
        eq.to_csv(os.path.join(args.out, "equity.csv"))
        skipped.to_csv(os.path.join(args.out, "skipped_signals.csv"), index=False)
        with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
            json.dump({"설정구간": s_is, "검증구간": s_os, "합격기준": crit, "최종판정": passed}, f,
                      ensure_ascii=False, indent=2, default=str)
        bench = ""
        if "KOSPI 누적수익률(%)" in s_os:
            bench = f"같은 검증 기간 코스피 {s_os['KOSPI 누적수익률(%)']}%, 코스닥 {s_os.get('벤치마크 누적수익률(%)')}%."
        report += [f"# v2 최종 검증 — {'합격' if passed else '불합격'}", "",
                   md_table(comp), "", bench, "", "## 합격 기준", "",
                   md_table(pd.DataFrame([{"기준": c["기준"], "결과": "통과" if c["통과"] else "미달"} for c in crit])), "",
                   "> 불합격이면 실전 투입하지 않는다. 합격해도 처음 3개월은 거래당 위험 0.25%로 시작한다."]

    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
