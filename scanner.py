import time
from data import get_all_symbols, get_klines

def run_scanner(signals):
    print("🔥 전체 종목 스캔 시작")

    symbols = get_all_symbols()
    print(f"총 종목 수: {len(symbols)}")

    while True:
        try:
            signals.clear()

            # 🔥 처음엔 30개만 테스트
            for symbol in symbols[:30]:
                try:
                    df = get_klines(symbol)

                    last_price = df["close"].iloc[-1]

                    signals.append({
                        "symbol": symbol,
                        "price": last_price,
                        "type": "TEST"
                    })

                except Exception as e:
                    print("❌ 에러:", symbol, e)

            print(f"✅ 스캔 완료: {len(signals)}개")

            time.sleep(10)

        except Exception as e:
            print("❌ 전체 스캐너 에러:", e)
            time.sleep(5)
