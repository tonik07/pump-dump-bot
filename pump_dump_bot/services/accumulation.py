"""
Детектор паттерна тихого накопления китов.
Анализирует поведение цены и объёма для выявления накопления
до начала роста — без платных API.
"""
import asyncio
import aiohttp
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com/api/v3"
FAPI_URL = "https://fapi.binance.com/fapi/v1"


@dataclass
class AccumulationResult:
    symbol: str
    label: str
    score: int                    # 0-100 — вероятность накопления
    signals: list = field(default_factory=list)
    price: float = 0.0
    price_change_24h: float = 0.0
    volume_usdt: float = 0.0
    description: str = ""
    phase: str = "unknown"        # accumulation / distribution / neutral


async def fetch(session, url, params=None):
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"Fetch error {url}: {e}")
    return None


def analyze_accumulation(klines_1h: list, klines_15m: list, oi_hist: list, funding: dict, ticker: dict) -> dict:
    """
    Анализируем паттерн накопления по нескольким факторам.
    Возвращает score 0-100 и список сигналов.
    """
    score = 0
    signals = []

    if not klines_1h or len(klines_1h) < 24:
        return {"score": 0, "signals": [], "phase": "unknown"}

    # --- ФАКТОР 1: Боковик при растущем объёме ---
    # Цена не движется, но объём растёт = тихая скупка
    closes_1h = [float(k[4]) for k in klines_1h[-24:]]
    volumes_1h = [float(k[5]) for k in klines_1h[-24:]]

    price_range = (max(closes_1h) - min(closes_1h)) / closes_1h[0] * 100
    vol_recent = sum(volumes_1h[-6:]) / 6
    vol_prev = sum(volumes_1h[-24:-6]) / 18 if len(volumes_1h) >= 24 else vol_recent
    vol_growth = ((vol_recent - vol_prev) / vol_prev * 100) if vol_prev > 0 else 0

    if price_range < 3 and vol_growth > 30:
        score += 25
        signals.append(("🔕 Боковик + объём растёт — тихая скупка", "strong"))
    elif price_range < 5 and vol_growth > 20:
        score += 15
        signals.append(("📊 Слабый боковик при повышенном объёме", "medium"))

    # --- ФАКТОР 2: Длинные нижние тени (покупки на снижениях) ---
    # Свечи с длинным нижним фитилём = кто-то выкупает каждый провал
    long_wicks = 0
    for k in klines_1h[-12:]:
        open_p = float(k[1])
        high_p = float(k[2])
        low_p = float(k[3])
        close_p = float(k[4])
        body = abs(close_p - open_p)
        lower_wick = min(open_p, close_p) - low_p
        candle_range = high_p - low_p if high_p != low_p else 0.001
        if candle_range > 0 and lower_wick / candle_range > 0.4 and lower_wick > body:
            long_wicks += 1

    if long_wicks >= 5:
        score += 20
        signals.append((f"🪝 {long_wicks} свечей с длинным нижним фитилём — выкупают просадки", "strong"))
    elif long_wicks >= 3:
        score += 10
        signals.append((f"🪝 {long_wicks} свечи с выкупом просадок", "medium"))

    # --- ФАКТОР 3: Постепенный рост OI при боковике ---
    if oi_hist and len(oi_hist) >= 4:
        try:
            oi_values = [float(x["sumOpenInterest"]) for x in oi_hist[-6:]]
            oi_trend = (oi_values[-1] - oi_values[0]) / oi_values[0] * 100 if oi_values[0] > 0 else 0
            if oi_trend > 5 and price_range < 5:
                score += 20
                signals.append((f"📈 OI растёт +{oi_trend:.1f}% при боковике — позиции набираются", "strong"))
            elif oi_trend > 2:
                score += 10
                signals.append((f"📈 OI постепенно растёт +{oi_trend:.1f}%", "medium"))
        except (IndexError, KeyError, ValueError, ZeroDivisionError):
            pass

    # --- ФАКТОР 4: Отрицательный funding (умные деньги в лонге) ---
    if funding and isinstance(funding, dict):
        try:
            fr = float(funding.get("lastFundingRate", 0)) * 100
            if fr < -0.02:
                score += 15
                signals.append((f"💡 Funding отрицательный {fr:.4f}% — шорты финансируют лонги", "strong"))
            elif fr < 0:
                score += 8
                signals.append((f"💡 Funding слегка отрицательный {fr:.4f}%", "medium"))
            elif fr > 0.05:
                score -= 10
                signals.append((f"⚠️ Funding перегрет {fr:.4f}% — не накопление", "negative"))
        except (ValueError, TypeError):
            pass

    # --- ФАКТОР 5: Сжатие волатильности (Squeeze) ---
    # Bollinger Bands сужаются = монета готовится к движению
    if len(closes_1h) >= 20:
        sma20 = sum(closes_1h[-20:]) / 20
        std20 = (sum((c - sma20) ** 2 for c in closes_1h[-20:]) / 20) ** 0.5
        bb_width = (std20 * 2) / sma20 * 100 if sma20 > 0 else 0

        # Сравниваем с прошлым периодом
        if len(closes_1h) >= 48:
            sma20_prev = sum(closes_1h[-48:-28]) / 20
            std20_prev = (sum((c - sma20_prev) ** 2 for c in closes_1h[-48:-28]) / 20) ** 0.5
            bb_width_prev = (std20_prev * 2) / sma20_prev * 100 if sma20_prev > 0 else bb_width

            if bb_width < bb_width_prev * 0.6:
                score += 15
                signals.append(("🗜 Сильное сжатие волатильности (Squeeze) — готовится движение", "strong"))
            elif bb_width < bb_width_prev * 0.75:
                score += 8
                signals.append(("🗜 Волатильность сжимается", "medium"))

    # --- ФАКТОР 6: 15м свечи — нарастающий объём без роста цены ---
    if klines_15m and len(klines_15m) >= 8:
        vols_15m = [float(k[5]) for k in klines_15m[-8:]]
        closes_15m = [float(k[4]) for k in klines_15m[-8:]]
        vol_increasing = sum(1 for i in range(1, len(vols_15m)) if vols_15m[i] > vols_15m[i-1])
        price_flat = abs(closes_15m[-1] - closes_15m[0]) / closes_15m[0] * 100 < 1
        if vol_increasing >= 5 and price_flat:
            score += 10
            signals.append(("⏱ На 15м объём нарастает без движения цены", "medium"))

    # Определяем фазу
    if score >= 55:
        phase = "accumulation"
    elif score >= 30:
        phase = "possible_accumulation"
    else:
        phase = "neutral"

    return {"score": min(score, 100), "signals": signals, "phase": phase}


