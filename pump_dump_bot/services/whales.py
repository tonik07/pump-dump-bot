"""
Сервис отслеживания китовых сделок через Binance WebSocket API.
Отслеживает агрегированные сделки от $100k+ в реальном времени.
"""
import asyncio
import aiohttp
import json
import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

WHALE_THRESHOLD = 100_000  # минимальная сделка в USDT
AGGREGATE_WINDOW = 60  # секунды — агрегируем сделки за 1 минуту

# Хранилище агрегированных сделок: {symbol: {side: total_usdt, count}}
_whale_aggregator: dict = {}
_last_prices: dict = {}


async def fetch_price(session: aiohttp.ClientSession, symbol: str) -> float:
    try:
        async with session.get(
            f"https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            if r.status == 200:
                data = await r.json()
                return float(data["price"])
    except Exception:
        pass
    return 0.0


async def get_recent_large_trades(session: aiohttp.ClientSession, symbol: str, min_usdt: float = 100_000) -> list:
    """Получаем последние крупные сделки через REST API"""
    try:
        async with session.get(
            f"https://api.binance.com/api/v3/aggTrades",
            params={"symbol": symbol, "limit": 500},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            if r.status != 200:
                return []
            trades = await r.json()

        price = _last_prices.get(symbol, 0)
        if not price:
            price = await fetch_price(session, symbol)
            _last_prices[symbol] = price

        if not price:
            return []

        large = []
        now_ms = int(time.time() * 1000)
        window_ms = AGGREGATE_WINDOW * 1000

        for t in trades:
            trade_time = t.get("T", 0)
            if now_ms - trade_time > window_ms:
                continue
            qty = float(t.get("q", 0))
            usdt_val = qty * price
            if usdt_val >= min_usdt:
                large.append({
                    "symbol": symbol,
                    "side": "SELL" if t.get("m") else "BUY",
                    "usdt": usdt_val,
                    "qty": qty,
                    "price": price,
                    "time_ms": trade_time,
                })

        return large

    except Exception as e:
        logger.warning(f"Large trades error {symbol}: {e}")
        return []


async def scan_whales(watchlist: list, min_usdt: float = 100_000) -> list[dict]:
    """
    Сканируем все монеты вотчлиста на крупные сделки за последнюю минуту.
    Возвращает список агрегированных китовых активностей.
    """
    results = []

    async with aiohttp.ClientSession() as session:
        tasks = [get_recent_large_trades(session, sym, min_usdt) for sym in watchlist]
        all_trades = await asyncio.gather(*tasks, return_exceptions=True)

    # Агрегируем по символу и стороне
    agg: dict = {}
    for trades in all_trades:
        if not isinstance(trades, list):
            continue
        for t in trades:
            sym = t["symbol"]
            side = t["side"]
            key = f"{sym}_{side}"
            if key not in agg:
                agg[key] = {
                    "symbol": sym,
                    "label": sym.replace("USDT", ""),
                    "side": side,
                    "total_usdt": 0,
                    "count": 0,
                    "price": t["price"],
                }
            agg[key]["total_usdt"] += t["usdt"]
            agg[key]["count"] += 1

    # Фильтруем значимые активности
    for key, data in agg.items():
        if data["total_usdt"] >= min_usdt:
            results.append(data)

    # Сортируем по объёму
    results.sort(key=lambda x: x["total_usdt"], reverse=True)
    return results


def format_whale_alert(whale: dict) -> str:
    side = whale["side"]
    side_emoji = "🟢 ПОКУПКА" if side == "BUY" else "🔴 ПРОДАЖА"
    usdt = whale["total_usdt"]

    if usdt >= 1_000_000:
        usdt_str = f"${usdt/1_000_000:.2f}M"
    else:
        usdt_str = f"${usdt/1_000:.0f}K"

    price = whale["price"]
    if price < 0.01:
        price_str = f"${price:.6f}"
    elif price < 1:
        price_str = f"${price:.4f}"
    else:
        price_str = f"${price:.2f}"

    intensity = ""
    if usdt >= 1_000_000:
        intensity = "🚨 МЕГА КИТ"
    elif usdt >= 500_000:
        intensity = "🐋 КРУПНЫЙ КИТ"
    else:
        intensity = "🐬 КИТ"

    return (
        f"{intensity} — <b>#{whale['label']}</b>\n"
        f"{'━'*24}\n"
        f"{side_emoji}\n"
        f"💰 Объём: <b>{usdt_str}</b>\n"
        f"📊 Сделок: {whale['count']} шт.\n"
        f"💵 Цена: <code>{price_str}</code>\n\n"
        f"⚠️ <i>Наблюдение — не сигнал к действию</i>"
    )
