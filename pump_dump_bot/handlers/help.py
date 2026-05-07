from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from utils.formatter import format_help

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(format_help(), parse_mode="HTML")
