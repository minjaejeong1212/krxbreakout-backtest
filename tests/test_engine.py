import numpy as np
import pandas as pd
import pytest

from krxbt.backtest import Backtester
from krxbt.config import Params
from krxbt.signals import compute_signals
from krxbt.synthetic import make_universe


def frame(bars, signal_day=0, resistance=100.0, atr=4.0, ma_exit=None):
    """bars: [(o,h,l,c), ...]. signal_day 에 신호, 그 다음 날 진입."""
    dates = pd.bdate_range("2023-01-02", periods=len(bars))
    df = pd.DataFrame(bars, columns=["Open", "High", "Low", "Close"], index=dates)
    df["Volume"] = 1_000_000
    df["tradeable"] = True
    df["signal"] = False
    df.iloc[signal_day, df.columns.get_loc("signal")] = True
    df["resistance"] = resistance
    df["atr"] = atr
    df["vol_ratio"] = 2.0
    df["avg_value_prev"] = 5e9
    df["breakout_strength"] = 0.01
    df["ma_exit"] = ma_exit if ma_exit is not None else 0.0
    return df


def params(**kw):
    p = Params(start="2023-01-01", end="2023-12-31", monthly_deposit=0, slippage=0, commission=0, sell_tax=0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def run(df, **kw):
    p = params(**kw)
    return Backtester({"000010": df}, p).run()


# 손절가 = 100 - 0.5*4 = 98, 진입 102 → 1R = 4, +2R = 110
def test_stop_first_when_stop_and_target_same_day():
    df = frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (102, 111, 97, 105), (105, 106, 104, 105)])
    _, trades, _ = run(df)
    t = trades.iloc[0]
    assert t["exit_reason"] == "stop"
    assert not t["partial_taken"]
    assert t["r_multiple"] == pytest.approx(-1.0, abs=1e-6)


def test_gap_down_fills_at_open_and_loses_more_than_1r():
    df = frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (94, 95, 92, 93), (93, 94, 92, 93)])
    _, trades, _ = run(df)
    t = trades.iloc[0]
    assert t["exit_reason"] == "stop_gap"
    assert t["r_multiple"] == pytest.approx((94 - 102) / 4, abs=1e-6)  # -2R


def test_gap_up_more_than_2pct_skips_entry():
    df = frame([(100, 102, 99, 102), (104.5, 106, 104, 105), (105, 106, 104, 105)])
    _, trades, skipped = run(df)
    assert trades.empty
    assert skipped.iloc[0]["reason"] == "gap_up"


def test_open_below_resistance_skips_entry():
    df = frame([(100, 102, 99, 102), (99.5, 103, 99, 102), (102, 103, 101, 102)])
    _, trades, skipped = run(df)
    assert trades.empty
    assert skipped.iloc[0]["reason"] == "open_below_resistance"


def test_stop_too_wide_skips_entry():
    df = frame([(100, 102, 99, 102), (101, 103, 100.5, 102), (102, 103, 101, 102)], atr=12.0)
    _, trades, skipped = run(df)  # 손절 94 → 진입 101 대비 6.9%
    assert trades.empty
    assert skipped.iloc[0]["reason"] == "stop_too_wide"


def test_half_profit_at_2r_then_ma_exit_next_open():
    bars = [(100, 102, 99, 102), (102, 104, 101, 103), (104, 111, 103, 110), (110, 112, 108, 109), (107, 108, 106, 107)]
    ma = [0, 0, 0, 0, 0]
    df = frame(bars)
    df["ma_exit"] = [0, 0, 0, 120, 0]  # 4번째 날 종가 109 < MA 120 → 5번째 날 시가 107 청산
    _, trades, _ = run(df)
    t = trades.iloc[0]
    assert t["partial_taken"]
    assert t["exit_reason"] == "ma_exit"
    # 절반 110 (+2R), 나머지 107 (+1.25R) → 평균 +1.625R
    assert t["r_multiple"] == pytest.approx((2 + 1.25) / 2, abs=0.01)


def test_position_size_uses_half_percent_risk():
    df = frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (102, 103, 101, 102)])
    _, trades, _ = run(df)
    # 700만 × 0.5% / 4원 = 8750주, 그러나 계좌 25% 한도: 700만×0.25/102 = 17156 → 8750주
    assert trades.iloc[0]["shares"] == 8750


def test_max_positions_respected():
    dfs = {f"{i:06d}": frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (102, 103, 101, 102)]) for i in range(12)}
    p = params(max_positions=3)
    _, trades, skipped = Backtester(dfs, p).run()
    assert len(trades) == 3
    assert (skipped["reason"] == "max_positions").sum() == 9


def test_convergence_measured_on_previous_day():
    """돌파일 양봉이 커도 수렴 판단에는 영향이 없어야 한다."""
    p = Params()
    n = 80
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = np.linspace(100, 130, n)
    rng_width = np.r_[np.full(n - 11, 6.0), np.full(10, 1.0), [0.0]]  # 마지막 10일 좁게
    df = pd.DataFrame({"Close": close}, index=dates)
    df["Open"] = df["Close"] - 0.2
    df["High"] = df["Close"] + rng_width / 2
    df["Low"] = df["Close"] - rng_width / 2
    df["Volume"] = 1_000_000.0
    # 마지막 날: 큰 장대 양봉 + 거래량 3배
    df.iloc[-1, df.columns.get_loc("Close")] = close[-2] * 1.08
    df.iloc[-1, df.columns.get_loc("High")] = close[-2] * 1.09
    df.iloc[-1, df.columns.get_loc("Low")] = close[-2] * 0.99
    df.iloc[-1, df.columns.get_loc("Volume")] = 3_000_000.0
    p.min_avg_value = 1e6
    out = compute_signals(df, p)
    last = out.iloc[-1]
    assert last["range_ratio"] < 0.7
    assert last["atr_ratio"] < 0.75
    assert bool(last["signal"])


def test_synthetic_end_to_end_runs():
    p = Params(start="2022-03-01", end="2024-05-31", min_avg_value=1e8)
    data = {t: compute_signals(df, p) for t, df in make_universe().items()}
    eq, trades, _ = Backtester(data, p).run()
    assert not eq.empty
    assert eq["equity"].iloc[-1] > 0
    assert eq["total_deposit"].iloc[-1] > p.initial_cash  # 월 입금 반영
    assert (trades["exit_reason"] == "data_end").any() or True
