# 🚀 Pump/Dump Scanner Bot

Telegram-бот для анализа альткоинов Binance по объёмам, OI, денежным потокам и активности китов.

## Что анализирует

- **Объём** — аномальный рост vs среднее за 48 часов
- **OI (Open Interest)** — рост/падение открытого интереса на фьючерсах
- **Funding Rate** — перегрев фьючерсного рынка
- **Long/Short Ratio** — куда ставят крупные игроки
- **Позиция цены** — у хая или у лоя диапазона 24ч

## Команды

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/scan` | Полный скан всех монет |
| `/pump` | Только монеты в стадии накопления |
| `/dump` | Только перегретые монеты |
| `/coin XRP` | Анализ одной конкретной монеты |
| `/alerts on` | Авто-скан каждые 5 минут |
| `/alerts off` | Выключить авто-скан |
| `/help` | Справка |

---

## Деплой на Railway (бесплатно, 5 минут)

### 1. Получи новый токен бота

Зайди в [@BotFather](https://t.me/BotFather) → выбери своего бота → **Revoke token** → скопируй новый токен.

### 2. Загрузи код на GitHub

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/ТВОЙ_ЮЗЕР/pump-dump-bot.git
git push -u origin main
```

### 3. Деплой на Railway

1. Зайди на [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Выбери репозиторий
3. Зайди в **Variables** и добавь:
   ```
   BOT_TOKEN = твой_новый_токен
   SCAN_INTERVAL = 300
   ```
4. Railway сам задеплоит — бот запустится через ~1 минуту

---

## Локальный запуск (для теста)

```bash
# Установи зависимости
pip install -r requirements.txt

# Создай .env файл
cp .env.example .env
# Отредактируй .env — вставь токен

# Запусти
python bot.py
```

---

## Структура проекта

```
pump_dump_bot/
├── bot.py                  # Точка входа
├── config.py               # Конфиг из переменных окружения
├── requirements.txt
├── Procfile                # Для Railway
├── handlers/
│   ├── start.py            # /start, кнопки меню
│   ├── scanner.py          # /scan /pump /dump /coin
│   ├── alerts.py           # /alerts — авто-скан
│   └── help.py             # /help
├── services/
│   └── market.py           # Binance API — реальные данные
└── utils/
    └── formatter.py        # Форматирование сообщений TG
```

---

⚠️ **Дисклеймер**: Бот предоставляет аналитические данные, не торговые сигналы. DYOR.
