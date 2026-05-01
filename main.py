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

VOLUME_SPIKE_MULTIPLIER = 1.5
CANDLE_LIMIT = 200
ALERT_COOLDOWN_SECONDS = 60
LOG_LEVEL = logging.INFO

TP_MOVE_RATIO = 0.005   # +0.5%
SL_MOVE_RATIO = 0.005   # -0.5%
LEVERAGE = 10

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("discord-mtf-signal-bot")


# =========================
# 데이터 구조
# =========================
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
        self.live_candle: Dict[str, Dict[str, Optional[Candle]]] = {
            symbol: {interval: None for interval in INTERVALS}
            for symbol in SYMBOLS
        }

        self.bullish_ob_active: Dict[str, Dict[str, bool]] = {
            symbol: {interval: False for interval in INTERVALS}
            for symbol in SYMBOLS
        }
        self.bullish_ob_time: Dict[str, Dict[str, Optional[int]]] = {
            symbol: {interval: None for interval in INTERVALS}
            for symbol in SYMBOLS
        }

        self.last_alert_key_time: Dict[str, float] = {}

        # 계정 전체 1포지션 개념 유지
        self.active_trade = {
            "symbol": None,
            "interval": None,
            "entry_price": None,
            "tp_price": None,
            "sl_price": None,
            "entered_at": None,
            "is_active": False,
        }


STATE = State()


# =========================
# 공용 함수
# =========================
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


# =========================
# 지표 계산
# =========================
def calc_ma14_from_closed(symbol: str, interval: str) -> Optional[float]:
    candles = list(STATE.closed_candles[symbol][interval])
    if len(candles) < 14:
        return None
    return sum(c.close for c in candles[-14:]) / 14.0


def calc_prev_ma14(symbol: str, interval: str) -> Optional[float]:
    candles = list(STATE.closed_candles[symbol][interval])
    if len(candles) < 15:
        return None
    return sum(c.close for c in candles[-15:-1]) / 14.0


def calc_live_ma14(symbol: str, interval: str) -> Optional[float]:
    candles = list(STATE.closed_candles[symbol][interval])
    live = STATE.live_candle[symbol][interval]
    if len(candles) < 13 or live is None:
        return None
    return (sum(c.close for c in candles[-13:]) + live.close) / 14.0


def avg_volume_20(symbol: str, interval: str) -> Optional[float]:
    candles = list(STATE.closed_candles[symbol][interval])
    if len(candles) < 20:
        return None
    return sum(c.volume for c in candles[-20:]) / 20.0


# =========================
# 전략 조건
# =========================
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


def ma14_cross_on_closed(symbol: str, interval: str) -> bool:
    candles = list(STATE.closed_candles[symbol][interval])
    if len(candles) < 15:
        return False

    prev_candle = candles[-2]
    curr_candle = candles[-1]

    prev_ma = calc_prev_ma14(symbol, interval)
    curr_ma = calc_ma14_from_closed(symbol, interval)

    if prev_ma is None or curr_ma is None:
        return False

    body_low = min(curr_candle.open, curr_candle.close)
    body_high = max(curr_candle.open, curr_candle.close)

    result = (
        prev_ma > prev_candle.high and
        body_low <= curr_ma <= body_high
    )

    print(
        f"[{symbol}][{interval}] CLOSED MA CHECK | "
        f"prev_ma={prev_ma:.2f} prev_high={prev_candle.high:.2f} | "
        f"curr_ma={curr_ma:.2f} body_low={body_low:.2f} body_high={body_high:.2f} | "
        f"result={result}"
    )

    return result


def ma14_cross_live(symbol: str, interval: str) -> bool:
    candles = list(STATE.closed_candles[symbol][interval])
    live = STATE.live_candle[symbol][interval]

    if len(candles) < 14 or live is None:
        return False

    prev_candle = candles[-1]
    prev_ma = calc_ma14_from_closed(symbol, interval)
    current_live_ma = calc_live_ma14(symbol, interval)

    if prev_ma is None or current_live_ma is None:
        return False

    body_low = min(live.open, live.close)
    body_high = max(live.open, live.close)

    result = (
        prev_ma > prev_candle.high and
        body_low <= current_live_ma <= body_high
    )

    print(
        f"[{symbol}][{interval}] LIVE MA CHECK | "
        f"prev_ma={prev_ma:.2f} prev_high={prev_candle.high:.2f} | "
        f"live_ma={current_live_ma:.2f} body_low={body_low:.2f} body_high={body_high:.2f} | "
        f"result={result}"
    )

    return result


