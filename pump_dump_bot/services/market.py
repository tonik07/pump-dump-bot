"""
Сервис получения данных с Binance Public API.
Динамический вотчлист — топ-30 по объёму, обновляется каждые 6 часов.
"""
import asyncio
import aiohttp
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com/api/v3"
FAPI_URL = "https://fapi.binance.com/fapi/v1"

EXCLUDE = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "USDCUSDT", "BUSDUSDT", "TUSDUSDT", "USDTUSDT", "FDUSDUSDT", "USDSUSDT"}

_watchlist_cache: list = []
_watchlist_labels: dict = {}
_watchlist_updated_at: float = 0
WATCHLIST_TTL = 6 * 3600
TOP_N = 30


async def fetch_json(session, url, params=None):
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"Fetch error {url}: {e}")
    return None


async def update_watchlist(session) -> list:
    global _watchlist_cache, _watchlist_labels, _watchlist_updated_at

    now = time.time()
    if _watchlist_cache and (now - _watchlist_updated_at) < WATCHLIST_TTL:
        return _watchlist_cache

    logger.info("Обновляем динамический вотчлист с Binance...")
    data = await fetch_json(session, f"{BASE_URL}/ticker/24hr")

    if not data:
        logger.warning("Не удалось получить тикеры — используем кэш")
        return _watchlist_cache or []

    usdt_pairs = [
        d for d in data
        if d["symbol"].endswith("USDT")
        and d["symbol"] not in EXCLUDE
        and float(d.get("quoteVolume", 0)) > 5_000_000
    ]

    usdt_pairs.sort(key=lambda d: float(d.get("quoteVolume", 0)), reverse=True)
    top = usdt_pairs[:TOP_N]

    _watchlist_cache = [d["symbol"] for d in top]
    _watchlist_labels = {d["symbol"]: d["symbol"].replace("USDT", "") for d in top}
    _watchlist_updated_at = now

    logger.info(f"Вотчлист обновлён: {len(_watchlist_cache)} монет — {_watchlist_cache[:5]}...")
    return _watchlist_cache


def get_watchlist() -> list:
    return _watchlist_cache


def get_label(symbol: str) -> str:
    return _watchlist_labels.get(symbol, symbol.replace("USDT", ""))


@dataclass
class CoinData:
    symbol: str
    label: str
    price: float
    price_change_1h: float
    price_change_24h: float
    volume_usdt: float
    volume_change_pct: float
    quote_volume: float
    high_24h: float
    low_24h: float
    oi_usdt: Optional[float]
    oi_change_pct: Optional[float]
    funding_rate: Optional[float]
    long_short_ratio: Optional[float]
    signal: str = "neutral"
    score: int = 0
    analysis: str = ""
    signals_list: list = field(default_factory=list)


def compute_volume_change(klines: list) -> float:
    if not klines or len(klines) < 2:
        return 0.0
    volumes = [float(k[5]) for k in klines]
    recent = sum(volumes[-24:]) / 24 if len(volumes) >= 24 else sum(volumes) / len(volumes)
    prev = sum(volumes[-48:-24]) / 24 if len(volumes) >= 48 else recent
    if prev == 0:
        return 0.0
    return ((recent - prev) / prev) * 100


def analyze_coin(c: CoinData) -> CoinData:
    score = 0
    signals = []

    if c.volume_change_pct > 100:
        score += 3
        signals.append(("📈 Объём ×2+ от нормы", "bull"))
    elif c.volume_change_pct > 50:
        score += 2
        signals.append((f"📈 Объём +{c.volume_change_pct:.0f}%", "bull"))
    elif c.volume_change_pct > 20:
        score += 1
        signals.append((f"📊 Объём выше нормы (+{c.volume_change_pct:.0f}%)", "bull"))
    elif c.volume_change_pct < -30:
        score -= 2
        signals.append(("📉 Объём сдыхает", "bear"))

    if c.oi_change_pct is not None:
        if c.oi_change_pct > 5:
            score += 2
            signals.append((f"🔥 OI растёт +{c.oi_change_pct:.1f}%", "bull"))
        elif c.oi_change_pct < -5:
            score -= 2
            signals.append((f"❄️ OI падает {c.oi_change_pct:.1f}%", "bear"))

    if c.funding_rate is not None:
        fr = c.funding_rate * 100
        if fr > 0.05:
            score -= 2
            signals.append((f"⚠️ Funding перегрет +{fr:.4f}%", "bear"))
        elif fr < -0.01:
            score += 1
            signals.append((f"💡 Funding отрицательный {fr:.4f}%", "bull"))

    if c.long_short_ratio is not None:
        lsr = c.long_short_ratio
        if lsr > 1.5:
            score += 1
            signals.append((f"📊 Long/Short: {lsr:.2f} — лонги доминируют", "bull"))
        elif lsr < 0.7:
            score -= 1
            signals.append((f"📊 Long/Short: {lsr:.2f} — шорты давят", "bear"))

    if c.price_change_24h > 15 and c.volume_change_pct > 100:
        score -= 1
        signals.append(("🚨 Быстрый рост — возможен откат", "warn"))

    if c.price_change_24h < -10 and c.volume_change_pct > 80:
        score += 1
        signals.append(("🛒 Слив на объёме — возможен разворот", "warn"))

    range_24h = c.high_24h - c.low_24h
    if range_24h > 0:
        pos = (c.price - c.low_24h) / range_24h
        if pos < 0.15:
            score += 1
            signals.append(("🔻 У дна диапазона 24ч", "bull"))
        elif pos > 0.85:
            score -= 1
            signals.append(("🔺 У хая 24ч — осторожно", "warn"))

    c.score = score
    c.signals_list = signals

    if score >= 4:
        c.signal = "pump"
    elif score <= -3:
        c.signal = "dump"
    else:
        c.signal = "neutral"

    bull_s = [s[0] for s in signals if s[1] == "bull"]
    bear_s = [s[0] for s in signals if s[1] == "bear"]

    if c.signal == "pump":
        c.analysis = f"Монета в фазе накопления. {'. '.join(bull_s[:2])}. Стоит присмотреться."
    elif c.signal == "dump":
        c.analysis = f"Признаки перегрева. {'. '.join(bear_s[:2])}. Осторожно."
    else:
        c.analysis = "Нейтральная зона — аномалий не обнаружено."

    return c


