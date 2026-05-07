"""
Сервис получения данных с Binance Public API.
Используем только публичные endpoints — без ключей.
"""
import asyncio
import aiohttp
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api1.binance.com/api/v3"
FAPI_URL = "https://fapi.binance.com/fapi/v1"  # фьючерсы

# Топ шиткоины из топ-20 Binance (без BTC, ETH, SOL)
WATCHLIST = [
    "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "TONUSDT", "SHIBUSDT", "LTCUSDT",
    "UNIUSDT", "NEARUSDT", "APTUSDT", "TRXUSDT", "SUIUSDT",
    "OPUSDT", "ARBUSDT",
]

SYMBOL_LABELS = {
    "BNBUSDT": "BNB", "XRPUSDT": "XRP", "ADAUSDT": "ADA",
    "DOGEUSDT": "DOGE", "AVAXUSDT": "AVAX", "LINKUSDT": "LINK",
    "DOTUSDT": "DOT", "TONUSDT": "TON", "SHIBUSDT": "SHIB",
    "LTCUSDT": "LTC", "UNIUSDT": "UNI", "NEARUSDT": "NEAR",
    "APTUSDT": "APT", "TRXUSDT": "TRX", "SUIUSDT": "SUI",
    "OPUSDT": "OP", "ARBUSDT": "ARB",
}


@dataclass
class CoinData:
    symbol: str
    label: str
    price: float
    price_change_1h: float
    price_change_24h: float
    volume_usdt: float        # объём за 24ч в USDT
    volume_change_pct: float  # изменение объёма vs предыдущий период
    quote_volume: float       # объём в базовой валюте
    high_24h: float
    low_24h: float
    oi_usdt: Optional[float]          # открытый интерес (фьючи)
    oi_change_pct: Optional[float]    # изменение OI
    funding_rate: Optional[float]     # funding rate
    long_short_ratio: Optional[float] # отношение лонг/шорт
    # вычисляемые поля
    signal: str = "neutral"           # pump / dump / neutral
    score: int = 0
    analysis: str = ""
    signals_list: list = None

    def __post_init__(self):
        if self.signals_list is None:
            self.signals_list = []


async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None):
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"Fetch error {url}: {e}")
    return None


async def get_ticker_24h(session: aiohttp.ClientSession) -> dict:
    data = await fetch_json(session, f"{BASE_URL}/ticker/24hr")
    if data:
        return {d["symbol"]: d for d in data if d["symbol"] in WATCHLIST}
    return {}


async def get_klines_1h(session: aiohttp.ClientSession, symbol: str) -> Optional[list]:
    """Получаем 2 свечи по 1ч для сравнения объёмов"""
    return await fetch_json(session, f"{BASE_URL}/klines", params={
        "symbol": symbol, "interval": "1h", "limit": 48
    })


async def get_futures_oi(session: aiohttp.ClientSession, symbol: str) -> Optional[dict]:
    return await fetch_json(session, f"{FAPI_URL}/openInterest", params={"symbol": symbol})


async def get_futures_oi_hist(session: aiohttp.ClientSession, symbol: str) -> Optional[list]:
    return await fetch_json(session, f"{FAPI_URL}/openInterestHist", params={
        "symbol": symbol, "period": "1h", "limit": 2
    })


async def get_funding_rate(session: aiohttp.ClientSession, symbol: str) -> Optional[dict]:
    data = await fetch_json(session, f"{FAPI_URL}/premiumIndex", params={"symbol": symbol})
    return data


async def get_long_short_ratio(session: aiohttp.ClientSession, symbol: str) -> Optional[list]:
    return await fetch_json(session, f"{FAPI_URL}/globalLongShortAccountRatio", params={
        "symbol": symbol, "period": "1h", "limit": 1
    })


def compute_volume_change(klines: list) -> float:
    """Сравниваем среднюю часовую свечу за последние 24ч vs предыдущие 24ч"""
    if not klines or len(klines) < 2:
        return 0.0
    volumes = [float(k[5]) for k in klines]  # индекс 5 = volume
    recent = sum(volumes[-24:]) / 24 if len(volumes) >= 24 else sum(volumes) / len(volumes)
    prev = sum(volumes[-48:-24]) / 24 if len(volumes) >= 48 else recent
    if prev == 0:
        return 0.0
    return ((recent - prev) / prev) * 100


