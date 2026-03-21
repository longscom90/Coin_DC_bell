from data import get_klines, ema

# =========================
# 📈 EMA 정배열 체크
# =========================
def is_aligned(df):
    try:
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
    except:
        return False


# =========================
# 📈 가격이 이평선 위
# =========================
def is_above(df):
    try:
        if df is None or len(df) < 200:
            return False

        e14 = ema(df, 14)
        return df["close"].iloc[-1] > e14.iloc[-1]
    except:
        return False


# =========================
# 📈 상승 중인지 확인
# =========================
def is_up(df):
    try:
        if df is None or len(df) < 2:
            return False

        return df["close"].iloc[-1] > df["close"].iloc[-2]
    except:
        return False


# =========================
# 🚀 최종 시그널 조건
# =========================
def check_signal(symbol):
    try:
        df4 = get_klines(symbol, "4h")
        df15 = get_klines(symbol, "15m")

        if df4 is None or df15 is None:
            return False

        return (
            is_aligned(df4) and is_above(df4) and
            is_aligned(df15) and is_above(df15) and
            is_up(df15)
        )

    except:
        return False