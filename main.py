from fastapi import FastAPI
from scanner import run_scanner
import threading

app = FastAPI()

signals = []

@app.get("/")
def root():
    return {"status": "running"}

@app.get("/signals")
def get_signals():
    return signals

def start_scanner():
    run_scanner(signals)

@app.on_event("startup")
def start():
    threading.Thread(target=start_scanner, daemon=True).start()
