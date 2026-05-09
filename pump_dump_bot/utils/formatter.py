"""Форматирование сообщений для Telegram (HTML)"""
from datetime import datetime


def fmt_price(price: float, symbol: str) -> str:
    if "SHIB" in symbol:
        return f"${price:.8f}"
    if price < 0.01:
        return f"${price:.6f}"
    if price < 1:
        return f"${price:.4f}"
    if price < 100:
        return f"${price:.2f}"
    return f"${price:,.2f}"


def fmt_volume(vol: float) -> str:
    if vol >= 1_000_000_000:
        return f"${vol/1_000_000_000:.2f}B"
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    return f"${vol/1_000:.0f}K"


def fmt_pct(val: float, with_plus: bool = True) -> str:
    sign = "+" if val > 0 and with_plus else ""
    return f"{sign}{val:.2f}%"


def signal_emoji(signal: str) -> str:
    return {"pump": "🟢", "dump": "🔴", "neutral": "⚪️"}.get(signal, "⚪️")


def signal_label(signal: str) -> str:
    return {"pump": "НАКОПЛЕНИЕ", "dump": "ПЕРЕГРЕВ", "neutral": "НЕЙТРАЛЬНО"}.get(signal, "—")


def format_coin_card(c, short: bool = False) -> str:
    emoji = signal_emoji(c.signal)
    label = signal_label(c.signal)
    p_emoji_1h = "📈" if c.price_change_1h >= 0 else "📉"
    p_emoji_24h = "📈" if c.price_change_24h >= 0 else "📉"

    lines = [
        f"{'━'*28}",
        f"{emoji} <b>#{c.label}</b>  <i>{label}</i>",
        f"Цена: <code>{fmt_price(c.price, c.symbol)}</code>  "
        f"{p_emoji_1h} <b>{fmt_pct(c.price_change_1h)}</b> 1ч  "
        f"{p_emoji_24h} <b>{fmt_pct(c.price_change_24h)}</b> 24ч",
    ]

    if not short:
        vol_icon = "🔥" if c.volume_change_pct > 50 else ("📊" if c.volume_change_pct > 0 else "📉")
        lines.append(
            f"{vol_icon} Объём: {fmt_volume(c.volume_usdt)}  "
            f"(<code>{fmt_pct(c.volume_change_pct)}</code> vs норма)"
        )
        if c.oi_change_pct is not None:
            oi_icon = "🔺" if c.oi_change_pct > 0 else "🔻"
            oi_str = fmt_volume(c.oi_usdt) if c.oi_usdt else "—"
            lines.append(f"{oi_icon} OI: {oi_str}  (<code>{fmt_pct(c.oi_change_pct)}</code>)")
        if c.funding_rate is not None:
            fr_pct = c.funding_rate * 100
            fr_icon = "⚠️" if fr_pct > 0.04 else ("✅" if fr_pct < 0 else "➖")
            lines.append(f"{fr_icon} Funding: <code>{fr_pct:.4f}%</code>")
        if c.long_short_ratio is not None:
            lsr = c.long_short_ratio
            lsr_icon = "🐂" if lsr > 1.3 else ("🐻" if lsr < 0.8 else "⚖️")
            lines.append(f"{lsr_icon} Long/Short: <code>{lsr:.2f}</code>")
        if c.signals_list:
            lines.append("")
            for sig, stype in c.signals_list[:4]:
                lines.append(f"  • {sig}")
        lines.append("")
        lines.append(f"💬 <i>{c.analysis}</i>")

    return "\n".join(lines)


def format_scan_report(coins: list, filter_signal: str = "all") -> list[str]:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    if filter_signal == "all":
        filtered = coins
        header_emoji = "🔍"
    elif filter_signal == "pump":
        filtered = [c for c in coins if c.signal == "pump"]
        header_emoji = "🟢"
    elif filter_signal == "dump":
        filtered = [c for c in coins if c.signal == "dump"]
        header_emoji = "🔴"
    else:
        filtered = coins
        header_emoji = "🔍"

    pump_count = sum(1 for c in coins if c.signal == "pump")
    dump_count = sum(1 for c in coins if c.signal == "dump")
    neutral_count = sum(1 for c in coins if c.signal == "neutral")

    header = (
        f"{header_emoji} <b>Pump/Dump Scanner</b>\n"
        f"<i>Binance · Топ-30 динамический (без BTC/ETH/SOL)</i>\n"
        f"🕐 {now}\n\n"
        f"🟢 Накопление: <b>{pump_count}</b>  "
        f"🔴 Перегрев: <b>{dump_count}</b>  "
        f"⚪️ Нейтрально: <b>{neutral_count}</b>\n"
        f"{'━'*28}\n"
        f"⚠️ <i>Это не торговые сигналы — только анализ данных.</i>"
    )

    if not filtered:
        return [header + "\n\nМонет по фильтру не найдено."]

    messages = [header]
    current_msg = ""
    for coin in filtered:
        card = format_coin_card(coin, short=False)
        if len(current_msg) + len(card) > 3800:
            messages.append(current_msg)
            current_msg = card
        else:
            current_msg += ("\n" if current_msg else "") + card
    if current_msg:
        messages.append(current_msg)
    return messages


def format_single_coin(c) -> str:
    return format_coin_card(c, short=False)


def format_help() -> str:
    return (
        "📊 <b>Pump/Dump Scanner Bot v3</b>\n\n"
        "<b>📡 Основной скан (Binance):</b>\n"
        "/scan — полный скан топ-30 монет\n"
        "/pump — только накопление 🟢\n"
        "/dump — только перегрев 🔴\n"
        "/coin XRP — анализ одной монеты\n"
        "/alerts on/off — авто-скан каждые 5 минут\n\n"
        "<b>🐋 Киты на Binance ($100k+):</b>\n"
        "/whales — разовый скан крупных сделок\n"
        "/whales on/off — авто-мониторинг\n\n"
        "<b>⚡️ On-chain DEX мониторинг:</b>\n"
        "/onchain — крупные сделки на Uniswap+PancakeSwap\n"
        "/onchain on/off — авто-мониторинг каждые 3 минуты\n\n"
        "<b>🔍 Накопление китов:</b>\n"
        "/accum — паттерны тихого накопления\n"
        "/accum on/off — авто-мониторинг каждые 30 минут\n\n"
        "<b>📊 Мультитаймфрейм (15м/1ч/4ч/1д):</b>\n"
        "/mtf XRP — анализ монеты на всех TF\n"
        "/mtf top — топ монет по совпадению TF\n\n"
        "/help — это сообщение\n\n"
        "⚠️ <i>Не торговые сигналы. DYOR.</i>"
    )
