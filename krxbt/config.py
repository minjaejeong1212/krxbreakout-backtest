"""전략·계좌·비용 파라미터. 숫자를 바꿔서 민감도 테스트를 할 때 이 파일만 고치면 된다."""
from dataclasses import dataclass, field, asdict


@dataclass
class Params:
    # ---------- 기간 ----------
    start: str = "2021-10-25"          # 백테스트 시작일 (지표 계산용 데이터는 이보다 앞에서 더 받음)
    end: str = "2026-10-23"            # 백테스트 종료일
    warmup_days: int = 120             # 지표 워밍업용으로 start 이전에 더 받을 달력일 수

    # ---------- 종목 필터 ----------
    min_avg_value: float = 2_000_000_000   # 직전 20거래일 평균 거래대금 하한 (20억)
    value_window: int = 20
    min_marcap: float = 0                  # 시가총액 하한 (v2: 2,000억). 종가×현재 상장주식수로 근사
    market_filter: bool = False            # v2: 지수 > 60일선, 지수 20일선 상승일 때만 신규 매수
    index_ma_long: int = 60
    index_ma_short: int = 20
    index_slope_lag: int = 5

    # ---------- 수렴 조건 (돌파 '전날' t-1 기준으로 계산) ----------
    range_window: int = 10             # 최근 10일 vs 그 직전 10일
    range_ratio_max: float = 0.70      # 최근 범위 / 직전 범위 ≤ 0.70
    atr_period: int = 14               # 손절가 계산용 ATR(14)
    atr_ratio_mode: str = "tr"         # "tr": 하루 변동폭(TR) 5일 평균 ÷ 20일 평균 (기본)
                                       # "smoothed": ATR(14)의 5일 평균 ÷ 20일 평균 (원문, 5년 200종목에서 신호 2건뿐)
    atr_fast: int = 5
    atr_slow: int = 20
    atr_ratio_max: float = 0.75
    ma_trend: int = 20                 # 종가 > MA20, MA20 > 5일 전 MA20 (돌파일 t 기준)
    ma_slope_lag: int = 5

    # ---------- 돌파 조건 (돌파일 t 기준) ----------
    breakout_window: int = 10          # 직전 10거래일 고가(high) 또는 종가(close)의 최고값
    breakout_basis: str = "high"       # "high" | "close"
    breakout_buffer: float = 1.005     # 종가 ≥ 저항선 × 1.005
    vol_window: int = 20
    vol_mult: float = 1.5              # 거래량 ≥ 직전 20일 평균 × 1.5
    min_close_location: float = 0.0    # v2 0.7: 종가가 당일 고저 범위 위쪽 30% 안
    max_day_return: float = 9.99       # v2 0.15: 당일 상승률 15% 초과 제외

    # ---------- 진입 (t+1 시가) ----------
    confirm_next_day: bool = False     # v2: 신호 다음 날 종가가 저항선 위 + 손절가 미터치 → 그다음 날 시가 진입
    max_gap_up: float = 0.02           # 시가 > 기준 종가(신호일 또는 확인일) × 1.02 이면 추격 안 함
    require_open_above_resistance: bool = True
    stop_atr_mult: float = 0.5         # 손절가 = 저항선 − 0.5 × ATR(14)
    max_stop_pct: float = 0.06         # (진입가−손절가)/진입가 > 6% 이면 진입 안 함 (v2: 8%)
    min_stop_pct: float = 0.0          # v2 0.025: 손절폭이 2.5%보다 좁으면 2.5%로 넓힘

    # ---------- 청산 ----------
    take_profit_r: float = 2.0         # +2R 에서 절반 익절
    take_profit_frac: float = 0.5
    exit_ma: int = 10                  # 종가 < MA10 → 다음 날 시가 청산
    move_stop_to_breakeven: bool = False  # 절반 익절 후 손절가를 진입가로 올릴지 (원문 규칙엔 없음 → 기본 끔)

    # ---------- 계좌·포지션 ----------
    initial_cash: float = 7_000_000
    monthly_deposit: float = 100_000   # 매월 첫 거래일 입금
    risk_per_trade: float = 0.005      # 계좌의 0.5%
    max_positions: int = 8             # v2: 6
    max_new_per_day: int = 99          # v2: 2
    max_position_frac: float = 0.25    # 한 종목에 계좌 25% 초과 금지 (손절폭이 아주 좁을 때 몰빵 방지)
    priority: str = "vol_ratio"        # 같은 날 신호 여러 개면 우선순위: vol_ratio | value | breakout_strength
    mdd_alert: float = 0.10            # 최대낙폭 10% 도달 시 리포트에 경고
    dd_tiers: bool = False             # v2: 고점 대비 5% 이상 → 위험 절반, 8% 이상 → 신규 매수 중단
    dd_half: float = 0.05
    dd_halt: float = 0.08

    # ---------- 비용 ----------
    commission: float = 0.00015        # 매수·매도 각각 0.015% (온라인 수수료 가정)
    sell_tax: float = 0.0020           # 매도 시 증권거래세(+농특세) 가정 0.20% — 시기·시장별로 다르니 확인 후 조정
    slippage: float = 0.0020           # 매수·매도 각각 체결가 불리하게 0.2%

    # ---------- 기타 ----------
    delisted_exit: str = "last_close"  # 데이터가 끊긴 보유 종목 처리: last_close | zero (보수적: 전액 손실)

    def to_dict(self):
        return asdict(self)


# ---------------- 프리셋 · 단계 ----------------
IN_SAMPLE = ("2021-10-25", "2024-10-25")
OUT_SAMPLE = ("2024-10-28", "2026-10-23")

# 문서 '검증 방법' 의 단계별 변경 (누적 적용)
STAGES = [
    ("1. v1 그대로 (기준선)", {}),
    ("2. + 시장 필터", {"market_filter": True}),
    ("3. + 종목 필터 (시총 2,000억·거래대금 50억)", {"min_marcap": 2e11, "min_avg_value": 5e9}),
    ("4. + 돌파 캔들 품질·과열 제외", {"min_close_location": 0.7, "max_day_return": 0.15}),
    ("5. + 다음 날 확인 후 진입", {"confirm_next_day": True}),
    ("6. + 손절 1ATR·최소 2.5%·최대 8%·본전 이동",
     {"stop_atr_mult": 1.0, "min_stop_pct": 0.025, "max_stop_pct": 0.08, "move_stop_to_breakeven": True}),
    ("7. + 하루 2종목·최대 6종목·낙폭 단계 관리", {"max_new_per_day": 2, "max_positions": 6, "dd_tiers": True}),
]


def stage_params(n: int, base: "Params | None" = None, skip: tuple = ()) -> "Params":
    """1..n 단계 변경을 누적 적용한 Params. skip 에 단계 번호를 넣으면 그 단계는 빼고 적용."""
    from dataclasses import replace
    p = base or Params()
    for i, (_, changes) in enumerate(STAGES[:n], start=1):
        if i in skip:
            continue
        p = replace(p, **changes)
    return p


def preset(name: str) -> "Params":
    if name == "v1":
        return Params()
    if name == "v2":
        return stage_params(len(STAGES))
    raise ValueError(name)
