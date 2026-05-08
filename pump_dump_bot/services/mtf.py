"""
Мультитаймфреймный анализ — 15м, 1ч, 4ч, 1д.
Совпадение сигналов на нескольких таймфреймах = более сильный сигнал.
"""
import asyncio
import aiohttp
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BASE_URL = "https://api.binance.com/api/v3"

TIMEFRAMES = {
    "15m": {"interval": "15m", "limit": 48, "label": "15 минут"},
    "1h":  {"interval": "1h",  "limit": 48, "label": "1 час"},
    "4h":  {"interval": "4h",  "limit": 48, "label": "4 часа"},
    "1d":  {"interval": "1d",  "limit": 14, "label": "1 день"},
}


@dataclass
class TFSignal:
    timeframe: str
    label: str
    signal: str        # bull / bear / neutral
    volume_change: float
    price_change: float
    rsi: float
    trend: str         # up / down / sideways


@dataclass
class MTFResult:
    symbol: str
    label: str
    signals: list      # список TFSignal
    confluence: str    # strong_bull / bull / neutral / bear / strong_bear
    confluence_score: int
    description: str


def compute_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze_klines(klines: list, tf: str) -> TFSignal:
    if not klines or len(klines) < 3:
        return TFSignal(tf, TIMEFRAMES[tf]["label"], "neutral", 0, 0, 50, "sideways")

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]

    # Изменение цены
    price_change = ((closes[-1] - closes[-2]) / closes[-2]) * 100 if closes[-2] > 0 else 0

    # Изменение объёма vs среднее
    recent_vol = volumes[-1]
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else recent_vol
    vol_change = ((recent_vol - avg_vol) / avg_vol) * 100 if avg_vol > 0 else 0

    # RSI
    rsi = compute_rsi(closes)

    # Тренд — сравниваем последние 5 свечей
    last5 = closes[-5:]
    if last5[-1] > last5[0] * 1.01:
        trend = "up"
    elif last5[-1] < last5[0] * 0.99:
        trend = "down"
    else:
        trend = "sideways"

    # Сигнал
    score = 0
    if rsi < 35:
        score += 2
    elif rsi < 45:
        score += 1
    elif rsi > 70:
        score -= 2
    elif rsi > 60:
        score -= 1

    if vol_change > 50:
        score += 1
    if vol_change > 100:
        score += 1

    if trend == "up":
        score += 1
    elif trend == "down":
        score -= 1

    if price_change > 2:
        score += 1
    elif price_change < -2:
        score -= 1

    if score >= 2:
        signal = "bull"
    elif score <= -2:
        signal = "bear"
    else:
        signal = "neutral"

    return TFSignal(
        timeframe=tf,
        label=TIMEFRAMES[tf]["label"],
        signal=signal,
        volume_change=vol_change,
        price_change=price_change,
        rsi=rsi,
        trend=trend,
    )


async def fetch_klines(session: aiohttp.ClientSession, symbol: str, interval: str, limit: int):
    try:
        async with session.get(
            f"{BASE_URL}/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"Klines error {symbol} {interval}: {e}")
    return None


async def analyze_mtf(symbol: str, label: str) -> MTFResult:
    """Анализ монеты на всех таймфреймах"""
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_klines(session, symbol, cfg["interval"], cfg["limit"])
            for cfg in TIMEFRAMES.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    tf_signals = []
    for i, (tf, cfg) in enumerate(TIMEFRAMES.items()):
        klines = results[i] if not isinstance(results[i], Exception) else None
        sig = analyze_klines(klines or [], tf)
        tf_signals.append(sig)

    # Считаем confluence
    bull_count = sum(1 for s in tf_signals if s.signal == "bull")
    bear_count = sum(1 for s in tf_signals if s.signal == "bear")
    score = bull_count - bear_count

    if score >= 3:
        confluence = "strong_bull"
        desc = "Сильный бычий сигнал на большинстве таймфреймов — монета интересна для лонга."
    elif score == 2:
        confluence = "bull"
        desc = "Преимущественно бычья картина — стоит присмотреться."
    elif score <= -3:
        confluence = "strong_bear"
        desc = "Сильный медвежий сигнал — монета перегрета или в даунтренде."
    elif score == -2:
        confluence = "bear"
        desc = "Преимущественно медвежья картина — осторожно с лонгами."
    else:
        confluence = "neutral"
        desc = "Смешанные сигналы — нет чёткого направления."

    return MTFResult(
        symbol=symbol,
        label=label,
        signals=tf_signals,
        confluence=confluence,
        confluence_score=score,
        description=desc,
    )


def format_mtf_result(mtf: MTFResult) -> str:
    emoji_map = {
        "strong_bull": "🚀 СИЛЬНЫЙ БЫЧИЙ",
        "bull": "🟢 БЫЧИЙ",
        "neutral": "⚪️ НЕЙТРАЛЬНЫЙ",
        "bear": "🔴 МЕДВЕЖИЙ",
        "strong_bear": "💀 СИЛЬНЫЙ МЕДВЕЖИЙ",
    }

    sig_emoji = {"bull": "🟢", "bear": "🔴", "neutral": "⚪️"}
    trend_emoji = {"up": "↗️", "down": "↘️", "sideways": "➡️"}

    lines = [
        f"📊 <b>Мультитаймфрейм — #{mtf.label}</b>",
        f"{'━'*26}",
        f"Итог: <b>{emoji_map.get(mtf.confluence, '—')}</b>",
        "",
    ]

    for s in mtf.signals:
        rsi_warn = " ⚠️" if s.rsi > 70 else (" 💡" if s.rsi < 35 else "")
        lines.append(
            f"{sig_emoji[s.signal]} <b>{s.label}</b> {trend_emoji[s.trend]}\n"
            f"   RSI: <code>{s.rsi:.1f}</code>{rsi_warn}  "
            f"Объём: <code>{s.volume_change:+.0f}%</code>  "
            f"Цена: <code>{s.price_change:+.2f}%</code>"
        )

    lines.append("")
    lines.append(f"💬 <i>{mtf.description}</i>")
    lines.append("")
    lines.append("⚠️ <i>Не торговый сигнал — только анализ данных.</i>")

    return "\n".join(lines)
