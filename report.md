# 수렴·돌파 전략 백테스트 결과

- **기간**: 2021-10-25 ~ 2026-10-23 (5.0년)
- **총입금액**: 13000000
- **최종평가액**: 9773922
- **순손익(입금 제외)**: -3226077
- **전략 누적수익률(TWR)**: -34.4
- **CAGR(TWR)**: -8.1
- **MDD(TWR)**: -36.88
- **MDD 경고(설정 한도 도달)**: True
- **평균 보유 종목 수**: 1.64
- **주식 보유 비중 평균(%)**: 16.7
- **거래 수**: 388
- **승률(%)**: 28.9
- **평균 R**: -0.221
- **평균 수익 R**: 1.74
- **평균 손실 R**: -1.016
- **손익비(평균수익/평균손실)**: 1.73
- **Profit Factor**: 0.7
- **최대 연속 손실 횟수**: 18
- **평균 보유일(영업일)**: 5.5
- **청산 사유별 건수**
  - stop: 221
  - ma_exit: 159
  - stop_gap: 8
- **-1R보다 큰 손실(갭하락) 건수**: 220
- **연도별 수익률(%)**
  - 2021: 1.57
  - 2022: -20.16
  - 2023: -9.38
  - 2024: 0.45
  - 2025: -10.42
  - 2026: -0.79
- **벤치마크 누적수익률(%)**: -24.4
- **벤치마크 MDD(%)**: -47.42
- **벤치마크 연도별(%)**
  - 2021: 3.99
  - 2022: -34.55
  - 2023: 29.05
  - 2024: -22.84
  - 2025: 34.78
  - 2026: -20.5
- **KOSPI 누적수익률(%)**: 83.75
- **[진단] 데이터 수집 성공 종목**: 2700
- **[진단] 데이터 수집 실패 종목**: 1181
- **[진단] 실패 예시**: [{'code': '950260', 'error': '행 수 부족(45)'}, {'code': '0158S0', 'error': '행 수 부족(4)'}, {'code': '0220W0', 'error': '행 수 부족(40)'}]
- **[진단] 매수 신호 수**: 1257
- **[진단] 진입 안 한 이유**
  - stop_too_wide: 478
  - gap_up: 217
  - max_positions: 104
  - open_below_resistance: 66
  - no_cash_or_too_small: 1
- **[진단] 종목당 일봉 수(최소/중앙/최대)**: 60 / 1302 / 1302
- **[진단] 조건별 충족 일수(종목 합계)**
  - 수렴(범위): 836450
  - 수렴(ATR): 599528
  - 추세: 1244229
  - 돌파가격: 120791
  - 거래량: 423545
  - 거래대금: 1029879

## 사용한 파라미터

```
start = 2021-10-25
end = 2026-10-23
warmup_days = 120
min_avg_value = 2000000000
value_window = 20
range_window = 10
range_ratio_max = 0.7
atr_period = 14
atr_ratio_mode = tr
atr_fast = 5
atr_slow = 20
atr_ratio_max = 0.75
ma_trend = 20
ma_slope_lag = 5
breakout_window = 10
breakout_basis = high
breakout_buffer = 1.005
vol_window = 20
vol_mult = 1.5
max_gap_up = 0.02
require_open_above_resistance = True
stop_atr_mult = 0.5
max_stop_pct = 0.06
take_profit_r = 2.0
take_profit_frac = 0.5
exit_ma = 10
move_stop_to_breakeven = False
initial_cash = 7000000
monthly_deposit = 100000
risk_per_trade = 0.005
max_positions = 8
max_position_frac = 0.25
priority = vol_ratio
mdd_alert = 0.1
commission = 0.00015
sell_tax = 0.002
slippage = 0.002
delisted_exit = last_close
```

> 과거 성과가 미래 수익을 보장하지 않습니다. 거래대금이 근사치이거나 상장폐지 종목이 빠졌다면 결과가 낙관적으로 나올 수 있습니다.