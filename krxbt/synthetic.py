"""테스트·데모용 합성 일봉 데이터 (실제 시장 데이터 아님)."""
import numpy as np
import pandas as pd


def make_stock(n=600, seed=0, start="2022-01-03", base=10_000, with_pattern=True):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    mu = np.full(n, 0.0003)
    sigma = np.full(n, 0.022)
    vol = rng.lognormal(13.5, 0.4, n)
    shocks = []
    if with_pattern:
        # 수렴 후 돌파 패턴: 상승·큰 변동 → 변동성 축소 → 거래량 동반 돌파
        for k in range(100, n - 40, 120):
            mu[k - 30 : k - 10], sigma[k - 30 : k - 10] = 0.004, 0.03
            mu[k - 10 : k], sigma[k - 10 : k] = 0.001, 0.006
            mu[k + 1 : k + 15], sigma[k + 1 : k + 15] = 0.004, 0.015
            vol[k] *= 3
            shocks.append(k)
    rets = rng.normal(mu, sigma)
    for k in shocks:
        rets[k] = 0.06
    close = base * np.exp(np.cumsum(rets))
    spread = np.abs(rng.normal(0, 1, n)) * sigma * close
    spread[shocks] = 0.03 * close[shocks]
    open_ = close / np.exp(rets) * (1 + rng.normal(0, 0.2, n) * sigma)
    high = np.maximum(open_, close) + spread * 0.5
    low = np.minimum(open_, close) - spread * 0.5
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol.round()}, index=dates
    )


def make_universe(n_stocks=30, n=600, seed=42):
    data = {}
    for i in range(n_stocks):
        code = f"{100000 + i * 10:06d}"
        df = make_stock(n=n, seed=seed + i, base=5_000 + 500 * i)
        if i % 10 == 9:  # 일부는 중간에 데이터가 끊기는 '상장폐지' 종목
            df = df.iloc[: n // 2]
        data[code] = df
    return data


def make_index(n=700, seed=7, start="2021-10-01"):
    """가짜 지수 두 개 (시장 필터 테스트용)."""
    out = {}
    for k, s in (("KOSPI", seed), ("KOSDAQ", seed + 1)):
        rng = np.random.default_rng(s)
        dates = pd.bdate_range(start, periods=n)
        out[k] = pd.Series(2500 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, n))), index=dates)
    return out
