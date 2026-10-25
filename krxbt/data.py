"""데이터 수집·캐시.

소스
- fdr : FinanceDataReader 로 KOSPI/KOSDAQ 현재 상장 + 상장폐지 목록을 받아 일봉 다운로드 (캐시 저장)
- csv : 직접 받은 KRX 일봉 CSV 폴더 사용 (파일명 = 종목코드.csv,
        열: Date, Open, High, Low, Close, Volume[, Value(실제 거래대금)])

필터
- 보통주만 (종목코드 끝자리 0), 스팩·ETF·ETN·리츠 이름 제외
- 관리종목·투자위험 지정 '이력'은 무료 소스로 얻기 어려우므로, 직접 만든 제외 목록 CSV
  (열: code, start, end) 를 --exclude 로 넘기면 해당 기간을 거래 불가로 처리한다.
  현재 상태로 과거를 거르면 미래 정보를 쓰게 되므로 일부러 그렇게 하지 않는다.
"""
from __future__ import annotations

import os
import time

import pandas as pd

EXCLUDE_NAME_KEYWORDS = ["스팩", "ETF", "ETN", "리츠", "REIT", "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO"]


def _is_common_stock(code: str, name: str) -> bool:
    if not isinstance(code, str) or len(code) != 6:
        return False
    if not code.endswith("0"):        # 우선주(5,7,9,K 등) 제외
        return False
    name = str(name)
    return not any(k in name for k in EXCLUDE_NAME_KEYWORDS)


def get_universe(include_delisted: bool = True) -> pd.DataFrame:
    import FinanceDataReader as fdr

    listed = fdr.StockListing("KRX")
    code_col = "Code" if "Code" in listed.columns else "Symbol"
    listed = listed.rename(columns={code_col: "code", "Name": "name", "Market": "market"})
    listed = listed[listed["market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])]
    # 상장주식수 (시가총액 근사용). 열 이름이 버전마다 달라서 있는 것을 사용
    shares_col = next((c for c in ["Stocks", "ListedShares", "Shares"] if c in listed.columns), None)
    listed["shares"] = pd.to_numeric(listed[shares_col], errors="coerce") if shares_col else float("nan")
    listed = listed[["code", "name", "market", "shares"]].assign(delisted=False)

    frames = [listed]
    if include_delisted:
        try:
            dl = fdr.StockListing("KRX-DELISTING")
            dl = dl.rename(columns={"Symbol": "code", "Name": "name", "Market": "market"})
            if "SecuGroup" in dl.columns:
                dl = dl[dl["SecuGroup"].astype(str).str.contains("주권")]
            dl = dl[dl["market"].astype(str).str.contains("KOSPI|KOSDAQ|유가|코스닥")]
            frames.append(dl[["code", "name", "market"]].assign(delisted=True, shares=float("nan")))
        except Exception as e:  # noqa: BLE001
            print(f"[경고] 상장폐지 목록 수집 실패 → 생존편향 있음: {e}")

    uni = pd.concat(frames, ignore_index=True).drop_duplicates("code")
    uni = uni[[_is_common_stock(c, n) for c, n in zip(uni["code"], uni["name"])]]
    return uni.reset_index(drop=True)


def load_fdr(codes, start: str, end: str, cache_dir: str = "cache", sleep: float = 0.05):
    import FinanceDataReader as fdr

    os.makedirs(cache_dir, exist_ok=True)
    data, failed = {}, []
    try:
        from tqdm import tqdm
        it = tqdm(codes, desc="일봉 수집")
    except ImportError:
        it = codes
    for code in it:
        path = os.path.join(cache_dir, f"{code}.csv")
        try:
            if os.path.exists(path):
                df = pd.read_csv(path, index_col=0, parse_dates=True)
            else:
                df = fdr.DataReader(code, start, end)
                time.sleep(sleep)
                if df is None or df.empty:
                    raise ValueError("빈 데이터")
                df.to_csv(path)
            df = _clean(df)
            if len(df) < 60:
                raise ValueError(f"행 수 부족({len(df)})")
            data[code] = df
        except Exception as e:  # noqa: BLE001
            failed.append({"code": code, "error": str(e)[:200]})
    return data, pd.DataFrame(failed)


def load_csv_dir(folder: str):
    data, failed = {}, []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".csv"):
            continue
        code = fn[:-4]
        try:
            df = pd.read_csv(os.path.join(folder, fn))
            date_col = next(c for c in df.columns if c.lower() in ("date", "날짜", "일자"))
            df[date_col] = pd.to_datetime(df[date_col])
            df = _clean(df.set_index(date_col))
            data[code] = df
        except Exception as e:  # noqa: BLE001
            failed.append({"code": code, "error": str(e)[:200]})
    return data, pd.DataFrame(failed)


KOR_COLS = {"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close", "거래량": "Volume", "거래대금": "Value"}


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=KOR_COLS)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume", "Value"] if c in df.columns]
    df = df[keep].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    # 시가 0 (거래정지일 표기) → 거래량 0 으로 맞춰 거래 불가 처리
    halted = df["Open"] <= 0
    df.loc[halted, "Volume"] = 0
    df.loc[halted, ["Open", "High", "Low"]] = df.loc[halted, "Close"]
    return df


def apply_exclusions(data: dict, exclude_csv: str | None):
    """관리종목·투자위험 등 기간을 거래 불가(Volume=0)로 표시."""
    if not exclude_csv:
        return data
    ex = pd.read_csv(exclude_csv, dtype={"code": str})
    for _, r in ex.iterrows():
        code = r["code"].zfill(6)
        if code not in data:
            continue
        df = data[code]
        mask = (df.index >= pd.Timestamp(r["start"])) & (df.index <= pd.Timestamp(r["end"]))
        df.loc[mask, "Volume"] = 0
    return data


def coverage_table(data: dict) -> pd.DataFrame:
    rows = []
    for code, df in data.items():
        rows.append(
            {
                "code": code,
                "first_date": df.index[0].date(),
                "last_date": df.index[-1].date(),
                "rows": len(df),
                "signals": int(df["signal"].sum()) if "signal" in df.columns else None,
                "value_is_approx": bool(df["value_is_approx"].iloc[0]) if "value_is_approx" in df.columns else None,
            }
        )
    return pd.DataFrame(rows)


def attach_shares(data: dict, universe: pd.DataFrame) -> dict:
    """현재 상장주식수를 일봉에 붙인다 (시가총액 = 종가 × 주식수 근사).
    증자·감자·분할 이력은 반영되지 않는 근사치이고, 주식수를 모르는 종목은 시총 조건을 통과시킨다."""
    if "shares" not in universe.columns:
        return data
    m = universe.set_index("code")["shares"].to_dict()
    for code, df in data.items():
        sh = m.get(code)
        if sh is not None and sh == sh and sh > 0:
            df["Shares"] = float(sh)
    return data


def load_index_ok(start: str, end: str, p) -> tuple[dict, dict]:
    """KOSPI·KOSDAQ 지수 종가와 추세 통과 여부."""
    import FinanceDataReader as fdr
    from .backtest import index_trend_ok

    closes = {"KOSPI": fdr.DataReader("KS11", start, end)["Close"], "KOSDAQ": fdr.DataReader("KQ11", start, end)["Close"]}
    return closes, {k: index_trend_ok(v, p) for k, v in closes.items()}
