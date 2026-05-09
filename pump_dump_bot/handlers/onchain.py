import asyncio
import logging
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from services.onchain import scan_dex_trades, format_dex_trade

router = Router()
logger = logging.getLogger(__name__)

# Подписчики на авто-мониторинг
_onchain_subscribers: dict[int, asyncio.Task] = {}
ONCHAIN_INTERVAL = 3 * 60  # каждые 3 минуты


async def _onchain_loop(bot: Bot, chat_id: int):
    logger.info(f"Onchain loop started for {chat_id}")
    while True:
        try:
            await asyncio.sleep(ONCHAIN_INTERVAL)
            trades = await scan_dex_trades()

            if not trades:
                continue

            # Отправляем топ сделки
            for trade in trades[:5]:
                text = format_dex_trade(trade)
                await bot.send_message(
                    chat_id, text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Onchain loop error: {e}")
            await asyncio.sleep(60)


@router.message(Command("onchain"))
async def cmd_onchain(message: Message, bot: Bot):
    args = message.text.split()

    if len(args) >= 2 and args[1].lower() == "on":
        chat_id = message.chat.id
        if chat_id in _onchain_subscribers:
            await message.answer("✅ Мониторинг DEX уже включён.")
            return
        task = asyncio.create_task(_onchain_loop(bot, chat_id))
        _onchain_subscribers[chat_id] = task
        await message.answer(
            "⚡️ <b>DEX мониторинг включён!</b>\n\n"
            "Буду присылать алерт каждые 3 минуты когда кит "
            "совершает сделку <b>$100k+</b> на:\n"
            "• Uniswap V3 (Ethereum)\n"
            "• PancakeSwap (BNB Chain)\n\n"
            "Крупные DEX покупки часто предшествуют "
            "памп на Binance на <b>30-60 минут</b>.\n\n"
            "Выключить: <code>/onchain off</code>",
            parse_mode="HTML"
        )
        return

    if len(args) >= 2 and args[1].lower() == "off":
        chat_id = message.chat.id
        if chat_id not in _onchain_subscribers:
            await message.answer("⚪️ Мониторинг DEX не был включён.")
            return
        task = _onchain_subscribers.pop(chat_id)
        task.cancel()
        await message.answer("🔕 DEX мониторинг выключен.")
        return

    # Разовый скан
    wait = await message.answer(
        "🔍 Сканирую крупные DEX сделки...\n"
        "Uniswap V3 (ETH) + PancakeSwap (BSC)\n"
        "Минимум: $100,000",
        parse_mode="HTML"
    )

    try:
        trades = await scan_dex_trades()

        if not trades:
            await wait.edit_text(
                "😴 Крупных DEX сделок ($100k+) не найдено за последние минуты.\n\n"
                "Включи авто-мониторинг: <code>/onchain on</code>",
                parse_mode="HTML"
            )
            return

        buys = [t for t in trades if t.side == "BUY"]
        sells = [t for t in trades if t.side == "SELL"]

        await wait.edit_text(
            f"⚡️ <b>DEX крупные сделки</b>\n"
            f"{'━'*26}\n"
            f"🟢 Покупки: <b>{len(buys)}</b>\n"
            f"🔴 Продажи: <b>{len(sells)}</b>\n\n"
            f"⚠️ <i>Не торговые сигналы. DYOR.</i>",
            parse_mode="HTML"
        )

        for trade in trades[:8]:
            await asyncio.sleep(0.4)
            await message.answer(
                format_dex_trade(trade),
                parse_mode="HTML",
                disable_web_page_preview=True
            )

    except Exception as e:
        logger.exception("Onchain scan error")
        await wait.edit_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
