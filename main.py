from fastapi import FastAPI
from scanner import run_scanner
import threading

app = FastAPI()

signals = []

@app.get("/signals")
def get_signals():
    return signals

def start():
    run_scanner(signals)

# 🔥 백그라운드 실행
threading.Thread(target=start, daemon=True).start()