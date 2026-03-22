import requests
import pandas as pd

BASE_URL = "https://fapi.binance.com"

def get_all_symbols():
    url = f"{BASE_URL}/fapi/v1/exchangeInfo"
    data = requests.get(url).json()

    symbols = []

    for s in data["symbols"]:
        if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT":
            symbols.append(s["symbol"])

    return symbols


def get_klines(symbol="BTCUSDT", interval="5m", limit=100):
    url = f"{BASE_URL}/fapi/v1/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    response = requests.get(url, params=params)
    data = response.json()

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "taker_base_vol",
        "taker_quote_vol", "ignore"
    ])

    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)

    return df
