from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from utils.formatter import format_help

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Полный скан", callback_data="scan_all"),
            InlineKeyboardButton(text="🟢 Накопление", callback_data="scan_pump"),
        ],
        [
            InlineKeyboardButton(text="🔴 Перегрев", callback_data="scan_dump"),
            InlineKeyboardButton(text="📖 Помощь", callback_data="help"),
        ],
    ])

    await message.answer(
        "👋 <b>Pump/Dump Scanner</b>\n\n"
        "Анализирую топ-20 шиткоинов Binance по объёмам, "
        "OI, денежным потокам и активности китов.\n\n"
        "Выбери действие или используй команды:",
        reply_markup=kb,
        parse_mode="HTML"
    )


from aiogram.types import CallbackQuery
from aiogram import F


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await cb.message.edit_text(format_help(), parse_mode="HTML")
    await cb.answer()
