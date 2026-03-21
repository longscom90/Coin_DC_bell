import requests
import pandas as pd


# =========================
# 📊 전체 종목 가져오기
# =========================
def get_symbols():
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        data = requests.get(url).json()

        return [
            s["symbol"] for s in data["symbols"]
            if s["contractType"] == "PERPETUAL"
            and s["quoteAsset"] == "USDT"
        ]
    except:
        return []


# =========================
# 📊 캔들 데이터 가져오기
# =========================
def get_klines(symbol, interval):
    try:
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": 200
        }

        res = requests.get(url, params=params)

        # 요청 실패
        if res.status_code != 200:
            return None

        data = res.json()

        # 데이터 이상
        if not data or isinstance(data, dict):
            return None

        df = pd.DataFrame(data, columns=[
            "time","open","high","low","close","volume",
            "ct","qv","nt","tbv","tqv","ignore"
        ])

        df["close"] = df["close"].astype(float)
        return df

    except:
        return None


# =========================
# 📈 EMA 계산
# =========================
def ema(df, period):
    try:
        return df["close"].ewm(span=period).mean()
    except:
        return None