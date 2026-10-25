"""v2 규칙 단위 테스트."""
import numpy as np
import pandas as pd
import pytest

from krxbt.backtest import Backtester
from krxbt.config import Params, stage_params
from krxbt.signals import compute_signals
from tests.test_engine import frame, params

# frame 기본값: 저항선 100, ATR 4, 신호일 0


def v2(**kw):
    return params(**kw)


def test_confirm_next_day_enters_on_t_plus_2():
    # t0 신호, t1 종가 101 ≥ 저항선 100 이고 저가 99 > 손절후보 98 → t2 시가 진입
    df = frame([(100, 102, 99, 102), (101, 102, 99, 101), (101.5, 103, 101, 102), (102, 103, 101, 102)])
    _, trades, _ = Backtester({"000010": df}, v2(confirm_next_day=True)).run()
    assert trades.iloc[0]["entry_date"] == df.index[2]


def test_confirm_fails_when_close_back_below_resistance():
    df = frame([(100, 102, 99, 102), (101, 101.5, 99, 99.5), (100, 101, 99, 100), (100, 101, 99, 100)])
    _, trades, skipped = Backtester({"000010": df}, v2(confirm_next_day=True)).run()
    assert trades.empty
    assert "confirm_close_below" in set(skipped["reason"])


def test_confirm_fails_when_low_hits_stop():
    df = frame([(100, 102, 99, 102), (101, 103, 97.5, 101), (101, 102, 100.5, 101), (101, 102, 100.5, 101)])
    _, trades, skipped = Backtester({"000010": df}, v2(confirm_next_day=True)).run()
    assert trades.empty
    assert "confirm_hit_stop" in set(skipped["reason"])


def test_min_stop_widens_narrow_stop():
    # ATR 0.4 → 손절 99.8, 진입 102 → 2.2% 폭 → 최소 2.5% 로 넓혀 99.45
    df = frame([(100, 102, 99.9, 102), (102, 102.5, 101, 102), (102, 103, 101, 102)], atr=0.4)
    _, trades, _ = Backtester({"000010": df}, v2(min_stop_pct=0.025)).run()
    assert trades.iloc[0]["init_stop"] == pytest.approx(102 * 0.975, abs=0.01)


def test_breakeven_after_partial():
    # 진입 102, 1R 4 → +2R 110 에서 절반 익절, 이후 저가 101.5 → 본전(102) 손절
    bars = [(100, 102, 99, 102), (102, 104, 101, 103), (104, 111, 103, 110), (108, 109, 101.5, 105), (105, 106, 104, 105)]
    _, trades, _ = Backtester({"000010": frame(bars)}, v2(move_stop_to_breakeven=True)).run()
    t = trades.iloc[0]
    assert t["exit_reason"] == "breakeven_stop"
    assert t["r_multiple"] == pytest.approx(1.0, abs=0.01)  # 절반 +2R, 절반 0R


def test_max_new_per_day():
    dfs = {f"{i:06d}": frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (102, 103, 101, 102)]) for i in range(5)}
    _, trades, skipped = Backtester(dfs, v2(max_new_per_day=2)).run()
    assert len(trades) == 2
    assert (skipped["reason"] == "max_new_per_day").sum() == 3


def test_market_filter_blocks_entry():
    df = frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (102, 103, 101, 102)])
    ok = pd.Series(False, index=df.index)
    _, trades, skipped = Backtester({"000010": df}, v2(market_filter=True), {"000010": "KOSDAQ"}, {"KOSDAQ": ok}).run()
    assert trades.empty and skipped.iloc[0]["reason"] == "market_filter"
    ok[:] = True
    _, trades, _ = Backtester({"000010": df}, v2(market_filter=True), {"000010": "KOSDAQ"}, {"KOSDAQ": ok}).run()
    assert len(trades) == 1


def test_dd_halt_stops_new_entries():
    # 첫 거래 큰 손실(갭 하락) 후 낙폭 8% 이상이면 다음 신호는 진입 안 함
    dates = pd.bdate_range("2023-01-02", periods=8)
    a = frame([(100, 102, 99, 102), (102, 103, 101, 102.5), (60, 61, 59, 60), (60, 61, 59, 60),
               (60, 61, 59, 60), (60, 61, 59, 60), (60, 61, 59, 60), (60, 61, 59, 60)])
    b = frame([(100, 101, 99, 100)] * 4 + [(100, 102, 99, 102), (102, 103, 101, 102.5), (102, 103, 101, 102), (102, 103, 101, 102)], signal_day=4)
    p = v2(dd_tiers=True, max_position_frac=1.0, risk_per_trade=0.05)
    _, trades, skipped = Backtester({"000010": a, "000020": b}, p).run()
    assert "dd_halt" in set(skipped["reason"])


def test_candle_quality_filter():
    p = stage_params(4, Params(min_avg_value=1e6))
    n = 80
    dates = pd.bdate_range("2023-01-02", periods=n)
    close = np.linspace(100, 130, n)
    w = np.r_[np.full(n - 11, 6.0), np.full(10, 1.0), [0.0]]
    df = pd.DataFrame({"Close": close}, index=dates)
    df["Open"], df["High"], df["Low"], df["Volume"] = df["Close"] - 0.2, df["Close"] + w / 2, df["Close"] - w / 2, 1e6
    # 마지막 날: 돌파했지만 윗꼬리가 긴 캔들 (종가가 범위 아래쪽)
    df.iloc[-1, df.columns.get_loc("Close")] = close[-2] * 1.03
    df.iloc[-1, df.columns.get_loc("High")] = close[-2] * 1.09
    df.iloc[-1, df.columns.get_loc("Low")] = close[-2] * 0.99
    df.iloc[-1, df.columns.get_loc("Volume")] = 3e6
    out = compute_signals(df, p)
    assert out.iloc[-1]["close_location"] < 0.7
    assert not bool(out.iloc[-1]["signal"])
