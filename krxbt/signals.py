"""지표·신호 계산.

핵심 수정 사항
- 수렴(가격 범위 축소, ATR 축소)은 돌파 '전날'(t-1)까지의 데이터로만 계산한다.
  돌파일의 큰 양봉이 수렴 지표를 망가뜨려 좋은 신호가 빠지는 문제를 막기 위함.
- 추세(종가>MA20, MA20 상승)와 돌파·거래량 조건은 돌파일(t) 기준.
- 저항선 = 직전 10거래일(t-10 ~ t-1) 고가(기본) 또는 종가의 최고값. 당일 값은 포함하지 않는다.
- 평균 거래량·평균 거래대금도 직전 20거래일(t-20 ~ t-1) 기준.
"""
import numpy as np
import pandas as pd

from .config import Params

REQUIRED = ["Open", "High", "Low", "Close", "Volume"]


def wilder_atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_signals(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """일봉 DataFrame(Open/High/Low/Close/Volume[,Value])에 지표·신호 열을 붙여 돌려준다."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"필수 열 없음: {missing}")

    out = df.copy()
    # 거래정지(거래량 0) 일은 지표 계산에서 제외하지 않고 그대로 두되, 그날 신호·체결은 막는다.
    out["tradeable"] = out["Volume"] > 0

    # 거래대금: 실제 거래대금(Value) 열이 있으면 사용, 없으면 종가×거래량 근사
    if "Value" in out.columns and out["Value"].notna().any():
        value = out["Value"].astype(float)
        out["value_is_approx"] = False
    else:
        value = out["Close"] * out["Volume"]
        out["value_is_approx"] = True

    out["atr"] = wilder_atr(out, p.atr_period)

    # ---- 직전 N일 기준 값들 (shift(1) 로 당일 제외) ----
    out["avg_value_prev"] = value.shift(1).rolling(p.value_window).mean()
    out["avg_vol_prev"] = out["Volume"].shift(1).rolling(p.vol_window).mean()

    basis = out["High"] if p.breakout_basis == "high" else out["Close"]
    out["resistance"] = basis.shift(1).rolling(p.breakout_window).max()

    # ---- 수렴: t-1 기준 ----
    w = p.range_window
    hi_recent = out["High"].shift(1).rolling(w).max()          # t-w .. t-1
    lo_recent = out["Low"].shift(1).rolling(w).min()
    hi_prior = out["High"].shift(1 + w).rolling(w).max()       # t-2w .. t-w-1
    lo_prior = out["Low"].shift(1 + w).rolling(w).min()
    recent_range = hi_recent - lo_recent
    prior_range = hi_prior - lo_prior
    out["range_ratio"] = recent_range / prior_range.replace(0, np.nan)

    atr_fast = out["atr"].rolling(p.atr_fast).mean().shift(1)
    atr_slow = out["atr"].rolling(p.atr_slow).mean().shift(1)
    out["atr_ratio"] = atr_fast / atr_slow.replace(0, np.nan)

    converge = (out["range_ratio"] <= p.range_ratio_max) & (out["atr_ratio"] <= p.atr_ratio_max)

    # ---- 추세: t 기준 ----
    ma = out["Close"].rolling(p.ma_trend).mean()
    out["ma_trend"] = ma
    trend = (out["Close"] > ma) & (ma > ma.shift(p.ma_slope_lag))

    # ---- 돌파: t 기준 ----
    out["vol_ratio"] = out["Volume"] / out["avg_vol_prev"].replace(0, np.nan)
    out["breakout_strength"] = out["Close"] / out["resistance"] - 1
    breakout = (out["Close"] >= out["resistance"] * p.breakout_buffer) & (out["vol_ratio"] >= p.vol_mult)
    liquid = out["avg_value_prev"] >= p.min_avg_value

    out["ma_exit"] = out["Close"].rolling(p.exit_ma).mean()

    out["signal"] = (converge & trend & breakout & liquid & out["tradeable"]).fillna(False).astype(bool)
    return out