def analyze_coin(c: CoinData) -> CoinData:
    score = 0
    signals = []

    # --- ОБЪЁМ ---
    if c.volume_change_pct > 100:
        score += 3
        signals.append(("📈 Объём ×2+ от нормы", "bull"))
    elif c.volume_change_pct > 50:
        score += 2
        signals.append((f"📈 Объём +{c.volume_change_pct:.0f}%", "bull"))
    elif c.volume_change_pct > 20:
        score += 1
        signals.append((f"📊 Объём немного выше нормы (+{c.volume_change_pct:.0f}%)", "bull"))
    elif c.volume_change_pct < -30:
        score -= 2
        signals.append(("📉 Объём сдыхает", "bear"))

    # --- OI ---
    if c.oi_change_pct is not None:
        if c.oi_change_pct > 5:
            score += 2
            signals.append((f"🔥 OI растёт +{c.oi_change_pct:.1f}% — деньги заходят", "bull"))
        elif c.oi_change_pct < -5:
            score -= 2
            signals.append((f"❄️ OI падает {c.oi_change_pct:.1f}% — позиции закрываются", "bear"))

    # --- FUNDING RATE ---
    if c.funding_rate is not None:
        fr = c.funding_rate * 100
        if fr > 0.05:
            score -= 2
            signals.append((f"⚠️ Funding перегрет +{fr:.4f}% — шорт-сжатие опасно", "bear"))
        elif fr < -0.01:
            score += 1
            signals.append((f"💡 Funding отрицательный {fr:.4f}% — шорты платят лонгам", "bull"))

    # --- LONG/SHORT RATIO ---
    if c.long_short_ratio is not None:
        lsr = c.long_short_ratio
        if lsr > 1.5:
            score += 1
            signals.append((f"📊 Long/Short: {lsr:.2f} — лонги доминируют", "bull"))
        elif lsr < 0.7:
            score -= 1
            signals.append((f"📊 Long/Short: {lsr:.2f} — шорты давят", "bear"))

    # --- ЦЕНА ---
    if c.price_change_24h > 15 and c.volume_change_pct > 100:
        score -= 1
        signals.append(("🚨 Быстрый рост цены при высоком объёме — возможен откат", "warn"))

    if c.price_change_24h < -10 and c.volume_change_pct > 80:
        score += 1
        signals.append(("🛒 Слив на объёме — возможно выбивание стопов перед разворотом", "warn"))

    # --- БЛИЗОСТЬ К ХАЮ/ЛОЮ ---
    range_24h = c.high_24h - c.low_24h
    if range_24h > 0:
        pos_in_range = (c.price - c.low_24h) / range_24h
        if pos_in_range < 0.15:
            score += 1
            signals.append(("🔻 Цена у дна диапазона 24ч — потенциал отскока", "bull"))
        elif pos_in_range > 0.85:
            score -= 1
            signals.append(("🔺 Цена у хая 24ч — осторожно с лонгами", "warn"))

    # --- ИТОГ ---
    c.score = score
    c.signals_list = signals

    if score >= 4:
        c.signal = "pump"
    elif score <= -3:
        c.signal = "dump"
    else:
        c.signal = "neutral"

    # Текстовый вывод
    bull_signals = [s[0] for s in signals if s[1] == "bull"]
    bear_signals = [s[0] for s in signals if s[1] == "bear"]

    if c.signal == "pump":
        reasons = bull_signals[:2]
        c.analysis = f"Монета в фазе накопления. {'. '.join(reasons)}. Стоит присмотреться."
    elif c.signal == "dump":
        reasons = bear_signals[:2]
        c.analysis = f"Признаки перегрева или слива. {'. '.join(reasons)}. Осторожно."
    else:
        c.analysis = "Нейтральная зона — аномалий не обнаружено."

    return c