def live_volume_spike(symbol: str, interval: str) -> bool:
    live = STATE.live_candle[symbol][interval]
    avg_vol = avg_volume_20(symbol, interval)
    if live is None or avg_vol is None:
        return False

    ratio = live.volume / avg_vol if avg_vol > 0 else 0
    result = live.volume >= avg_vol * VOLUME_SPIKE_MULTIPLIER

    print(
        f"[{symbol}][{interval}] LIVE VOL CHECK | "
        f"live_vol={live.volume:.2f} avg20={avg_vol:.2f} ratio={ratio:.2f} | "
        f"threshold={VOLUME_SPIKE_MULTIPLIER} | result={result}"
    )

    return result


# =========================
# 활성 신호 관리
# =========================
def clear_active_trade():
    print("[TRADE] clear_active_trade")
    STATE.active_trade = {
        "symbol": None,
        "interval": None,
        "entry_price": None,
        "tp_price": None,
        "sl_price": None,
        "entered_at": None,
        "is_active": False,
    }


def has_active_trade() -> bool:
    return bool(STATE.active_trade["is_active"])


# =========================
# 알림 함수
# =========================
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


def send_entry_alert(symbol: str, interval: str, entry_price: float, candle_time: int):
    key = f"entry_{symbol}_{interval}_{candle_time}"
    if not should_send_alert(key):
        return

    if has_active_trade():
        print(f"[ENTRY BLOCKED] active_trade exists: {STATE.active_trade}")
        logger.info("Active trade exists. Skip new entry alert for %s %s", symbol, interval)
        return

    tp_price = entry_price * (1 + TP_MOVE_RATIO)
    sl_price = entry_price * (1 - SL_MOVE_RATIO)

    msg = (
        f"🚨롱 신호 감지!\n"
        f"📈차트를 확인하고 롱 포지션에 진입하세요!\n\n"
        f"⚡진입근거 : 1. 직전 상승형 오더블록 생성\n"
        f"                  2. MA 14선이 캔들 몸통을 통과\n\n"
        f"🔥종목: {symbol}\n"
        f"⏰시간봉: {interval}\n"
        f"✅ 현재가 : {entry_price:.2f}\n"
        f"🟢 익절가 : {tp_price:.2f} (5%)\n"
        f"🔴 손절가 : {sl_price:.2f}(-5%)\n"
        f"------------------------------------------------\n"
    )

    try:
        send_discord_message(msg)

        STATE.active_trade = {
            "symbol": symbol,
            "interval": interval,
            "entry_price": entry_price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "entered_at": candle_time,
            "is_active": True,
        }

        print(f"[ENTRY SUCCESS] {STATE.active_trade}")
        logger.info("Sent entry alert successfully: %s %s", symbol, interval)

    except Exception as e:
        print(f"[ENTRY FAILED] symbol={symbol} interval={interval} error={e}")
        logger.exception("Failed to send entry alert for %s %s: %s", symbol, interval, e)


def send_take_profit_alert(symbol: str, interval: str, current_price: float):
    key = f"tp_{symbol}_{interval}_{STATE.active_trade['entered_at']}"
    if not should_send_alert(key):
        return

    msg = (
        f"🎊수익 5%를 달성 하였습니다!\n"
        f"😊축하합니다!\n\n"
        f"🔥종목 : {symbol}\n"
        f"⏰시간봉: {interval}\n"
        f"💵현재가 : {current_price:.2f}\n"
        f"------------------------------------------------\n"
    )
    try:
        send_discord_message(msg)
        logger.info("Sent take profit alert: %s %s", symbol, interval)
        clear_active_trade()
    except Exception as e:
        logger.exception("Failed take profit alert: %s", e)


