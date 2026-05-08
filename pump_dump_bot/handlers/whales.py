import asyncio
import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from services.whales import scan_whales, format_whale_alert
from services.market import get_watchlist

router = Router()
logger = logging.getLogger(__name__)

# Подписчики на whale алерты: {chat_id: asyncio.Task}
_whale_subscribers: dict[int, asyncio.Task] = {}
WHALE_SCAN_INTERVAL = 60  # каждую минуту


async def _whale_loop(bot: Bot, chat_id: int, min_usdt: float = 100_000):
    logger.info(f"Whale loop started for {chat_id}")
    while True:
        try:
            await asyncio.sleep(WHALE_SCAN_INTERVAL)
            watchlist = get_watchlist()
            if not watchlist:
                continue

            whales = await scan_whales(watchlist, min_usdt=min_usdt)
            for w in whales[:5]:  # максимум 5 алертов за раз
                text = format_whale_alert(w)
                await bot.send_message(chat_id, text, parse_mode="HTML")
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info(f"Whale loop cancelled for {chat_id}")
            break
        except Exception as e:
            logger.error(f"Whale loop error: {e}")
            await asyncio.sleep(60)


@router.message(Command("whales"))
async def cmd_whales(message: Message, bot: Bot):
    args = message.text.split()

    if len(args) < 2:
        # Разовый скан
        wait = await message.answer("🔍 Сканирую крупные сделки за последнюю минуту...", parse_mode="HTML")
        watchlist = get_watchlist()
        if not watchlist:
            await wait.edit_text("❌ Вотчлист пустой — сначала запусти /scan")
            return

        whales = await scan_whales(watchlist)
        if not whales:
            await wait.edit_text(
                "🐬 Крупных сделок ($100k+) за последнюю минуту не обнаружено.\n\n"
                "Попробуй через несколько минут или включи авто-мониторинг:\n"
                "<code>/whales on</code>",
                parse_mode="HTML"
            )
            return

        await wait.edit_text(
            f"🐋 <b>Найдено {len(whales)} китовых сделок</b>\n"
            f"За последнюю минуту · $100k+\n"
            f"{'━'*26}",
            parse_mode="HTML"
        )

        for w in whales[:8]:
            await asyncio.sleep(0.3)
            await message.answer(format_whale_alert(w), parse_mode="HTML")
        return

    action = args[1].lower()
    chat_id = message.chat.id

    if action == "on":
        if chat_id in _whale_subscribers:
            await message.answer("✅ Мониторинг китов уже включён.")
            return
        task = asyncio.create_task(_whale_loop(bot, chat_id))
        _whale_subscribers[chat_id] = task
        await message.answer(
            "🐋 <b>Мониторинг китов включён!</b>\n\n"
            "Буду присылать алерт когда появится сделка <b>$100k+</b> "
            "по любой монете из топ-30.\n\n"
            "Выключить: <code>/whales off</code>",
            parse_mode="HTML"
        )

    elif action == "off":
        if chat_id not in _whale_subscribers:
            await message.answer("⚪️ Мониторинг китов не был включён.")
            return
        task = _whale_subscribers.pop(chat_id)
        task.cancel()
        await message.answer("🔕 Мониторинг китов выключен.")

    else:
        await message.answer(
            "Использование:\n"
            "<code>/whales</code> — разовый скан\n"
            "<code>/whales on</code> — авто-мониторинг\n"
            "<code>/whales off</code> — выключить",
            parse_mode="HTML"
        )