async def scan_market() -> list:
    results = []

    async with aiohttp.ClientSession() as session:
        watchlist = await update_watchlist(session)
        if not watchlist:
            return []

        data = await fetch_json(session, f"{BASE_URL}/ticker/24hr")
        tickers = {d["symbol"]: d for d in data if d["symbol"] in watchlist} if data else {}

        tasks = [_fetch_coin_data(session, sym, tickers.get(sym)) for sym in watchlist]
        coins = await asyncio.gather(*tasks, return_exceptions=True)

    for coin in coins:
        if isinstance(coin, CoinData):
            results.append(analyze_coin(coin))

    results.sort(key=lambda c: (0 if c.signal == "pump" else 1 if c.signal == "dump" else 2, -abs(c.score)))
    return results


async def _fetch_coin_data(session, symbol, ticker):
    if not ticker:
        return None
    label = get_label(symbol)
    try:
        price = float(ticker["lastPrice"])
        price_change_24h = float(ticker["priceChangePercent"])
        volume_usdt = float(ticker["quoteVolume"])
        quote_volume = float(ticker["volume"])
        high_24h = float(ticker["highPrice"])
        low_24h = float(ticker["lowPrice"])
    except (KeyError, ValueError):
        return None

    klines, oi_data, oi_hist, funding, lsr = await asyncio.gather(
        fetch_json(session, f"{BASE_URL}/klines", {"symbol": symbol, "interval": "1h", "limit": 48}),
        fetch_json(session, f"{FAPI_URL}/openInterest", {"symbol": symbol}),
        fetch_json(session, f"{FAPI_URL}/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 2}),
        fetch_json(session, f"{FAPI_URL}/premiumIndex", {"symbol": symbol}),
        fetch_json(session, f"{FAPI_URL}/globalLongShortAccountRatio", {"symbol": symbol, "period": "1h", "limit": 1}),
        return_exceptions=True
    )

    volume_change_pct = compute_volume_change(klines) if isinstance(klines, list) else 0.0

    price_change_1h = 0.0
    if isinstance(klines, list) and len(klines) >= 2:
        try:
            price_change_1h = ((float(klines[-1][4]) - float(klines[-2][1])) / float(klines[-2][1])) * 100
        except (IndexError, ValueError, ZeroDivisionError):
            pass

    oi_usdt = None
    if isinstance(oi_data, dict) and "openInterest" in oi_data:
        try:
            oi_usdt = float(oi_data["openInterest"]) * price
        except (ValueError, TypeError):
            pass

    oi_change_pct = None
    if isinstance(oi_hist, list) and len(oi_hist) >= 2:
        try:
            oi_prev = float(oi_hist[-2]["sumOpenInterest"])
            oi_curr = float(oi_hist[-1]["sumOpenInterest"])
            if oi_prev > 0:
                oi_change_pct = ((oi_curr - oi_prev) / oi_prev) * 100
        except (IndexError, KeyError, ValueError):
            pass

    funding_rate = None
    if isinstance(funding, dict):
        try:
            funding_rate = float(funding.get("lastFundingRate", 0))
        except (ValueError, TypeError):
            pass

    long_short = None
    if isinstance(lsr, list) and lsr:
        try:
            long_short = float(lsr[0].get("longShortRatio", 1.0))
        except (IndexError, KeyError, ValueError):
            pass

    return CoinData(
        symbol=symbol, label=label, price=price,
        price_change_1h=price_change_1h, price_change_24h=price_change_24h,
        volume_usdt=volume_usdt, volume_change_pct=volume_change_pct,
        quote_volume=quote_volume, high_24h=high_24h, low_24h=low_24h,
        oi_usdt=oi_usdt, oi_change_pct=oi_change_pct,
        funding_rate=funding_rate, long_short_ratio=long_short,
    )
