from fastapi import FastAPI
import threading
import time

from data import get_klines

app = FastAPI()

signals = []

# ✅ 기본 상태 확인 (Render 405 방지용)
@app.get("/")
def home():
    return {"status": "BFL scanner running"}

# ✅ 현재 시그널 조회
@app.get("/signals")
def get_signals():
    return signals

# ✅ Binance 데이터 테스트 API
@app.get("/test")
def test():
    df = get_klines("BTCUSDT")

    return {
        "symbol": "BTCUSDT",
        "last_price": df["close"].iloc[-1],
        "volume": df["volume"].iloc[-1]
    }

# ✅ (임시) 테스트용 스캐너
def fake_scanner():
    print("🔥 scanner 시작")

    while True:
        try:
            df = get_klines("BTCUSDT")

            signals.clear()
            signals.append({
                "symbol": "BTCUSDT",
                "price": df["close"].iloc[-1],
                "type": "TEST"
            })

            print("✅ signals 업데이트:", signals)

            time.sleep(5)

        except Exception as e:
            print("❌ 에러:", e)
            time.sleep(5)

# ✅ 서버 시작 시 자동 실행
@app.on_event("startup")
def start():
    threading.Thread(target=fake_scanner, daemon=True).start()