async def scan_accumulation(watchlist: list) -> list[AccumulationResult]:
    """Сканируем все монеты на паттерн накопления"""
    results = []

    async with aiohttp.ClientSession() as session:
        tasks = [_analyze_coin(session, sym) for sym in watchlist]
        coins = await asyncio.gather(*tasks, return_exceptions=True)

    for coin in coins:
        if isinstance(coin, AccumulationResult):
            results.append(coin)

    # Сортируем по score
    results.sort(key=lambda x: x.score, reverse=True)
    return results


async def _analyze_coin(session, symbol: str) -> AccumulationResult:
    label = symbol.replace("USDT", "")

    klines_1h, klines_15m, oi_hist, funding, ticker = await asyncio.gather(
        fetch(session, f"{BASE_URL}/klines", {"symbol": symbol, "interval": "1h", "limit": 48}),
        fetch(session, f"{BASE_URL}/klines", {"symbol": symbol, "interval": "15m", "limit": 16}),
        fetch(session, f"{FAPI_URL}/openInterestHist", {"symbol": symbol, "period": "1h", "limit": 6}),
        fetch(session, f"{FAPI_URL}/premiumIndex", {"symbol": symbol}),
        fetch(session, f"{BASE_URL}/ticker/24hr", {"symbol": symbol}),
        return_exceptions=True
    )

    # Безопасно получаем данные
    klines_1h = klines_1h if isinstance(klines_1h, list) else []
    klines_15m = klines_15m if isinstance(klines_15m, list) else []
    oi_hist = oi_hist if isinstance(oi_hist, list) else []
    funding = funding if isinstance(funding, dict) else {}
    ticker = ticker if isinstance(ticker, dict) else {}

    price = float(ticker.get("lastPrice", 0))
    price_change_24h = float(ticker.get("priceChangePercent", 0))
    volume_usdt = float(ticker.get("quoteVolume", 0))

    analysis = analyze_accumulation(klines_1h, klines_15m, oi_hist, funding, ticker)
    score = analysis["score"]
    signals = analysis["signals"]
    phase = analysis["phase"]

    # Описание
    if phase == "accumulation":
        strong = [s[0] for s in signals if s[1] == "strong"]
        description = f"Высокая вероятность накопления. {'. '.join(strong[:2])}."
    elif phase == "possible_accumulation":
        description = "Слабые признаки накопления — наблюдаем."
    else:
        description = "Паттерн накопления не обнаружен."

    return AccumulationResult(
        symbol=symbol,
        label=label,
        score=score,
        signals=signals,
        price=price,
        price_change_24h=price_change_24h,
        volume_usdt=volume_usdt,
        description=description,
        phase=phase,
    )


def format_accumulation(r: AccumulationResult) -> str:
    if r.score >= 55:
        phase_str = "🐋 НАКОПЛЕНИЕ КИТОВ"
        phase_emoji = "🚨"
    elif r.score >= 30:
        phase_str = "👀 ВОЗМОЖНОЕ НАКОПЛЕНИЕ"
        phase_emoji = "⚠️"
    else:
        phase_str = "😴 НЕЙТРАЛЬНО"
        phase_emoji = "⚪️"

    # Score bar
    filled = int(r.score / 10)
    bar = "█" * filled + "░" * (10 - filled)

    price = r.price
    if price < 0.01:
        price_str = f"${price:.6f}"
    elif price < 1:
        price_str = f"${price:.4f}"
    else:
        price_str = f"${price:.2f}"

    vol_str = f"${r.volume_usdt/1_000_000:.1f}M" if r.volume_usdt >= 1_000_000 else f"${r.volume_usdt/1_000:.0f}K"
    p_emoji = "📈" if r.price_change_24h >= 0 else "📉"

    lines = [
        f"{phase_emoji} <b>#{r.label}</b> — {phase_str}",
        f"{'━'*26}",
        f"Вероятность накопления: <b>{r.score}%</b>",
        f"<code>[{bar}]</code>",
        f"",
        f"Цена: <code>{price_str}</code>  {p_emoji} {r.price_change_24h:+.2f}% 24ч",
        f"Объём: {vol_str}",
        f"",
    ]

    for sig, strength in r.signals[:5]:
        lines.append(f"  • {sig}")

    lines.append("")
    lines.append(f"💬 <i>{r.description}</i>")
    lines.append("")
    lines.append("⚠️ <i>Алгоритмический анализ — не торговый сигнал.</i>")

    return "\n".join(lines)
