from data import get_klines, ema

def is_ema_aligned(df):
    if df is None or len(df) < 200:
        return False

    e14 = ema(df, 14)
    e21 = ema(df, 21)
    e35 = ema(df, 35)
    e50 = ema(df, 50)
    e100 = ema(df, 100)
    e200 = ema(df, 200)

    return (
        e14.iloc[-1] > e21.iloc[-1] >
        e35.iloc[-1] > e50.iloc[-1] >
        e100.iloc[-1] > e200.iloc[-1]
    )


def is_price_above(df):
    e14 = ema(df, 14)
    return df["close"].iloc[-1] > e14.iloc[-1]


def is_uptrend(df):
    return df["close"].iloc[-1] > df["close"].iloc[-2]


def check_long_signal(symbol):
    try:
        df_15m = get_klines(symbol, "15m")
        df_4h = get_klines(symbol, "4h")

        if df_15m is None or df_4h is None:
            return False

        return (
            is_ema_aligned(df_15m) and
            is_price_above(df_15m) and
            is_uptrend(df_15m) and
            is_ema_aligned(df_4h) and
            is_price_above(df_4h)
        )

    except:
        return False
