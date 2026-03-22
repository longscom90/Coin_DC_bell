from fastapi import FastAPI
import threading

from scanner import run_scanner

app = FastAPI()

signals = []

@app.get("/")
def home():
    return {"status": "EMA 정배열 롱 시그널 알리미 실행중"}

@app.get("/signals")
def get_signals():
    return signals

@app.on_event("startup")
def start():
    threading.Thread(target=run_scanner, args=(signals,), daemon=True).start()