async def scan_market() -> list[CoinData]:
    """Главная функция — сканирует весь вотчлист"""
    results = []

    async with aiohttp.ClientSession() as session:
        # 1. Получаем 24h тикеры для всех монет
        tickers = await get_ticker_24h(session)

        # 2. Параллельно грузим данные по каждой монете
        tasks = []
        for symbol in WATCHLIST:
            tasks.append(_fetch_coin_data(session, symbol, tickers.get(symbol)))

        coins = await asyncio.gather(*tasks, return_exceptions=True)

    for coin in coins:
        if isinstance(coin, CoinData):
            results.append(analyze_coin(coin))
        elif isinstance(coin, Exception):
            logger.error(f"Coin fetch error: {coin}")

    # Сортируем: pump → dump → neutral, внутри по |score|
    results.sort(key=lambda c: (
        0 if c.signal == "pump" else 1 if c.signal == "dump" else 2,
        -abs(c.score)
    ))
    return results


async def _fetch_coin_data(
    session: aiohttp.ClientSession,
    symbol: str,
    ticker: Optional[dict]
) -> Optional[CoinData]:
    if not ticker:
        return None

    label = SYMBOL_LABELS.get(symbol, symbol.replace("USDT", ""))

    try:
        price = float(ticker["lastPrice"])
        price_change_24h = float(ticker["priceChangePercent"])
        volume_usdt = float(ticker["quoteVolume"])
        quote_volume = float(ticker["volume"])
        high_24h = float(ticker["highPrice"])
        low_24h = float(ticker["lowPrice"])
    except (KeyError, ValueError):
        return None

    # Объём: часовые свечи
    klines, oi_data, oi_hist, funding, lsr = await asyncio.gather(
        get_klines_1h(session, symbol),
        get_futures_oi(session, symbol),
        get_futures_oi_hist(session, symbol),
        get_funding_rate(session, symbol),
        get_long_short_ratio(session, symbol),
        return_exceptions=True
    )

    volume_change_pct = 0.0
    if isinstance(klines, list) and klines:
        volume_change_pct = compute_volume_change(klines)

    # 1h изменение цены из свечей
    price_change_1h = 0.0
    if isinstance(klines, list) and len(klines) >= 2:
        try:
            open_1h = float(klines[-2][1])
            close_1h = float(klines[-1][4])
            if open_1h > 0:
                price_change_1h = ((close_1h - open_1h) / open_1h) * 100
        except (IndexError, ValueError):
            pass

    # OI
    oi_usdt = None
    oi_change_pct = None
    if isinstance(oi_data, dict) and "openInterest" in oi_data:
        try:
            oi_usdt = float(oi_data["openInterest"]) * price
        except (ValueError, TypeError):
            pass

    if isinstance(oi_hist, list) and len(oi_hist) >= 2:
        try:
            oi_prev = float(oi_hist[-2]["sumOpenInterest"])
            oi_curr = float(oi_hist[-1]["sumOpenInterest"])
            if oi_prev > 0:
                oi_change_pct = ((oi_curr - oi_prev) / oi_prev) * 100
        except (IndexError, KeyError, ValueError):
            pass

    # Funding rate
    funding_rate = None
    if isinstance(funding, dict):
        try:
            funding_rate = float(funding.get("lastFundingRate", 0))
        except (ValueError, TypeError):
            pass

    # Long/Short
    long_short = None
    if isinstance(lsr, list) and lsr:
        try:
            long_short = float(lsr[0].get("longShortRatio", 1.0))
        except (IndexError, KeyError, ValueError):
            pass

    return CoinData(
        symbol=symbol,
        label=label,
        price=price,
        price_change_1h=price_change_1h,
        price_change_24h=price_change_24h,
        volume_usdt=volume_usdt,
        volume_change_pct=volume_change_pct,
        quote_volume=quote_volume,
        high_24h=high_24h,
        low_24h=low_24h,
        oi_usdt=oi_usdt,
        oi_change_pct=oi_change_pct,
        funding_rate=funding_rate,
        long_short_ratio=long_short,
    )
