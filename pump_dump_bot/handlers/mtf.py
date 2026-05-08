import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from services.mtf import analyze_mtf, format_mtf_result
from services.market import get_watchlist, get_label, scan_market

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("mtf"))
async def cmd_mtf(message: Message):
    args = message.text.split()

    if len(args) < 2:
        await message.answer(
            "Укажи символ монеты.\n"
            "Пример: <code>/mtf XRP</code>\n\n"
            "Или <code>/mtf top</code> — топ-5 по confluence",
            parse_mode="HTML"
        )
        return

    arg = args[1].upper().strip()

    if arg == "TOP":
        # Анализируем все монеты и показываем топ по confluence
        wait = await message.answer("⏳ Анализирую все таймфреймы для топ-30 монет...\nЭто займёт ~30 секунд.", parse_mode="HTML")
        watchlist = get_watchlist()
        if not watchlist:
            await wait.edit_text("❌ Сначала запусти /scan чтобы загрузить вотчлист.")
            return

        import asyncio
        tasks = [analyze_mtf(sym, get_label(sym)) for sym in watchlist[:15]]  # первые 15 для скорости
        results = await asyncio.gather(*tasks, return_exceptions=True)

        bull = [r for r in results if isinstance(r, object) and hasattr(r, 'confluence') and r.confluence in ("strong_bull", "bull")]
        bear = [r for r in results if isinstance(r, object) and hasattr(r, 'confluence') and r.confluence in ("strong_bear", "bear")]

        bull.sort(key=lambda r: r.confluence_score, reverse=True)
        bear.sort(key=lambda r: r.confluence_score)

        lines = ["📊 <b>MTF Топ — лучшие совпадения</b>\n" + "━"*26]

        if bull:
            lines.append("\n🟢 <b>Бычьи совпадения:</b>")
            for r in bull[:3]:
                score_str = "🚀" * min(r.confluence_score, 3)
                lines.append(f"  #{r.label} {score_str} ({r.confluence_score}/4 TF)")

        if bear:
            lines.append("\n🔴 <b>Медвежьи совпадения:</b>")
            for r in bear[:3]:
                score_str = "💀" * min(abs(r.confluence_score), 3)
                lines.append(f"  #{r.label} {score_str} ({abs(r.confluence_score)}/4 TF)")

        lines.append("\n<i>Для детального анализа: /mtf XRP</i>")
        await wait.edit_text("\n".join(lines), parse_mode="HTML")
        return

    # Анализ конкретной монеты
    symbol = arg if arg.endswith("USDT") else arg + "USDT"
    watchlist = get_watchlist()

    if not watchlist:
        # Если вотчлист не загружен — грузим
        await scan_market()
        watchlist = get_watchlist()

    label = get_label(symbol) if symbol in watchlist else arg

    wait = await message.answer(
        f"⏳ Анализирую <b>#{label}</b> на 4 таймфреймах (15м, 1ч, 4ч, 1д)...",
        parse_mode="HTML"
    )

    try:
        result = await analyze_mtf(symbol, label)
        text = format_mtf_result(result)
        await wait.edit_text(text, parse_mode="HTML")
    except Exception as e:
        logger.exception("MTF error")
        await wait.edit_text(f"❌ Ошибка анализа: <code>{e}</code>", parse_mode="HTML")
