import asyncio
import logging
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from services.market import scan_market
from utils.formatter import format_scan_report
from config import config

router = Router()
logger = logging.getLogger(__name__)

# Хранилище подписчиков: {chat_id: asyncio.Task}
_subscribers: dict[int, asyncio.Task] = {}


async def _alert_loop(bot: Bot, chat_id: int, interval: int):
    """Фоновый цикл авто-скана для одного пользователя"""
    logger.info(f"Alert loop started for {chat_id}")
    while True:
        try:
            await asyncio.sleep(interval)
            coins = await scan_market()

            # Отправляем только если есть pump или dump
            hot = [c for c in coins if c.signal in ("pump", "dump")]
            if not hot:
                continue

            msgs = format_scan_report(coins, filter_signal="all")
            for m in msgs:
                await bot.send_message(chat_id, m, parse_mode="HTML")

        except asyncio.CancelledError:
            logger.info(f"Alert loop cancelled for {chat_id}")
            break
        except Exception as e:
            logger.error(f"Alert loop error for {chat_id}: {e}")
            await asyncio.sleep(60)  # пауза при ошибке


@router.message(Command("alerts"))
async def cmd_alerts(message: Message, bot: Bot):
    args = message.text.split()
    chat_id = message.chat.id

    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        await message.answer(
            "Использование:\n"
            "<code>/alerts on</code> — включить авто-скан\n"
            "<code>/alerts off</code> — выключить",
            parse_mode="HTML"
        )
        return

    action = args[1].lower()

    if action == "on":
        if chat_id in _subscribers:
            await message.answer(
                f"✅ Авто-скан уже включён. Интервал: каждые {config.SCAN_INTERVAL // 60} минут."
            )
            return

        task = asyncio.create_task(_alert_loop(bot, chat_id, config.SCAN_INTERVAL))
        _subscribers[chat_id] = task

        await message.answer(
            f"🔔 <b>Авто-скан включён!</b>\n\n"
            f"Буду присылать анализ каждые <b>{config.SCAN_INTERVAL // 60} минут</b> "
            f"при наличии интересных монет.\n\n"
            f"Выключить: /alerts off",
            parse_mode="HTML"
        )

    elif action == "off":
        if chat_id not in _subscribers:
            await message.answer("⚪️ Авто-скан не был включён.")
            return

        task = _subscribers.pop(chat_id)
        task.cancel()

        await message.answer("🔕 Авто-скан выключен.")
