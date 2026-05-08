import asyncio
import logging
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from services.accumulation import scan_accumulation, format_accumulation
from services.market import get_watchlist, scan_market

router = Router()
logger = logging.getLogger(__name__)

# Подписчики на авто-мониторинг накопления
_accum_subscribers: dict[int, asyncio.Task] = {}
ACCUM_INTERVAL = 30 * 60  # каждые 30 минут


async def _accum_loop(bot: Bot, chat_id: int):
    logger.info(f"Accumulation loop started for {chat_id}")
    while True:
        try:
            await asyncio.sleep(ACCUM_INTERVAL)
            watchlist = get_watchlist()
            if not watchlist:
                await scan_market()
                watchlist = get_watchlist()

            results = await scan_accumulation(watchlist)
            hot = [r for r in results if r.score >= 55]

            if not hot:
                continue

            await bot.send_message(
                chat_id,
                f"🐋 <b>Обнаружено накопление!</b>\n"
                f"Найдено монет: <b>{len(hot)}</b>\n"
                f"{'━'*26}",
                parse_mode="HTML"
            )

            for r in hot[:5]:
                await asyncio.sleep(0.5)
                await bot.send_message(chat_id, format_accumulation(r), parse_mode="HTML")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Accumulation loop error: {e}")
            await asyncio.sleep(60)


@router.message(Command("accum"))
async def cmd_accum(message: Message, bot: Bot):
    args = message.text.split()

    if len(args) >= 2 and args[1].lower() == "on":
        chat_id = message.chat.id
        if chat_id in _accum_subscribers:
            await message.answer("✅ Мониторинг накопления уже включён.")
            return
        task = asyncio.create_task(_accum_loop(bot, chat_id))
        _accum_subscribers[chat_id] = task
        await message.answer(
            "🐋 <b>Мониторинг накопления включён!</b>\n\n"
            "Буду присылать алерт каждые 30 минут когда обнаружу "
            "паттерн тихого накопления китов.\n\n"
            "Выключить: <code>/accum off</code>",
            parse_mode="HTML"
        )
        return

    if len(args) >= 2 and args[1].lower() == "off":
        chat_id = message.chat.id
        if chat_id not in _accum_subscribers:
            await message.answer("⚪️ Мониторинг не был включён.")
            return
        task = _accum_subscribers.pop(chat_id)
        task.cancel()
        await message.answer("🔕 Мониторинг накопления выключен.")
        return

    # Разовый скан
    wait = await message.answer(
        "🔍 Сканирую паттерны накопления китов...\n"
        "Анализирую объёмы, фитили свечей, OI, funding и волатильность.\n"
        "Это займёт ~20 секунд.",
        parse_mode="HTML"
    )

    watchlist = get_watchlist()
    if not watchlist:
        await scan_market()
        watchlist = get_watchlist()

    if not watchlist:
        await wait.edit_text("❌ Сначала запусти /scan")
        return

    try:
        results = await scan_accumulation(watchlist)
        hot = [r for r in results if r.score >= 30]

        if not hot:
            await wait.edit_text(
                "😴 Паттернов накопления не обнаружено.\n\n"
                "Включи авто-мониторинг: <code>/accum on</code>",
                parse_mode="HTML"
            )
            return

        strong = [r for r in hot if r.score >= 55]
        weak = [r for r in hot if r.score < 55]

        summary = (
            f"🐋 <b>Анализ накопления китов</b>\n"
            f"{'━'*26}\n"
            f"🚨 Сильное накопление: <b>{len(strong)}</b>\n"
            f"👀 Слабые признаки: <b>{len(weak)}</b>\n\n"
            f"⚠️ <i>Алгоритмический анализ — не сигналы к торговле.</i>"
        )
        await wait.edit_text(summary, parse_mode="HTML")

        for r in hot[:6]:
            await asyncio.sleep(0.4)
            await message.answer(format_accumulation(r), parse_mode="HTML")

    except Exception as e:
        logger.exception("Accum scan error")
        await wait.edit_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
