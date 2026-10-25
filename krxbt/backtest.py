"""포트폴리오 백테스트 엔진 (일봉, 하루 단위 루프). v1·v2 규칙을 설정으로 전환.

하루 처리 순서
 1) 월 첫 거래일이면 추가 입금
 2) 전날 '10일선 이탈' 표시된 보유 종목 → 오늘 시가 청산
 3) 진입 대기 종목 → 오늘 시가 진입
      (갭 추격 회피·저항선 위 확인·손절폭 확인·하루 신규 매수 한도·계좌 낙폭 단계)
 4) 보유 종목 장중 점검
      - 시가가 이미 손절가 아래(갭 하락) → 시가에 전량 청산 (손실이 1R보다 커질 수 있음)
      - 저가가 손절가 터치 → 손절가에 전량 청산
        (같은 날 +2R 고가도 찍혔더라도 일봉으로는 순서를 알 수 없으므로 '손절 먼저' 가정)
      - 아니면 고가가 +2R 이상 → 절반 익절 (v2: 남은 물량 손절가를 본전으로)
      - 종가 < MA10 → 다음 날 시가 청산 표시
 5) 데이터가 끊기는(상장폐지 등) 보유 종목 강제 청산
 6) 종가로 평가
 7) 신호 처리
      v1: 오늘 신호 → 내일 시가 진입 대기
      v2(confirm_next_day): 오늘 신호 → 내일 종가 확인 대기 → 확인되면 모레 시가 진입 대기
      v2(market_filter): 진입 대기에 올리는 날 지수 추세가 나쁘면 버림
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Params


@dataclass
class Position:
    ticker: str
    entry_date: pd.Timestamp
    entry_px: float          # 슬리피지 반영 체결가
    stop: float
    init_risk_ps: float      # 주당 초기 위험 (진입가 − 손절가)
    init_shares: int
    shares: int
    target: float
    partial_done: bool = False
    exit_next_open: bool = False
    pnl: float = 0.0         # 누적 실현손익 (비용 포함)
    buy_cost: float = 0.0    # 매수 총비용 (수수료 포함)
    last_close: float = 0.0
    events: list = field(default_factory=list)


def index_trend_ok(close: pd.Series, p: Params) -> pd.Series:
    """지수 종가 > 장기 이평, 단기 이평이 N일 전보다 높음."""
    ma_l = close.rolling(p.index_ma_long).mean()
    ma_s = close.rolling(p.index_ma_short).mean()
    return ((close > ma_l) & (ma_s > ma_s.shift(p.index_slope_lag))).fillna(False)


class Backtester:
    def __init__(
        self,
        data: dict[str, pd.DataFrame],
        p: Params,
        ticker_market: dict[str, str] | None = None,
        index_ok: dict[str, pd.Series] | None = None,
    ):
        """data: ticker -> compute_signals() 결과 DataFrame (DatetimeIndex).
        ticker_market: ticker -> "KOSPI" | "KOSDAQ" (시장 필터용)
        index_ok: "KOSPI"/"KOSDAQ" -> 날짜별 True/False (index_trend_ok 결과)"""
        self.p = p
        self.data = data
        self.ticker_market = ticker_market or {}
        self.index_ok = index_ok or {}
        if p.market_filter and not self.index_ok:
            raise ValueError("market_filter=True 인데 지수 데이터(index_ok)가 없습니다")
        start, end = pd.Timestamp(p.start), pd.Timestamp(p.end)
        all_dates = set()
        for df in data.values():
            idx = df.index[(df.index >= start) & (df.index <= end)]
            all_dates.update(idx)
        self.calendar = pd.DatetimeIndex(sorted(all_dates))
        self.last_date = {t: df.index[-1] for t, df in data.items()}
        # 신호 발생일 → 종목 목록 (매일 전 종목을 훑지 않도록 미리 모아둠)
        self.signals_by_date: dict[pd.Timestamp, list[str]] = {}
        for t, df in data.items():
            for d in df.index[df["signal"].values]:
                self.signals_by_date.setdefault(d, []).append(t)

    # ---------- 체결 헬퍼 ----------
    def _sell(self, pos: Position, shares: int, raw_px: float, date, reason: str):
        p = self.p
        px = raw_px * (1 - p.slippage)
        proceeds = shares * px * (1 - p.commission - p.sell_tax)
        cost_basis = pos.buy_cost * shares / pos.init_shares
        pos.pnl += proceeds - cost_basis
        pos.shares -= shares
        self.cash += proceeds
        pos.events.append((date, reason, shares, px))

    def _close_position(self, pos: Position, date, reason: str):
        r_mult = pos.pnl / (pos.init_risk_ps * pos.init_shares) if pos.init_risk_ps > 0 else np.nan
        self.trades.append(
            {
                "ticker": pos.ticker,
                "market": self.ticker_market.get(pos.ticker, ""),
                "entry_date": pos.entry_date,
                "exit_date": date,
                "entry_px": round(pos.entry_px, 2),
                "init_stop": round(pos.entry_px - pos.init_risk_ps, 2),
                "target_2r": round(pos.target, 2),
                "shares": pos.init_shares,
                "position_value": round(pos.entry_px * pos.init_shares),
                "pnl": round(pos.pnl),
                "r_multiple": round(r_mult, 3),
                "partial_taken": pos.partial_done,
                "exit_reason": reason,
                "holding_days": int(np.busday_count(pos.entry_date.date(), pd.Timestamp(date).date())),
            }
        )
        del self.positions[pos.ticker]

    def _equity(self):
        return self.cash + sum(pos.shares * pos.last_close for pos in self.positions.values())

    def _market_ok(self, ticker, d) -> bool:
        if not self.p.market_filter:
            return True
        mkt = self.ticker_market.get(ticker, "")
        mkt = "KOSDAQ" if "KOSDAQ" in mkt else ("KOSPI" if "KOSPI" in mkt else mkt)
        s = self.index_ok.get(mkt)
        if s is None:
            return False
        return bool(s.get(d, False))

    def _stop_for(self, sig, entry_ref: float) -> float:
        """손절가 = 저항선 − k×ATR, 단 손절폭이 최소 비율보다 좁으면 최소 비율로 넓힘."""
        p = self.p
        stop = sig["resistance"] - p.stop_atr_mult * sig["atr"]
        if p.min_stop_pct > 0 and (entry_ref - stop) / entry_ref < p.min_stop_pct:
            stop = entry_ref * (1 - p.min_stop_pct)
        return stop

    # ---------- 메인 루프 ----------
    def run(self):
        p = self.p
        self.cash = float(p.initial_cash)
        self.positions: dict[str, Position] = {}
        self.trades: list[dict] = []
        self.skipped: list[dict] = []
        to_enter: list[dict] = []     # 다음 날 시가 진입 대기
        to_confirm: list[dict] = []   # 다음 날 종가 확인 대기 (v2)
        curve = []
        prev_equity = None
        prev_month = None
        total_deposit = float(p.initial_cash)
        twr_idx, twr_peak = 1.0, 1.0

        for i, d in enumerate(self.calendar):
            # 1) 월 입금 (시작 월은 제외)
            deposit = 0.0
            if prev_month is not None and d.month != prev_month and p.monthly_deposit > 0:
                deposit = p.monthly_deposit
                self.cash += deposit
                total_deposit += deposit
            prev_month = d.month

            # 2) 10일선 이탈 → 시가 청산
            for pos in list(self.positions.values()):
                if not pos.exit_next_open:
                    continue
                bar = self._bar(pos.ticker, d)
                if bar is None:
                    continue  # 거래정지 등: 다음 거래 가능일까지 보류
                self._sell(pos, pos.shares, bar["Open"], d, "ma_exit")
                self._close_position(pos, d, "ma_exit")

            # 3) 신규 진입
            equity_now = self._equity()
            dd = 1 - twr_idx / twr_peak
            risk = p.risk_per_trade
            halt = False
            if p.dd_tiers:
                if dd >= p.dd_halt:
                    halt = True
                elif dd >= p.dd_half:
                    risk = p.risk_per_trade * 0.5
            new_today = 0
            for sig in sorted(to_enter, key=lambda s: s["priority"], reverse=True):
                t = sig["ticker"]
                if t in self.positions:
                    continue
                if halt:
                    self.skipped.append({**sig, "date": d, "reason": "dd_halt"})
                    continue
                if new_today >= p.max_new_per_day:
                    self.skipped.append({**sig, "date": d, "reason": "max_new_per_day"})
                    continue
                if len(self.positions) >= p.max_positions:
                    self.skipped.append({**sig, "date": d, "reason": "max_positions"})
                    continue
                bar = self._bar(t, d)
                if bar is None:
                    self.skipped.append({**sig, "date": d, "reason": "no_bar"})
                    continue
                o = bar["Open"]
                if o > sig["ref_close"] * (1 + p.max_gap_up):
                    self.skipped.append({**sig, "date": d, "reason": "gap_up"})
                    continue
                if p.require_open_above_resistance and o <= sig["resistance"]:
                    self.skipped.append({**sig, "date": d, "reason": "open_below_resistance"})
                    continue
                entry_px = o * (1 + p.slippage)
                stop = self._stop_for(sig, entry_px)
                risk_ps = entry_px - stop
                if risk_ps <= 0 or risk_ps / entry_px > p.max_stop_pct:
                    self.skipped.append({**sig, "date": d, "reason": "stop_too_wide"})
                    continue
                shares = math.floor(equity_now * risk / risk_ps)
                shares = min(shares, math.floor(equity_now * p.max_position_frac / entry_px))
                shares = min(shares, math.floor(self.cash / (entry_px * (1 + p.commission))))
                if shares < 1:
                    self.skipped.append({**sig, "date": d, "reason": "no_cash_or_too_small"})
                    continue
                cost = shares * entry_px * (1 + p.commission)
                self.cash -= cost
                new_today += 1
                self.positions[t] = Position(
                    ticker=t, entry_date=d, entry_px=entry_px, stop=stop, init_risk_ps=risk_ps,
                    init_shares=shares, shares=shares, target=entry_px + p.take_profit_r * risk_ps,
                    buy_cost=cost, last_close=bar["Close"],
                )
            to_enter = []

            # 4) 장중 점검 + 종가 판단
            for pos in list(self.positions.values()):
                bar = self._bar(pos.ticker, d)
                if bar is None:
                    continue
                o, h, l, c = bar["Open"], bar["High"], bar["Low"], bar["Close"]
                if o <= pos.stop and pos.entry_date != d:
                    self._sell(pos, pos.shares, o, d, "stop_gap")
                    self._close_position(pos, d, "stop_gap")
                    continue
                if l <= pos.stop:
                    reason = "breakeven_stop" if pos.partial_done and p.move_stop_to_breakeven else "stop"
                    self._sell(pos, pos.shares, pos.stop, d, reason)
                    self._close_position(pos, d, reason)
                    continue
                if not pos.partial_done and h >= pos.target:
                    n = math.floor(pos.init_shares * p.take_profit_frac)
                    fill = max(o, pos.target) if pos.entry_date != d else pos.target
                    if n >= 1:
                        self._sell(pos, n, fill, d, "take_profit_2r")
                    pos.partial_done = True
                    if p.move_stop_to_breakeven:
                        pos.stop = pos.entry_px
                    if pos.shares == 0:
                        self._close_position(pos, d, "take_profit_2r")
                        continue
                pos.last_close = c
                ma = bar["ma_exit"]
                if not np.isnan(ma) and c < ma:
                    pos.exit_next_open = True

            # 5) 데이터 끊김(상장폐지 등) 강제 청산
            for pos in list(self.positions.values()):
                if self.last_date[pos.ticker] == d and d < self.calendar[-1]:
                    px = pos.last_close if p.delisted_exit == "last_close" else 0.0
                    self._sell(pos, pos.shares, px, d, "data_end")
                    self._close_position(pos, d, "data_end")

            # 6) 평가
            equity = self._equity()
            if prev_equity is None:
                twr_ret = equity / p.initial_cash - 1
            else:
                twr_ret = (equity - deposit) / prev_equity - 1
            prev_equity = equity
            twr_idx *= 1 + twr_ret
            twr_peak = max(twr_peak, twr_idx)
            curve.append(
                {
                    "date": d, "equity": equity, "cash": self.cash, "deposit": deposit,
                    "total_deposit": total_deposit, "n_positions": len(self.positions),
                    "twr_ret": twr_ret,
                }
            )

            if i >= len(self.calendar) - 1:
                continue  # 마지막 날 신호는 버림

            # 7a) 어제 신호의 오늘 종가 확인 (v2)
            for sig in to_confirm:
                t = sig["ticker"]
                bar = self._bar(t, d)
                if bar is None or t in self.positions:
                    continue
                stop_cand = sig["resistance"] - p.stop_atr_mult * sig["atr"]
                if bar["Close"] < sig["resistance"]:
                    self.skipped.append({**sig, "date": d, "reason": "confirm_close_below"})
                    continue
                if bar["Low"] <= stop_cand:
                    self.skipped.append({**sig, "date": d, "reason": "confirm_hit_stop"})
                    continue
                if not self._market_ok(t, d):
                    self.skipped.append({**sig, "date": d, "reason": "market_filter"})
                    continue
                to_enter.append({**sig, "ref_close": bar["Close"], "confirm_date": d})
            to_confirm = []

            # 7b) 오늘 신호
            for t in self.signals_by_date.get(d, []):
                bar = self._bar(t, d)
                if bar is None or not bar["signal"] or t in self.positions:
                    continue
                sig = {
                    "ticker": t, "signal_date": d, "ref_close": bar["Close"],
                    "resistance": bar["resistance"], "atr": bar["atr"],
                    "vol_ratio": bar["vol_ratio"], "avg_value_prev": bar["avg_value_prev"],
                    "priority": self._priority(bar),
                }
                if p.confirm_next_day:
                    to_confirm.append(sig)
                elif self._market_ok(t, d):
                    to_enter.append(sig)
                else:
                    self.skipped.append({**sig, "date": d, "reason": "market_filter"})

        # 종료 시 미청산 포지션은 마지막 종가로 정리하고 end_of_test 로 표시 (통계에서 제외)
        last = self.calendar[-1] if len(self.calendar) else None
        for pos in list(self.positions.values()):
            self._sell(pos, pos.shares, pos.last_close, last, "end_of_test")
            self._close_position(pos, last, "end_of_test")

        eq = pd.DataFrame(curve).set_index("date") if curve else pd.DataFrame()
        if not eq.empty:
            eq["twr_index"] = (1 + eq["twr_ret"]).cumprod()
        return eq, pd.DataFrame(self.trades), pd.DataFrame(self.skipped)

    # ---------- 유틸 ----------
    def _bar(self, ticker, d):
        df = self.data[ticker]
        if d not in df.index:
            return None
        row = df.loc[d]
        if not row["tradeable"]:
            return None
        return row

    def _priority(self, bar):
        key = self.p.priority
        if key == "value":
            return float(bar["avg_value_prev"])
        if key == "breakout_strength":
            return float(bar["breakout_strength"])
        return float(bar["vol_ratio"])