def send_stop_loss_alert(symbol: str, interval: str, current_price: float):
    key = f"sl_{symbol}_{interval}_{STATE.active_trade['entered_at']}"
    if not should_send_alert(key):
        return

    msg = (
        f"😟5% 손실 중 입니다.\n"
        f"⛔손절을 진행하고 다음 수익을 기대해 보세요!\n\n"
        f"🔥종목 : {symbol}\n"
        f"⏰시간봉: {interval}\n"
        f"💵현재가 : {current_price:.2f}\n"
        f"------------------------------------------------\n"
    )
    try:
        send_discord_message(msg)
        logger.info("Sent stop loss alert: %s %s", symbol, interval)
        clear_active_trade()
    except Exception as e:
        logger.exception("Failed stop loss alert: %s", e)


def send_bearish_take_profit_signal(symbol: str, interval: str, current_price: float):
    key = f"bearish_tp_{symbol}_{interval}_{STATE.active_trade['entered_at']}"
    if not should_send_alert(key):
        return

    msg = (
        f"🎯익절 신호 감지!\n"
        f"⛔하락형 오더블록이 생성되었습니다.\n"
        f"🚨지금이라도 익절을 준비 해 주세요!\n\n"
        f"🔥종목 : {symbol}\n"
        f"⏰시간봉: {interval}\n"
        f"💵현재가 : {current_price:.2f}\n"
        f"------------------------------------------------\n"
    )
    try:
        send_discord_message(msg)
        logger.info("Sent bearish take profit signal: %s %s", symbol, interval)
        clear_active_trade()
    except Exception as e:
        logger.exception("Failed bearish take profit alert: %s", e)


# =========================
# 처리 로직
# =========================
async def monitor_active_trade(symbol: str, interval: str):
    trade = STATE.active_trade
    live = STATE.live_candle[symbol][interval]

    if not trade["is_active"]:
        return
    if trade["symbol"] != symbol:
        return
    if trade["interval"] != interval:
        return
    if live is None:
        return

    current_price = live.close
    tp_price = trade["tp_price"]
    sl_price = trade["sl_price"]

    print(
        f"[{symbol}][{interval}] TRADE MONITOR | "
        f"entry={trade['entry_price']:.2f} current={current_price:.2f} "
        f"tp={tp_price:.2f} sl={sl_price:.2f}"
    )

    if current_price >= tp_price:
        send_take_profit_alert(symbol, interval, current_price)
    elif current_price <= sl_price:
        send_stop_loss_alert(symbol, interval, current_price)


async def handle_closed_candle(symbol: str, interval: str):
    candles = list(STATE.closed_candles[symbol][interval])
    if len(candles) < 2:
        return

    prev_candle = candles[-2]
    curr_candle = candles[-1]

    bullish_ob = is_bullish_order_block(prev_candle, curr_candle)
    bearish_ob = is_bearish_order_block(prev_candle, curr_candle)
    cross_closed = ma14_cross_on_closed(symbol, interval)

    print(
        f"\n[{symbol}][{interval}] CLOSED CANDLE"
        f"\nprev: O={prev_candle.open:.2f} H={prev_candle.high:.2f} L={prev_candle.low:.2f} C={prev_candle.close:.2f}"
        f"\ncurr: O={curr_candle.open:.2f} H={curr_candle.high:.2f} L={curr_candle.low:.2f} C={curr_candle.close:.2f}"
        f"\nbullish_ob={bullish_ob}, bearish_ob={bearish_ob}, "
        f"bullish_active={STATE.bullish_ob_active[symbol][interval]}, cross_closed={cross_closed}, "
        f"active_trade={STATE.active_trade}"
    )

    if bullish_ob:
        print(f"[{symbol}][{interval}] >>> BULLISH ORDER BLOCK DETECTED")
        STATE.bullish_ob_active[symbol][interval] = True
        STATE.bullish_ob_time[symbol][interval] = curr_candle.open_time
        send_bullish_ob_alert(symbol, interval, curr_candle)

    if bearish_ob:
        print(f"[{symbol}][{interval}] >>> BEARISH ORDER BLOCK DETECTED")
        send_bearish_ob_alert(symbol, interval, curr_candle)

        if (
            STATE.active_trade["is_active"] and
            STATE.active_trade["symbol"] == symbol and
            STATE.active_trade["interval"] == interval
        ):
            entry_price = STATE.active_trade["entry_price"]
            current_price = curr_candle.close
            pnl_percent = ((current_price - entry_price) / entry_price) * 100 * LEVERAGE

            print(f"[{symbol}][{interval}] bearish OB with active trade | pnl_percent={pnl_percent:.2f}")

            if pnl_percent < 5:
                send_bearish_take_profit_signal(symbol, interval, current_price)

        STATE.bullish_ob_active[symbol][interval] = False
        STATE.bullish_ob_time[symbol][interval] = None
        print(f"[{symbol}][{interval}] bullish_ob_active reset due to bearish OB")

    if (
        STATE.bullish_ob_active[symbol][interval] and
        not has_active_trade() and
        cross_closed
    ):
        print(f"[{symbol}][{interval}] >>> ENTRY SIGNAL DETECTED ON CLOSED CANDLE")
        send_entry_alert(symbol, interval, curr_candle.close, curr_candle.close_time)
        STATE.bullish_ob_active[symbol][interval] = False
        STATE.bullish_ob_time[symbol][interval] = None
        print(f"[{symbol}][{interval}] bullish_ob_active reset after entry alert")


