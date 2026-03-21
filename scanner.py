import time
from strategy import check_signal
from data import get_symbols

def run_scanner(signal_store):
    symbols = get_symbols()
    alerted = set()

    while True:
        for s in symbols:
            if check_signal(s):
                if s not in alerted:
                    signal_store.append({
                        "symbol": s,
                        "type": "LONG"
                    })
                    print(f"🚀 SIGNAL: {s}")
                    alerted.add(s)
            else:
                if s in alerted:
                    alerted.remove(s)

            time.sleep(0.05)