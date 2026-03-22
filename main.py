from fastapi import FastAPI
import threading

from scanner import run_scanner

app = FastAPI()

signals = []

# ✅ 서버 상태 확인
@app.get("/")
def home():
    return {"status": "BFL scanner running"}

# ✅ 시그널 조회
@app.get("/signals")
def get_signals():
    return signals

# ✅ 서버 시작 시 자동 스캐너 실행
@app.on_event("startup")
def start():
    threading.Thread(target=run_scanner, args=(signals,), daemon=True).start()
