from fastapi import FastAPI
import threading
import time

print("🔥 test_main 로드됨")  # 👉 여기 위치 (파일 맨 위)

app = FastAPI()

signals = []

@app.get("/signals")
def get_signals():
    return signals


def fake_scanner():
    print("🔥 scanner 시작됨")

    while True:
        signals.clear()
        signals.append({"symbol": "BTCUSDT", "type": "LONG"})
        signals.append({"symbol": "ETHUSDT", "type": "LONG"})
        print("🚀 신호 넣음")
        time.sleep(2)


@app.on_event("startup")
def start():
    print("🔥 startup 실행됨")
    threading.Thread(target=fake_scanner, daemon=True).start()