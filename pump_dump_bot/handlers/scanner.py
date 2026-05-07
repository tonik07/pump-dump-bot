import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from services.market import scan_market, SYMBOL_LABELS
from utils.formatter import format_scan_report, format_single_coin

router = Router()
logger = logging.getLogger(__name__)

# Кнопки после скана
def scan_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Накопление", callback_data="scan_pump"),
            InlineKeyboardButton(text="🔴 Перегрев", callback_data="scan_dump"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="scan_all"),
        ]
    ])


async def do_scan(send_func, filter_signal: str = "all"):
    """Универсальная функция скана — принимает функцию отправки"""
    msg = await send_func("⏳ Сканирую рынок, загружаю данные с Binance...", parse_mode="HTML")
    
    try:
        coins = await scan_market()
        messages = format_scan_report(coins, filter_signal=filter_signal)
        
        # Редактируем первое сообщение
        await msg.edit_text(messages[0], parse_mode="HTML", reply_markup=scan_kb())
        
        # Остальные отправляем следом
        for extra_msg in messages[1:]:
            await asyncio.sleep(0.3)
            await msg.answer(extra_msg, parse_mode="HTML")

    except Exception as e:
        logger.exception("Scan error")
        await msg.edit_text(
            f"❌ Ошибка при получении данных: <code>{e}</code>",
            parse_mode="HTML"
        )


@router.message(Command("scan"))
async def cmd_scan(message: Message):
    await do_scan(message.answer)


@router.message(Command("pump"))
async def cmd_pump(message: Message):
    await do_scan(message.answer, filter_signal="pump")


@router.message(Command("dump"))
async def cmd_dump(message: Message):
    await do_scan(message.answer, filter_signal="dump")


@router.message(Command("coin"))
async def cmd_coin(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "Укажи символ монеты. Пример: <code>/coin XRP</code>",
            parse_mode="HTML"
        )
        return

    ticker = args[1].upper().strip()
    symbol = ticker if ticker.endswith("USDT") else ticker + "USDT"

    if symbol not in SYMBOL_LABELS:
        available = ", ".join(SYMBOL_LABELS.values())
        await message.answer(
            f"❌ <b>{ticker}</b> не в списке.\n\nДоступные: {available}",
            parse_mode="HTML"
        )
        return

    wait = await message.answer(f"⏳ Загружаю данные по <b>{ticker}</b>...", parse_mode="HTML")

    try:
        coins = await scan_market()
        coin = next((c for c in coins if c.symbol == symbol), None)
        if coin:
            text = format_single_coin(coin)
            await wait.edit_text(text, parse_mode="HTML")
        else:
            await wait.edit_text("❌ Данные не получены. Попробуй позже.")
    except Exception as e:
        logger.exception("Coin fetch error")
        await wait.edit_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")


# Callback обработчики для инлайн кнопок
@router.callback_query(F.data == "scan_all")
async def cb_scan_all(cb: CallbackQuery):
    await cb.answer("Запускаю скан...")
    await cb.message.delete()
    await do_scan(cb.message.answer, filter_signal="all")


@router.callback_query(F.data == "scan_pump")
async def cb_scan_pump(cb: CallbackQuery):
    await cb.answer("Ищу накопление...")
    await cb.message.delete()
    await do_scan(cb.message.answer, filter_signal="pump")


@router.callback_query(F.data == "scan_dump")
async def cb_scan_dump(cb: CallbackQuery):
    await cb.answer("Ищу перегрев...")
    await cb.message.delete()
    await do_scan(cb.message.answer, filter_signal="dump")
