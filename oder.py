import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

import requests
import websockets


# =========================
# 설정
# =========================
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1499537754030080041/cQb6B2ocur3RrMPahgIow2J768iQw0x25TnB__v76vnZey6SEeXwmD48GodZg5JsZGVF"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
INTERVALS = ["15m", "30m", "1h", "4h", "12h", "1d"]

REST_BASE_URL = "https://fapi.binance.com"
WS_BASE_URL = "wss://fstream.binance.com/market"

CANDLE_LIMIT = 200
ALERT_COOLDOWN_SECONDS = 60
LOG_LEVEL = logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("orderblock-alert-bot")


@dataclass
class Candle:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


class State:
    def __init__(self):
        self.closed_candles: Dict[str, Dict[str, Deque[Candle]]] = {
            symbol: {interval: deque(maxlen=300) for interval in INTERVALS}
            for symbol in SYMBOLS
        }
        self.last_alert_key_time: Dict[str, float] = {}


STATE = State()


def send_discord_message(content: str):
    payload = {
        "content": content,
        "allowed_mentions": {"parse": []}
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    print(f"[DISCORD] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()


def format_kst(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_ms / 1000 + 9 * 3600))


def should_send_alert(alert_key: str) -> bool:
    now = time.time()
    last = STATE.last_alert_key_time.get(alert_key, 0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        print(f"[ALERT BLOCKED] cooldown key={alert_key}")
        return False
    STATE.last_alert_key_time[alert_key] = now
    return True


def fetch_klines(symbol: str, interval: str, limit: int = 200):
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    resp = requests.get(f"{REST_BASE_URL}/fapi/v1/klines", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def bootstrap():
    for symbol in SYMBOLS:
        for interval in INTERVALS:
            rows = fetch_klines(symbol, interval, CANDLE_LIMIT)
            dq = STATE.closed_candles[symbol][interval]
            dq.clear()

            for row in rows:
                dq.append(
                    Candle(
                        open_time=int(row[0]),
                        close_time=int(row[6]),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        is_closed=True,
                    )
                )

            logger.info("[%s][%s] loaded %d candles", symbol, interval, len(dq))


def is_bullish_order_block(prev_candle: Candle, curr_candle: Candle) -> bool:
    return (
        prev_candle.open > prev_candle.close and
        curr_candle.close > curr_candle.open and
        curr_candle.open <= prev_candle.close and
        curr_candle.close >= prev_candle.open
    )


def is_bearish_order_block(prev_candle: Candle, curr_candle: Candle) -> bool:
    return (
        prev_candle.close > prev_candle.open and
        curr_candle.open > curr_candle.close and
        curr_candle.open >= prev_candle.close and
        curr_candle.close <= prev_candle.open
    )


def send_bullish_ob_alert(symbol: str, interval: str, candle: Candle):
    key = f"bullish_ob_{symbol}_{interval}_{candle.open_time}"
    if not should_send_alert(key):
        return

    msg = (
        f"🟢 상승형 오더블록이 생성 되었습니다!\n"
        f"🔥종목: {symbol}\n"
        f"⏰시간봉: {interval}\n"
        f"🚨차트를 확인하여 매매를 준비 해 주세요!\n"
        f"🕒시간(KST): {format_kst(candle.close_time)}\n"
        f"------------------------------------------------\n"
    )
    try:
        send_discord_message(msg)
        logger.info("Sent bullish OB alert: %s %s", symbol, interval)
    except Exception as e:
        logger.exception("Failed bullish OB alert: %s", e)


def send_bearish_ob_alert(symbol: str, interval: str, candle: Candle):
    key = f"bearish_ob_{symbol}_{interval}_{candle.open_time}"
    if not should_send_alert(key):
        return

    msg = (
        f"🔴 하락형 오더블록이 생성 되었습니다!\n"
        f"🔥종목: {symbol}\n"
        f"⏰시간봉: {interval}\n"
        f"🚨차트를 확인하여 매매를 준비 해 주세요!\n"
        f"🕒시간(KST): {format_kst(candle.close_time)}\n"
        f"------------------------------------------------\n"
    )
    try:
        send_discord_message(msg)
        logger.info("Sent bearish OB alert: %s %s", symbol, interval)
    except Exception as e:
        logger.exception("Failed bearish OB alert: %s", e)


async def handle_closed_candle(symbol: str, interval: str):
    candles = list(STATE.closed_candles[symbol][interval])
    if len(candles) < 2:
        return

    prev_candle = candles[-2]
    curr_candle = candles[-1]

    bullish_ob = is_bullish_order_block(prev_candle, curr_candle)
    bearish_ob = is_bearish_order_block(prev_candle, curr_candle)

    print(
        f"\n[{symbol}][{interval}] CLOSED CANDLE"
        f"\nprev: O={prev_candle.open:.2f} H={prev_candle.high:.2f} L={prev_candle.low:.2f} C={prev_candle.close:.2f}"
        f"\ncurr: O={curr_candle.open:.2f} H={curr_candle.high:.2f} L={curr_candle.low:.2f} C={curr_candle.close:.2f}"
        f"\nbullish_ob={bullish_ob}, bearish_ob={bearish_ob}"
    )

    if bullish_ob:
        print(f"[{symbol}][{interval}] >>> BULLISH ORDER BLOCK DETECTED")
        send_bullish_ob_alert(symbol, interval, curr_candle)

    if bearish_ob:
        print(f"[{symbol}][{interval}] >>> BEARISH ORDER BLOCK DETECTED")
        send_bearish_ob_alert(symbol, interval, curr_candle)


def parse_ws_message(payload: dict) -> Candle:
    k = payload["data"]["k"]
    return Candle(
        open_time=int(k["t"]),
        close_time=int(k["T"]),
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        is_closed=bool(k["x"]),
    )


async def ws_loop():
    streams = "/".join(
        [f"{symbol.lower()}@kline_{interval}" for symbol in SYMBOLS for interval in INTERVALS]
    )
    url = f"{WS_BASE_URL}/stream?streams={streams}"

    while True:
        try:
            logger.info("Connecting WS: %s", url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                logger.info("WS connected")

                while True:
                    raw = await ws.recv()
                    payload = json.loads(raw)
                    symbol = payload["data"]["s"]
                    interval = payload["data"]["k"]["i"]
                    candle = parse_ws_message(payload)

                    if candle.is_closed:
                        STATE.closed_candles[symbol][interval].append(candle)
                        await handle_closed_candle(symbol, interval)

        except Exception as e:
            logger.exception("WS error: %s", e)
            await asyncio.sleep(3)


async def main():
    if not DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/1499537754030080041/cQb6B2ocur3RrMPahgIow2J768iQw0x25TnB__v76vnZey6SEeXwmD48GodZg5JsZGVF"):
        raise ValueError("DISCORD_WEBHOOK_URL 값을 확인해주세요.")

    bootstrap()

    try:
        send_discord_message("✅ 아롱이의 오더블록 알리미가 시작되었습니다\n" \
        "📈오더블록만 확인하시고 매매 판단에 참고 해 주세요!\n" \
        "\n" \
        "🚨공지!\n" \
        "1. 오더블록 알리미와 롱 신호감지 알리미가 분리 되었습니다.\n" \
        "　　1) 오더블록 알리미는 이 방에서 계속 확인이 가능합니다.\n" \
        "　　2) 롱 신호감지기는 라니에게 받아주시면 됩니다!\n" \
        "　　　　- 신규<롱 신호 알리미>에서 확인 해 주세요!\n" \
        "\n" \
        "2. 타임프레임은 아래와 같이 고정 합니다.\n" \
        "　　1) 15분, 30분, 1시간, 4시간, 1일\n" \
        "　　2) 익절은 실 차트에서 0.5%에서 익절을 해 주세요.\n" \
        "　　　　- 레버리지 10배 적용 시 → 5%\n" \
        "\n" \
        "두 형님의 성공적인 투자를 응원 합니다!")
    except Exception as e:
        logger.exception("Startup Discord message failed: %s", e)

    await ws_loop()


if __name__ == "__main__":
    asyncio.run(main())