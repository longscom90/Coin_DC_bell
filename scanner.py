import time
from data import get_all_symbols
from strategy import check_long_signal

def run_scanner(signals):
    print("🔥 EMA 정배열 롱 시그널 스캐너 시작")

    symbols = get_all_symbols()
    print(f"총 종목 수: {len(symbols)}")

    alerted = set()

    while True:
        try:
            signals.clear()

            for symbol in symbols[:50]:  # 🔥 초기 테스트용
                try:
                    if check_long_signal(symbol):
                        if symbol not in alerted:
                            signals.append({
                                "symbol": symbol,
                                "type": "LONG"
                            })

                            print(f"🚀 LONG SIGNAL: {symbol}")
                            alerted.add(symbol)
                    else:
                        if symbol in alerted:
                            alerted.remove(symbol)

                except Exception as e:
                    print("❌ 에러:", symbol, e)

            print(f"✅ 스캔 완료: {len(signals)}개")

            time.sleep(15)

        except Exception as e:
            print("❌ 전체 에러:", e)
            time.sleep(5)
