import os
from dataclasses import dataclass


@dataclass
class Config:
    BOT_TOKEN: str
    SCAN_INTERVAL: int = 300  # секунды между авто-сканами (5 минут)


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN не задан в переменных окружения")
    return Config(
        BOT_TOKEN=token,
        SCAN_INTERVAL=int(os.getenv("SCAN_INTERVAL", "300")),
    )


config = load_config()