async def handle_live_candle(symbol: str, interval: str):
    live = STATE.live_candle[symbol][interval]
    if live is None:
        return

    live_cross = ma14_cross_live(symbol, interval)
    vol_spike = live_volume_spike(symbol, interval)

    print(
        f"[{symbol}][{interval}] LIVE | "
        f"bullish_active={STATE.bullish_ob_active[symbol][interval]} "
        f"has_active_trade={has_active_trade()} "
        f"live_cross={live_cross} vol_spike={vol_spike} "
        f"live_open={live.open:.2f} live_close={live.close:.2f} "
        f"live_high={live.high:.2f} live_low={live.low:.2f}"
    )

    if has_active_trade():
        return
    if not STATE.bullish_ob_active[symbol][interval]:
        return
    if not live_cross:
        return
    if not vol_spike:
        return

    print(f"[{symbol}][{interval}] >>> ENTRY SIGNAL DETECTED ON LIVE CANDLE")
    send_entry_alert(symbol, interval, live.close, live.close_time)

    STATE.bullish_ob_active[symbol][interval] = False
    STATE.bullish_ob_time[symbol][interval] = None
    print(f"[{symbol}][{interval}] bullish_ob_active reset after live entry alert")


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


# =========================
# 웹소켓 루프
# =========================
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
                        STATE.live_candle[symbol][interval] = None
                        await handle_closed_candle(symbol, interval)
                    else:
                        STATE.live_candle[symbol][interval] = candle
                        await handle_live_candle(symbol, interval)
                        await monitor_active_trade(symbol, interval)

        except Exception as e:
            logger.exception("WS error: %s", e)
            await asyncio.sleep(3)


async def main():
    if not DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/1499537754030080041/cQb6B2ocur3RrMPahgIow2J768iQw0x25TnB__v76vnZey6SEeXwmD48GodZg5JsZGVF"):
        raise ValueError("DISCORD_WEBHOOK_URL 값을 확인해주세요.")

    bootstrap()

    try:
        send_discord_message("✅ 아롱이와 함께하는 <비트코인/이더리움> 오더블록 알리미!\n" \
        "지금 시작합니다! \n" \
        "   \n" \
        "🚨업데이트 내용 공지!\n" \
        "1. 타임프레임 증설 : 15분 봉만 보던 알리미가 수정 되었습니다.\n" \
        "   1) 5분봉, 30분봉, 1시간봉, 4시간봉, 12시간봉, 1일봉 추가\n" \
        "      - 5분봉 삭제 : 너무 많은 알림으로 혼돈을 줄 수 있어 삭제 되었습니다.\n" \
        "   2) 타임프레임이 길면 길 수록 정확도는 올라갑니다.\n" \
        "  \n" \
        "2. 종목 추가 : 새로운 코인을 아롱이가 새로 분석 해 드립니다!\n" \
        "   1) 리플(XRPUSDT) 추가 \n" \
        "   2) 추후 결과에 부합하는 종목 발생 시 추가 수정 예정\n" \
        "\n" \
        "두 형님들의 성공적인 투자를 응원합니다!\n" \
        "\n" \
        "이상입니다.\n" \
        "감사합니다.\n") \
        
    except Exception as e:
        logger.exception("Startup Discord message failed: %s", e)

    await ws_loop()


if __name__ == "__main__":
    asyncio.run(main())