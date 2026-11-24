import asyncio
import glob
import hashlib
import html
import logging
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow"])
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, ErrorEvent, FSInputFile,
    InputMediaPhoto, InputMediaDocument,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault, TelegramObject
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= НАСТРОЙКИ =================
# Токен автоматически берётся из вкладки «Переменные» / «Токен» на хостинге
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or ""
ADMIN_ID = 5157852376

# КОНТАКТ ПОДДЕРЖКИ В TELEGRAM (укажи актуальный @username)
SUPPORT_USERNAME = "@bombych"
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
DONATIONALERTS_URL = "https://www.donationalerts.com/r/bombychyt"
TON_WALLET = "UQAmhiehcvEaSqZZ-aTZK0RPDw2CDEzjSkiZymwYiyrMWbPw"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

CURRENT_DB_NAME = "bombystore_v10.db"
DB_PATH = os.path.join(DATA_DIR, CURRENT_DB_NAME)
IMG_DIR = os.path.join(BASE_DIR, "assets_v16")
CATALOG_SCHEMA_VERSION = "v12_fortnite_folder"

FORTNITE_CAT_IDS = (1, 2, 3)
USERS_PER_PAGE = 8
REQ_TIMEOUT = 15

PAYMENT_DA_TEXT = (
    "🧡 <b>Оплата через DonationAlerts:</b>\n"
    "<blockquote>1. Нажмите кнопку <b>«🧡 Перейти к оплате»</b> ниже.\n"
    "2. Укажите точную сумму заказа и в сообщении доната напишите номер заказа.\n"
    "3. После оплаты нажмите <b>«📸 Отправить чек»</b> и прикрепите скриншот.</blockquote>"
)

PAYMENT_CRYPTO_TEXT = (
    "🪙 <b>Оплата криптовалютой (TON / USDT в сети TON):</b>\n"
    "<blockquote>🌐 Сеть: <b>TON (The Open Network)</b>\n"
    f"👛 Кошелек: <code>{TON_WALLET}</code></blockquote>\n"
    "📌 Нажмите на адрес кошелька выше, чтобы скопировать его.\n"
    "После перевода нажмите <b>«📸 Отправить чек»</b> и прикрепите скриншот транзакции."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
router = Router()

# ================= ГЛОБАЛЬНЫЙ КЭШ И СОСТОЯНИЕ =================
DB_CONN: aiosqlite.Connection | None = None
DB_LOCK = asyncio.Lock()
LAST_SCREEN_TAG: dict[tuple[int, int], str] = {}
LAST_CLICK: dict[tuple[int, str], float] = {}

PHOTO_CACHE: dict[str, str] = {}
DOC_CACHE: dict[str, str] = {}
DOC_META: dict[str, dict[str, str]] = {}
FILE_HASHES: dict[str, str] = {}

KNOWN_USERS: set[int] = set()
ACCEPTED_USERS: set[int] = set()
_RESOLVED_FONT_PATH: str | None = None
_FONT_SEARCHED = False

RAM_CATS: dict[int, dict] = {}
RAM_CAT_ORDER: list[int] = []
RAM_PRODS: dict[int, dict] = {}
RAM_CAT_KBS: dict[int, InlineKeyboardMarkup] = {}
RAM_CAT_CAPTIONS: dict[int, str] = {}
RAM_CATALOG_KB: InlineKeyboardMarkup | None = None
RAM_FORTNITE_KB: InlineKeyboardMarkup | None = None


class OrderFlow(StatesGroup):
    waiting_receipt = State()


class AdminFlow(StatesGroup):
    waiting_broadcast = State()
    add_full_name = State()
    add_short_btn = State()
    add_price = State()


# ================= КАТАЛОГ ТОВАРОВ =================
CATEGORIES_DATA = [
    (
        1, "💎 В-Баксы", "💎 В-Баксы Fortnite", "vbucks.jpg", "purple_forest", ("VBUCKS", ""),
        "💎 <b>Официальное пополнение В-Баксов Fortnite на ваш аккаунт.</b>\n"
        "Перед покупкой убедитесь, что к вашему профилю Epic Games привязан аккаунт Xbox.",
        [
            ("800 В-Баксов", "💎 800 ВБ", 499, 399),
            ("2 400 В-Баксов", "💎 2400 ВБ", 1279, 1023),
            ("4 500 В-Баксов", "💎 4500 ВБ", 1949, 1559),
            ("12 500 В-Баксов", "💎 12500 ВБ", 4599, 3679),
        ]
    ),
    (
        2, "🎁 ВБ подарком", "🎁 В-Баксы подарком", "gift_vbucks.jpg", "purple_forest", ("GIFT", "VBUCKS"),
        "🎁 <b>Отправка любых скинов, кирок и эмоций из магазина Fortnite подарком!</b>\n"
        "Для получения добавьте наши аккаунты в друзья за 48 часов до покупки.",
        [
            ("200 В-Баксов (Подарком)", "🎁 200 ВБ", 170, 136),
            ("500 В-Баксов (Подарком)", "🎁 500 ВБ", 290, 232),
            ("800 В-Баксов (Подарком)", "🎁 800 ВБ", 390, 312),
            ("1 200 В-Баксов (Подарком)", "🎁 1200 ВБ", 550, 440),
            ("1 500 В-Баксов (Подарком)", "🎁 1500 ВБ", 720, 576),
            ("1 800 В-Баксов (Подарком)", "🎁 1800 ВБ", 970, 776),
            ("2 000 В-Баксов (Подарком)", "🎁 2000 ВБ", 1150, 920),
            ("2 500 В-Баксов (Подарком)", "🎁 2500 ВБ", 1250, 1000),
        ]
    ),
    (
        3, "📦 Наборы", "📦 Наборы", "packs.jpg", "purple_forest", ("НАБОРЫ", "FORTNITE"),
        "📦 <b>Подписка Отряд Fortnite (Fortnite Crew), наборы Xbox и покупка игр Epic Games.</b>",
        [
            ("Отряд Fortnite (Fortnite Crew)", "👑 Отряд", 444, 355),
            ("Стартер-пак Fortnite (600 ВБ)", "📦 Стартер", 349, 279),
            ("Боевой Пропуск сезона", "🎫 БП Сезона", 599, 479),
            ("Набор «Искусный взлом» / ПВЕ", "🛡 Набор ПВЕ", 1199, 959),
            ("Покупка игр / DLC Epic Games", "🎮 Игры Epic", 215, 172),
            ("Активация вашего кода Xbox", "🔑 Код Xbox", 100, 80),
        ]
    ),
    (
        4, "🌴 GTA VI", "🌴 Покупка игры Grand Theft Auto VI", "gta6.jpg", "gta6_sunset", ("GTA VI", ""),
        "🌴 <b>Официальная покупка Grand Theft Auto VI для PlayStation и Xbox!</b>\n"
        "После оплаты укажите данные вашей консоли / аккаунта для оформления игры.",
        [
            ("GTA VI PlayStation", "🎮 PS • 6479₽", 7199, 6479),
            ("GTA VI Xbox", "🎮 Xbox • 6209₽", 6899, 6209),
        ]
    ),
    (
        5, "🔫 Brawl Stars", "🟢 Гемы и Пропуски Brawl Stars", "brawl.jpg", "violet_neon", ("BRAWL", "STARS"),
        "🟢 <b>Официальное пополнение гемов и Brawl Pass по вашему Supercell ID.</b>\n"
        "❗ Перед покупкой убедитесь, что ваш аккаунт подключен к Supercell ID.",
        [
            ("30 Гемов Brawl Stars", "🟢 30 Гемов", 199, 159),
            ("80 Гемов Brawl Stars", "🟢 80 Гемов", 489, 391),
            ("170 Гемов Brawl Stars", "🟢 170 Гемов", 979, 783),
            ("180 Гемов (Акция)", "🔥 180 Акция", 999, 799),
            ("360 Гемов Brawl Stars", "🟢 360 Гемов", 1949, 1559),
            ("950 Гемов Brawl Stars", "🟢 950 Гемов", 4199, 3359),
            ("2000 Гемов Brawl Stars", "🟢 2000 Гемов", 8199, 6559),
            ("BRAWL PASS", "🎫 PASS", 949, 759),
            ("BRAWL PASS +", "🎫 PASS+", 969, 775),
        ]
    ),
    (
        6, "👑 Clash Royale", "👑 Гемы и Pass Clash Royale", "clash.jpg", "blue_royal", ("CLASH", "ROYALE"),
        "👑 <b>Официальное пополнение гемов и боевых пропусков Clash Royale через Supercell ID.</b>",
        [
            ("80 + 8 Гемов CR", "💎 88 Гемов", 169, 135),
            ("500 + 50 Гемов CR", "💎 550 Гемов", 479, 383),
            ("1200 + 120 Гемов CR", "💎 1320 Гемов", 919, 735),
            ("2500 + 250 Гемов CR", "💎 2750 Гемов", 1679, 1343),
            ("6500 + 650 Гемов CR", "💎 7150 Гемов", 3979, 3183),
            ("14000 + 1400 Гемов CR", "💎 15400 Гем", 7499, 5999),
            ("GOLD PASS", "🎫 GOLD", 549, 439),
            ("DIAMOND PASS", "🎫 DIAMOND", 999, 799),
        ]
    ),
    (
        7, "⚔️ Clash of Clans", "⚔️ Гемы и Пропуски Clash of Clans", "coc.jpg", "gold_forest", ("CLASH OF", "CLANS"),
        "⚔️ <b>Пополнение гемов и пропусков событий Clash of Clans по вашему Supercell ID.</b>",
        [
            ("80 Гемов Clash of Clans", "💎 80 Гемов", 119, 95),
            ("500 Гемов Clash of Clans", "💎 500 Гемов", 499, 399),
            ("1200 Гемов Clash of Clans", "💎 1200 Гемов", 999, 799),
            ("2500 Гемов Clash of Clans", "💎 2500 Гемов", 1899, 1519),
            ("6500 Гемов Clash of Clans", "💎 6500 Гемов", 4499, 3599),
            ("Мини-пропуск события CC", "🎫 Мини-Пасс", 339, 271),
        ]
    ),
    (
        8, "🎲 Roblox", "🎲 Коды Robux для РФ — Roblox", "roblox.jpg", "red_forest", ("ROBLOX", "ROBUX"),
        "🎲 <b>Цифровые коды пополнения Robux для аккаунтов РФ и любого региона.</b>",
        [
            ("199 Robux (Код РФ)", "🎲 199 R$", 279, 223),
            ("255 Robux (Код РФ)", "🎲 255 R$", 364, 291),
            ("395 Robux (Код РФ)", "🎲 395 R$", 559, 447),
            ("715 Robux (Код РФ)", "🎲 715 R$", 1009, 807),
            ("1500 Robux (Код РФ)", "🎲 1500 R$", 2099, 1679),
            ("4500 Robux (Код РФ)", "🎲 4500 R$", 5999, 4799),
        ]
    ),
    (
        9, "🌙 Genshin Impact", "🌙 Пополнение Genshin Impact по UID", "genshin.jpg", "cyan_night", ("GENSHIN", "IMPACT"),
        "🌙 <b>Моментальное пополнение Кристаллов Сотворения и Луны по вашему UID и серверу.</b>",
        [
            ("Гранулы времени", "⏳ Гранулы", 105, 84),
            ("Благословение полой луны", "🌙 Полая Луна", 491, 393),
            ("Кристаллы Сотворения (Пакет)", "💎 Пакет 500", 500, 400),
            ("980 + 110 Кристаллов", "💎 1090 Крист", 1399, 1119),
            ("1980 + 260 Кристаллов", "💎 2240 Крист", 2799, 2239),
            ("6480 + 1600 Кристаллов", "💎 8080 Крист", 8499, 6799),
        ]
    ),
    (
        10, "🎯 Standoff 2", "🎯 Голда Standoff 2 по ID", "standoff.jpg", "red_forest", ("STANDOFF 2", "GOLD"),
        "🎯 <b>Быстрое пополнение голды (Gold) в Standoff 2 напрямую по вашему игровому ID.</b>",
        [
            ("100 Gold (По ID)", "🎯 100 G", 109, 87),
            ("200 Gold (По ID)", "🎯 200 G", 219, 175),
            ("500 Gold (По ID)", "🎯 500 G", 600, 480),
            ("1000 Gold (По ID)", "🎯 1000 G", 1100, 880),
            ("3000 Gold (По ID)", "🎯 3000 G", 2600, 2080),
        ]
    ),
    (
        11, "🔥 Free Fire", "💎 Алмазы Free Fire", "freefire.jpg", "red_forest", ("FREE", "FIRE"),
        "💎 <b>Быстрое зачисление алмазов (Diamonds) на ваш игровой аккаунт Free Fire.</b>",
        [
            ("100 Diamonds", "💎 100 Алм.", 179, 143),
            ("210 Diamonds", "💎 210 Алм.", 269, 215),
            ("530 Diamonds", "💎 530 Алм.", 579, 463),
            ("645 Diamonds", "💎 645 Алм.", 749, 599),
            ("1080 Diamonds", "💎 1080 Алм.", 1049, 839),
            ("2200 Diamonds", "💎 2200 Алм.", 2049, 1639),
            ("4450 Diamonds", "💎 4450 Алм.", 4499, 3599),
            ("6900 Diamonds", "💎 6900 Алм.", 6749, 5399),
        ]
    ),
    (
        12, "🪂 PUBG / Шутеры", "🪂 G-Coin PUBG и Arena Breakout", "pubg.jpg", "gold_forest", ("PUBG", "G-COIN"),
        "🪂 <b>Коды G-Coin для Steam-версии PUBG и облигации для Arena Breakout Mobile.</b>",
        [
            ("100 G-Coin PUBG", "🪂 100 GC", 85, 68),
            ("500 + 10 G-Coin PUBG", "🪂 510 GC", 419, 335),
            ("1000 + 50 G-Coin PUBG", "🪂 1050 GC", 839, 671),
            ("2500 + 200 G-Coin PUBG", "🪂 2700 GC", 2099, 1679),
            ("5000 + 500 G-Coin PUBG", "🪂 5500 GC", 4189, 3351),
            ("Облигации Arena Breakout", "🎖 Arena 60", 119, 95),
        ]
    ),
    (
        13, "💰 Вирты GTA/BR", "💰 Вирты GTA 5 и Black Russia", "virts.jpg", "gold_forest", ("ВИРТЫ", ""),
        "💰 <b>Быстрая доставка игровой валюты на ваш сервер.</b>\n"
        "✅ После покупки укажите сервер и номер банковского счета в комментарии к чеку.",
        [
            ("1kk Виртов", "💰 1kk", 149, 119),
            ("5kk Виртов", "💰 5kk", 689, 551),
            ("10kk Виртов", "💰 10kk", 999, 799),
            ("15kk Виртов", "💰 15kk", 1299, 1039),
            ("30kk Виртов", "💰 30kk", 1899, 1519),
        ]
    ),
    (
        14, "⭐ Telegram", "⭐ Telegram Premium и Звёзды (Stars)", "tg_prem.jpg", "blue_royal", ("Telegram", "Premium"),
        "⭐ <b>Официальная подписка Telegram Premium и Звёзды (Telegram Stars) по вашему @username без входа в аккаунт.</b>",
        [
            ("Telegram Premium 30 дней", "⭐ Prem 30д", 249, 199),
            ("Telegram Premium 90 дней", "⭐ Prem 90д", 749, 599),
            ("Telegram Premium 365 дней", "⭐ Prem 1 Год", 1999, 1599),
            ("100 Звёзд Telegram (Stars)", "✨ 100 Stars", 199, 159),
            ("250 Звёзд Telegram (Stars)", "✨ 250 Stars", 489, 391),
            ("500 Звёзд Telegram (Stars)", "✨ 500 Stars", 949, 759),
            ("1000 Звёзд Telegram (Stars)", "✨ 1000 Stars", 1849, 1479),
            ("2500 Звёзд Telegram (Stars)", "✨ 2500 Stars", 4499, 3599),
        ]
    ),
    (
        15, "🧿 Steam", "🧿 Пополнение баланса и Игры Steam", "steam.jpg", "cyan_night", ("STEAM", "STORE"),
        "🧿 <b>Моментальное пополнение кошелька Steam (РФ / СНГ / КЗ) по логину и отправка игр подарком (Steam Gifts).</b>",
        [
            ("Пополнение Steam на 250 ₽", "🧿 250 ₽", 290, 232),
            ("Пополнение Steam на 500 ₽", "🧿 500 ₽", 560, 448),
            ("Пополнение Steam на 1000 ₽", "🧿 1000 ₽", 1120, 896),
            ("Пополнение Steam на 2000 ₽", "🧿 2000 ₽", 2200, 1760),
            ("Пополнение Steam на 5000 ₽", "🧿 5000 ₽", 5450, 4360),
            ("Игра подарком (Steam Gift)", "🎁 Steam Gift", 499, 399),
        ]
    ),
    (
        16, "🔮 Discord Nitro", "🔮 Discord N1tro (Любой аккаунт)", "nitro.jpg", "violet_neon", ("Discord", "N1tro"),
        "🔮 <b>Официальная подписка Discord Nitro Classic и Full на любой аккаунт!</b>",
        [
            ("Discord Nitro Classic 30 дн.", "🔮 Clas 30д", 250, 200),
            ("Discord Nitro Classic 365 дн.", "🔮 Clas Год", 1500, 1200),
            ("Discord Nitro Full 30 дн.", "🚀 Full 30д", 400, 320),
            ("Discord Nitro Full 365 дн.", "🚀 Full Год", 3050, 2440),
        ]
    ),
    (
        17, "🤖 ИИ и Spotify", "🤖 Подписки ChatGPT и Spotify Premium", "ai_spotify.jpg", "emerald_forest", ("SPOTIFY", "& AI"),
        "🤖 <b>Оформление зарубежных подписок ChatGPT (GO / Plus) и индивидуального Spotify Premium.</b>",
        [
            ("ChatGPT GO (1 месяц)", "🤖 GPT GO", 499, 399),
            ("ChatGPT Plus (1 месяц)", "🧠 GPT Plus", 1999, 1599),
            ("Spotify Premium 1 мес.", "🎧 Spotify 1м", 349, 279),
            ("Spotify Premium 3 мес.", "🎧 Spotify 3м", 899, 719),
            ("Spotify Premium 12 мес.", "🎧 Spotify 1г", 2499, 1999),
        ]
    ),
    (
        18, "🔻 ExitLag", "🔻 Ключи активации ExitLag", "exitlag.jpg", "red_forest", ("ExitLag", ""),
        "🔻 <b>Лицензионные коды ExitLag для снижения пинга и стабилизации соединения в играх.</b>",
        [
            ("ExitLag 3 дня", "🔻 3 дня", 20, 16),
            ("ExitLag 15 дней", "🔻 15 дней", 120, 96),
            ("ExitLag 30 дней", "🔻 30 дней", 200, 160),
            ("ExitLag 60 дней", "🔻 60 дней", 400, 320),
            ("ExitLag 100 дней", "🔻 100 дней", 500, 400),
            ("ExitLag 150 дней", "🔻 150 дней", 550, 440),
            ("ExitLag 200 дней", "🔻 200 дней", 600, 480),
            ("ExitLag 300 дней", "🔻 300 дней", 700, 560),
        ]
    ),
    (
        19, "💳 Банки / Биржи", "💳 Зарубежные Банки и Верификация", "banks.jpg", "cyan_night", ("БАНКИ", "ВЕРИФИКАЦИЯ"),
        "💳 <b>Готовые личные кабинеты зарубежных банков для оплаты сервисов и верификация криптобирж.</b>",
        [
            ("Ozan (Банк Турции)", "💳 Ozan", 999, 799),
            ("Belo (Банк Аргентины)", "💳 Belo", 1499, 1199),
            ("Bybit (Верификация)", "📈 Bybit", 1499, 1199),
            ("Binance (Верификация)", "📈 Binance", 1599, 1279),
            ("Huobi (Верификация)", "📈 Huobi", 1299, 1039),
            ("Ozon (Верификация)", "💳 Ozon", 999, 799),
            ("Yoomoney/Qiwi (Турция)", "💳 ЮMoney", 249, 199),
        ]
    ),
]

USER_UPLOADED_MAP = {
    "logo.jpg": ["4.jpg", "logo.jpg", "logo.png"],
    "vbucks.jpg": ["vbucks.jpg", "1 (1).jpg", "1_3.jpg", "vbucks.png"],
    "gift_vbucks.jpg": ["gifts.jpg", "xs1.jpg", "gift_vbucks.jpg", "gift_vbucks.png"],
    "nitro.jpg": ["nitro.jpg", "1.jpg", "1_2.jpg", "nitro.png"],
    "tg_prem.jpg": ["tg_prem.jpg", "-1.png", "tg_prem.png"],
    "exitlag.jpg": ["exitlag.jpg", "891.jpg", "exitlag.png"],
    "brawl.jpg": ["brawl.jpg", "brawl.png"],
    "info.jpg": ["information.png", "info.png", "info.jpg"],
}

SERVICE_BANNERS = [
    ("main.jpg", "purple_forest", ("BOMBYCH", "STORE")),
    ("catalog.jpg", "purple_forest", ("КАТАЛОГ", "")),
    ("fortnite.jpg", "purple_forest", ("FORTNITE", "")),
    ("profile.jpg", "violet_neon", ("ПРОФИЛЬ", "")),
    ("info.jpg", "purple_forest", ("INFORMATION", "")),
    ("rules.jpg", "purple_forest", ("ПРАВИЛА", "")),
    ("xbox.jpg", "cyan_night", ("ПРИВЯЗКА", "")),
    ("support.jpg", "blue_royal", ("ПОДДЕРЖКА", "")),
    ("terms.jpg", "violet_neon", ("ПОЛЬЗОВАТЕЛЬСКОЕ", "СОГЛАШЕНИЕ")),
    ("privacy.jpg", "cyan_night", ("ПОЛИТИКА", "КОНФИДЕНЦИАЛЬНОСТИ")),
]

# ================= СОДЕРЖИМОЕ PDF-ДОКУМЕНТОВ =================
TERMS_SECTIONS = [
    (
        "1. Общие положения",
        [
            "1.1. Настоящее Пользовательское соглашение (далее — Соглашение) регулирует отношения между администрацией Telegram-бота Bombych Store (далее — Сервис) и физическим лицом, использующим Сервис (далее — Пользователь).",
            "1.2. Нажимая кнопку «Принимаю условия» при первом входе и продолжая использование Сервиса, Пользователь подтверждает полное и безоговорочное согласие со всеми условиями настоящего Соглашения.",
            "1.3. Пользователь подтверждает достижение возраста 18 лет либо наличие согласия родителей или иных законных представителей на совершение покупок в Сервисе."
        ]
    ),
    (
        "2. Предмет соглашения",
        [
            "2.1. Сервис оказывает информационно-посреднические услуги по приобретению и зачислению цифровых товаров: игровой валюты, внутриигровых наборов, цифровых ключей активации и подписок.",
            "2.2. Сервис является независимой торговой площадкой и не аффилирован с компаниями Epic Games, Supercell, Valve, Telegram, Discord, Roblox, miHoYo, Krafton, Microsoft, Sony и иными правообладателями."
        ]
    ),
    (
        "3. Порядок оформления и оплаты заказов",
        [
            "3.1. Актуальный перечень товаров и стоимость указаны в каталоге Сервиса и могут изменяться администрацией без предварительного уведомления. Для уже оплаченных заказов цена фиксируется на момент оплаты.",
            "3.2. Оплата производится по реквизитам, выданным Сервисом в счёте на оплату. После перевода средств Пользователь прикрепляет скриншот или файл чека в бот.",
            "3.3. Заказ принимается в работу только после проверки администратором фактического поступления оплаты."
        ]
    ),
    (
        "4. Сроки выдачи и условия возврата",
        [
            "4.1. Приём заявок в боте осуществляется круглосуточно (24/7). Обработка заказов и выдача цифровых товаров производятся в рабочие часы: ежедневно с 05:00 до 22:00 по московскому времени (МСК).",
            "4.2. Цифровые товары, ключи активации, подписки и внутриигровые зачисления надлежащего качества после фактической передачи или активации возврату и обмену не подлежат.",
            "4.3. В случае невозможности выполнения оплаченного заказа по вине Сервиса Пользователю осуществляется полный возврат уплаченной суммы по согласованным реквизитам."
        ]
    ),
    (
        "5. Права, обязанности и ограничения",
        [
            "5.1. Пользователь несёт полную ответственность за достоверность предоставляемых данных (игровой ID, UID, @username, регион аккаунта, корректная привязка Xbox / Supercell ID и иные сведения).",
            "5.2. В случае указания Пользователем ошибочных реквизитов, повлекших зачисление товара на иной аккаунт, услуга считается оказанной надлежащим образом и возврату не подлежит.",
            "5.3. Запрещается отправка поддельных чеков, спам, попытки нарушения работы Сервиса, а также оскорбления в адрес поддержки. При выявлении нарушений администрация вправе ограничить доступ к боту.",
            "5.4. Сервис не несёт ответственности за временные технические сбои платёжных систем, мессенджера Telegram, игровых серверов, а также за ограничения, применяемые правообладателями игр."
        ]
    ),
    (
        "6. Заключительные положения",
        [
            "6.1. Администрация оставляет за собой право вносить изменения в настоящее Соглашение. Актуальная версия документа всегда доступна в соответствующем разделе бота.",
            f"6.2. По всем вопросам, связанным с работой Сервиса, заказами и условиями настоящего Соглашения, обращайтесь к нам в поддержку Telegram: {SUPPORT_USERNAME}."
        ]
    ),
]

PRIVACY_SECTIONS = [
    (
        "1. Общие положения",
        [
            "1.1. Настоящая Политика конфиденциальности определяет порядок сбора, хранения, обработки, защиты и удаления персональных данных пользователей Telegram-бота Bombych Store (далее — Сервис).",
            "1.2. Обработка данных осуществляется с соблюдением принципов конфиденциальности и безопасности, соответствующих базовым требованиям ФЗ № 152-ФЗ «О персональных данных».",
            "1.3. Нажимая кнопку согласия при первом запуске бота, Пользователь подтверждает своё согласие с условиями настоящей Политики."
        ]
    ),
    (
        "2. Состав собираемых данных",
        [
            "• Технические данные Telegram: уникальный идентификатор (Telegram ID), имя пользователя (@username), отображаемое имя профиля и дата первого обращения в бот.",
            "• Сведения о заказах: наименования выбранных позиций, суммы, выбранный способ оплаты, статусы обработки, прикреплённые чеки и комментарии к заказам.",
            "• Сведения для зачисления товара: игровой ID, UID, тег, электронная почта или временные реквизиты доступа, добровольно переданные Пользователем исключительно для выполнения конкретного заказа."
        ]
    ),
    (
        "3. Цели обработки персональных данных",
        [
            "• Регистрация и идентификация Пользователя в Сервисе, отображение личного кабинета и истории покупок.",
            "• Проверка факта оплаты, выполнение и доставка оплаченных цифровых товаров и услуг.",
            "• Оказание технической поддержки и разрешение спорных ситуаций по заказам.",
            "• Направление сервисных уведомлений о статусе заказов, а также новостей и акций Сервиса."
        ]
    ),
    (
        "4. Хранение и защита данных",
        [
            "4.1. Технические данные профиля и история заказов хранятся в защищённой базе данных с ограниченным доступом, доступной только администрации Сервиса.",
            "4.2. Данные доступа к игровым аккаунтам используются строго однократно для зачисления оплаченного товара и подлежат немедленному удалению сразу после завершения заказа. Сервис не сохраняет пароли и платёжные реквизиты банковских карт Пользователей.",
            "4.3. Администрация принимает необходимые организационные и технические меры для предотвращения утечки, утраты, изменения или несанкционированного доступа к информации."
        ]
    ),
    (
        "5. Нераспространение и передача третьим лицам",
        [
            "5.1. Личные данные Пользователей строго конфиденциальны: они не продаются, не публикуются в открытом доступе и не распространяются среди третьих лиц.",
            "5.2. Передача отдельных данных допускается исключительно в двух случаях: если это технически необходимо для проведения платежа или зачисления товара, либо по законному официальному требованию уполномоченных государственных органов."
        ]
    ),
    (
        "6. Права пользователя и удаление данных",
        [
            "6.1. Пользователь имеет право запросить информацию о своих данных, хранящихся в базе Сервиса, потребовать их исправления, отказаться от информационных рассылок или запросить полное удаление профиля и истории обращений.",
            f"6.2. Для отзыва согласия, удаления данных или по любым вопросам конфиденциальности напишите нам в поддержку Telegram: {SUPPORT_USERNAME}."
        ]
    ),
]


# ================= АВТООЧИСТКА СТАРЫХ ПАПОК И БД =================
def cleanup_old_files():
    removed_items = []
    current_img_folder = os.path.basename(IMG_DIR)

    for pattern in ("img_v*", "assets_v*"):
        for folder_path in glob.glob(os.path.join(BASE_DIR, pattern)):
            if os.path.isdir(folder_path) and os.path.basename(folder_path) != current_img_folder:
                shutil.rmtree(folder_path, ignore_errors=True)
                removed_items.append(os.path.basename(folder_path))

    keep_prefixes = (CURRENT_DB_NAME,)
    for search_dir in {BASE_DIR, DATA_DIR}:
        for pattern in ("bombystore.db*", "bombystore_v*.db*", "shop.db*", "bot.db*"):
            for db_file in glob.glob(os.path.join(search_dir, pattern)):
                fname = os.path.basename(db_file)
                if any(fname.startswith(pref) for pref in keep_prefixes):
                    continue
                try:
                    os.remove(db_file)
                    removed_items.append(fname)
                except OSError:
                    pass

    if removed_items:
        logging.info(f"Автоочистка выполнена. Удалено: {', '.join(removed_items)}")


# ================= ГЕНЕРАТОР БАННЕРОВ И PDF-ДОКУМЕНТОВ =================
THEME_PALETTES = {
    "purple_forest": {
        "bg": (5, 7, 22),
        "glow": (115, 38, 255),
        "corner_left": (15, 195, 255),
        "corner_right": (185, 35, 245),
        "star": (245, 220, 255),
        "text_top": (195, 65, 255),
        "text_bot": (105, 20, 225),
        "stroke": (35, 8, 75),
        "spark": (125, 235, 255),
        "tint_mode": "purple",
    },
    "gta6_sunset": {
        "bg": (18, 6, 28),
        "glow": (255, 55, 165),
        "corner_left": (255, 145, 40),
        "corner_right": (145, 50, 255),
        "star": (255, 225, 195),
        "text_top": (255, 220, 120),
        "text_bot": (255, 65, 175),
        "stroke": (48, 10, 58),
        "spark": (255, 200, 140),
        "tint_mode": "purple",
    },
    "violet_neon": {
        "bg": (10, 5, 28),
        "glow": (165, 45, 255),
        "corner_left": (235, 45, 210),
        "corner_right": (70, 125, 255),
        "star": (250, 225, 255),
        "text_top": (230, 80, 255),
        "text_bot": (120, 35, 235),
        "stroke": (42, 10, 80),
        "spark": (255, 165, 255),
        "tint_mode": "purple",
    },
    "blue_royal": {
        "bg": (4, 10, 28),
        "glow": (40, 130, 255),
        "corner_left": (0, 215, 255),
        "corner_right": (110, 65, 255),
        "star": (225, 242, 255),
        "text_top": (135, 225, 255),
        "text_bot": (40, 110, 245),
        "stroke": (12, 30, 75),
        "spark": (160, 235, 255),
        "tint_mode": "cyan",
    },
    "cyan_night": {
        "bg": (3, 14, 24),
        "glow": (15, 185, 245),
        "corner_left": (0, 245, 220),
        "corner_right": (85, 95, 255),
        "star": (215, 252, 255),
        "text_top": (115, 248, 255),
        "text_bot": (25, 145, 235),
        "stroke": (10, 42, 68),
        "spark": (150, 255, 245),
        "tint_mode": "cyan",
    },
    "red_forest": {
        "bg": (20, 4, 9),
        "glow": (235, 25, 55),
        "corner_left": (255, 95, 25),
        "corner_right": (200, 15, 95),
        "star": (255, 185, 195),
        "text_top": (255, 65, 105),
        "text_bot": (175, 12, 48),
        "stroke": (55, 6, 18),
        "spark": (255, 175, 100),
        "tint_mode": "red",
    },
    "gold_forest": {
        "bg": (18, 12, 5),
        "glow": (245, 165, 25),
        "corner_left": (255, 210, 60),
        "corner_right": (220, 85, 25),
        "star": (255, 242, 195),
        "text_top": (255, 225, 95),
        "text_bot": (215, 115, 15),
        "stroke": (58, 32, 5),
        "spark": (255, 235, 145),
        "tint_mode": "gold",
    },
    "emerald_forest": {
        "bg": (4, 18, 14),
        "glow": (25, 215, 120),
        "corner_left": (20, 240, 195),
        "corner_right": (95, 225, 60),
        "star": (220, 255, 235),
        "text_top": (105, 255, 170),
        "text_bot": (15, 165, 90),
        "stroke": (8, 52, 32),
        "spark": (165, 255, 210),
        "tint_mode": "emerald",
    },
}


def _find_user_file(filenames: list) -> str | None:
    home = os.path.expanduser("~")
    dirs = [
        os.path.join(BASE_DIR, "img"),
        os.path.join(BASE_DIR, "images"),
        BASE_DIR,
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
    ]
    lower_targets = [fn.lower() for fn in filenames]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        entries_map = {e.lower(): e for e in entries}
        for target in lower_targets:
            if target in entries_map:
                full_path = os.path.join(d, entries_map[target])
                if os.path.isfile(full_path):
                    return full_path
    return None


def _file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_font_file(urls: list[str], dest_path: str) -> str | None:
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
        try:
            ImageFont.truetype(dest_path, 24)
            return dest_path
        except Exception:
            pass
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = resp.read()
            if len(data) > 10000:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(data)
                ImageFont.truetype(dest_path, 24)
                return dest_path
        except Exception:
            continue
    return None


def _resolve_font_path() -> str | None:
    global _RESOLVED_FONT_PATH, _FONT_SEARCHED
    if _FONT_SEARCHED:
        return _RESOLVED_FONT_PATH
    _FONT_SEARCHED = True

    local_dirs = [
        os.path.join(BASE_DIR, "img"),
        os.path.join(BASE_DIR, "images"),
        BASE_DIR,
    ]
    preferred_names = ("impact.ttf", "arialbd.ttf", "font.ttf")
    for d in local_dirs:
        if not os.path.isdir(d):
            continue
        try:
            files = os.listdir(d)
        except OSError:
            continue
        files_map = {f.lower(): f for f in files}
        for pref in preferred_names:
            if pref in files_map:
                p = os.path.join(d, files_map[pref])
                try:
                    ImageFont.truetype(p, 48)
                    _RESOLVED_FONT_PATH = p
                    logging.info(f"Шрифт загружен из проекта: {p}")
                    return p
                except Exception:
                    pass
        for f in files:
            if f.lower().endswith((".ttf", ".otf")):
                p = os.path.join(d, f)
                try:
                    ImageFont.truetype(p, 48)
                    _RESOLVED_FONT_PATH = p
                    logging.info(f"Шрифт загружен из проекта: {p}")
                    return p
                except Exception:
                    pass

    font_candidates = [
        "C:\\Windows\\Fonts\\impact.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in font_candidates:
        if os.path.exists(p):
            try:
                ImageFont.truetype(p, 48)
                _RESOLVED_FONT_PATH = p
                return p
            except Exception:
                pass

    downloaded = _download_font_file(
        [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PTSans-Bold.ttf",
            "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ptsans/PTSans-Bold.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/ubuntu/Ubuntu-Bold.ttf",
        ],
        os.path.join(IMG_DIR, "_banner_bold.ttf")
    )
    if downloaded:
        _RESOLVED_FONT_PATH = downloaded
        return downloaded
    return None


def _resolve_doc_fonts() -> tuple[str | None, str | None]:
    reg_candidates = [
        os.path.join(IMG_DIR, "_doc_regular.ttf"),
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]
    bold_candidates = [
        os.path.join(IMG_DIR, "_doc_bold.ttf"),
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ]

    reg_path = None
    for p in reg_candidates:
        if os.path.exists(p):
            try:
                ImageFont.truetype(p, 20)
                reg_path = p
                break
            except Exception:
                pass

    bold_path = None
    for p in bold_candidates:
        if os.path.exists(p):
            try:
                ImageFont.truetype(p, 20)
                bold_path = p
                break
            except Exception:
                pass

    if not reg_path:
        reg_path = _download_font_file(
            [
                "https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PTSans-Regular.ttf",
                "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ptsans/PTSans-Regular.ttf",
                "https://raw.githubusercontent.com/google/fonts/main/ofl/ubuntu/Ubuntu-Regular.ttf",
                "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ubuntu/Ubuntu-Regular.ttf",
            ],
            os.path.join(IMG_DIR, "_doc_regular.ttf")
        )
    if not bold_path:
        bold_path = _download_font_file(
            [
                "https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PTSans-Bold.ttf",
                "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ptsans/PTSans-Bold.ttf",
                "https://raw.githubusercontent.com/google/fonts/main/ofl/ubuntu/Ubuntu-Bold.ttf",
                "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ubuntu/Ubuntu-Bold.ttf",
            ],
            os.path.join(IMG_DIR, "_doc_bold.ttf")
        ) or reg_path

    if not reg_path:
        fallback = _resolve_font_path()
        if fallback:
            reg_path = fallback
            bold_path = fallback

    return reg_path, bold_path


def _load_bold_font(size: int):
    font_path = _resolve_font_path()
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int, start_size: int, min_size: int = 34):
    sz = start_size
    while sz >= min_size:
        f = _load_bold_font(sz)
        bbox = draw.textbbox((0, 0), text, font=f)
        if (bbox[2] - bbox[0]) <= max_w:
            return f, bbox
        sz -= 4
    f = _load_bold_font(min_size)
    return f, draw.textbbox((0, 0), text, font=f)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for word in words:
        cand = f"{cur} {word}".strip() if cur else word
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
                cur = word
            else:
                chunk = ""
                for ch in word:
                    if draw.textlength(chunk + ch, font=font) <= max_w:
                        chunk += ch
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = ch
                cur = chunk
    if cur:
        lines.append(cur)
    return lines


def _make_doc_thumbnail(banner_path: str, thumb_path: str):
    src = Image.open(banner_path).convert("RGB")
    bg = src.resize((320, 320), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(12))
    bg = Image.blend(bg, Image.new("RGB", (320, 320), (10, 6, 26)), 0.45)

    bw = 320
    bh = int(src.height * (bw / src.width))
    fg = src.resize((bw, bh), Image.Resampling.LANCZOS)
    bg.paste(fg, (0, (320 - bh) // 2))
    bg.save(thumb_path, "JPEG", quality=85, optimize=True)


def _generate_legal_pdf(
    pdf_path: str,
    banner_path: str,
    title: str,
    subtitle: str,
    sections: list[tuple[str, list[str]]],
    reg_font_path: str,
    bold_font_path: str
):
    W, H = 1000, 1414
    ML, MR, MT, MB = 68, 68, 64, 88
    CONTENT_W = W - ML - MR

    f_sub = ImageFont.truetype(reg_font_path, 16)
    f_sec = ImageFont.truetype(bold_font_path, 22)
    f_body = ImageFont.truetype(reg_font_path, 19)
    f_foot = ImageFont.truetype(reg_font_path, 15)

    t_sz = 28
    f_title = ImageFont.truetype(bold_font_path, t_sz)
    tmp_dr = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while t_sz > 20 and tmp_dr.textlength(title, font=f_title) > CONTENT_W:
        t_sz -= 2
        f_title = ImageFont.truetype(bold_font_path, t_sz)

    pages: list[Image.Image] = []

    def new_page(first: bool = False):
        pg = Image.new("RGB", (W, H), (255, 255, 255))
        dr = ImageDraw.Draw(pg)
        if first:
            y_cursor = 0
            if os.path.exists(banner_path):
                b_img = Image.open(banner_path).convert("RGB")
                bh = int(b_img.height * (W / b_img.width))
                pg.paste(b_img.resize((W, bh), Image.Resampling.LANCZOS), (0, 0))
                y_cursor = bh
            dr.rectangle([0, y_cursor, W, y_cursor + 6], fill=(138, 43, 226))
            y_cursor += 28
            dr.text((ML, y_cursor), title, font=f_title, fill=(24, 16, 48))
            y_cursor += 38
            dr.text((ML, y_cursor), subtitle, font=f_sub, fill=(112, 116, 134))
            y_cursor += 34
            return pg, dr, y_cursor
        else:
            dr.rectangle([0, 0, W, 8], fill=(138, 43, 226))
            return pg, dr, MT

    page, draw, y = new_page(first=True)
    pages.append(page)

    line_h = 27
    for sec_title, paragraphs in sections:
        if y + 84 > H - MB:
            page, draw, y = new_page(first=False)
            pages.append(page)

        draw.text((ML, y), sec_title, font=f_sec, fill=(72, 24, 148))
        y += 32
        draw.line([(ML, y), (W - MR, y)], fill=(230, 222, 248), width=2)
        y += 14

        for para in paragraphs:
            is_bullet = para.startswith("•")
            indent = 16 if is_bullet else 0
            wrapped = _wrap_text(draw, para, f_body, CONTENT_W - indent)
            for ln in wrapped:
                if y + line_h > H - MB:
                    page, draw, y = new_page(first=False)
                    pages.append(page)
                draw.text((ML + indent, y), ln, font=f_body, fill=(32, 34, 44))
                y += line_h
            y += 9
        y += 12

    total_pages = len(pages)
    for idx, pg in enumerate(pages, start=1):
        dr = ImageDraw.Draw(pg)
        dr.line([(ML, H - 64), (W - MR, H - 64)], fill=(228, 226, 238), width=1)
        dr.text((ML, H - 48), f"Bombych Store  •  Поддержка: {SUPPORT_USERNAME}", font=f_foot, fill=(125, 128, 145))
        pg_label = f"Стр. {idx} из {total_pages}"
        lbl_w = dr.textlength(pg_label, font=f_foot)
        dr.text((W - MR - lbl_w, H - 48), pg_label, font=f_foot, fill=(125, 128, 145))

    if total_pages == 1:
        pages[0].save(pdf_path, "PDF", resolution=120.0)
    else:
        pages[0].save(pdf_path, "PDF", resolution=120.0, save_all=True, append_images=pages[1:])


def _generate_legal_txt(txt_path: str, title: str, subtitle: str, sections: list[tuple[str, list[str]]]):
    lines = [
        "============================================================",
        f"BOMBYCH STORE — {title.upper()}",
        subtitle,
        "============================================================",
        "",
    ]
    for sec_title, paragraphs in sections:
        lines.append(sec_title)
        lines.append("------------------------------------------------------------")
        for p in paragraphs:
            lines.append(p)
            lines.append("")
        lines.append("")
    lines.append("============================================================")
    lines.append(f"Поддержка Bombych Store: {SUPPORT_USERNAME}")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def prepare_legal_documents():
    os.makedirs(IMG_DIR, exist_ok=True)
    reg_font, bold_font = _resolve_doc_fonts()
    use_pdf = bool(reg_font and bold_font)

    docs_spec = [
        (
            "terms",
            "terms.jpg",
            "Пользовательское соглашение",
            "Bombych Store • Актуальная редакция",
            TERMS_SECTIONS,
            "terms_doc",
            "Пользовательское_соглашение_BombychStore",
        ),
        (
            "privacy",
            "privacy.jpg",
            "Политика конфиденциальности",
            "Bombych Store • Актуальная редакция",
            PRIVACY_SECTIONS,
            "privacy_doc",
            "Политика_конфиденциальности_BombychStore",
        ),
    ]

    DOC_META.clear()
    for key, banner_name, title, subtitle, sections, disk_base, send_base in docs_spec:
        banner_path = os.path.join(IMG_DIR, banner_name)
        thumb_path = os.path.join(IMG_DIR, f"{key}_thumb.jpg")
        if os.path.exists(banner_path):
            _make_doc_thumbnail(banner_path, thumb_path)

        ext = ".pdf" if use_pdf else ".txt"
        disk_name = f"{disk_base}{ext}"
        disk_path = os.path.join(IMG_DIR, disk_name)
        send_name = f"{send_base}{ext}"

        if use_pdf:
            try:
                _generate_legal_pdf(disk_path, banner_path, title, subtitle, sections, reg_font, bold_font)
                logging.info(f"PDF-документ создан: {disk_name}")
            except Exception as e:
                logging.warning(f"Ошибка PDF {key}, переход на TXT: {e}")
                ext = ".txt"
                disk_name = f"{disk_base}{ext}"
                disk_path = os.path.join(IMG_DIR, disk_name)
                send_name = f"{send_base}{ext}"
                _generate_legal_txt(disk_path, title, subtitle, sections)
        else:
            _generate_legal_txt(disk_path, title, subtitle, sections)

        cache_key = f"doc:{key}"
        DOC_META[key] = {
            "disk_path": disk_path,
            "thumb_path": thumb_path,
            "send_name": send_name,
            "cache_key": cache_key,
        }
        h_doc = _file_md5(disk_path)
        h_th = _file_md5(thumb_path) if os.path.exists(thumb_path) else ""
        FILE_HASHES[cache_key] = f"{h_doc}:{h_th}"


def _make_fallback_logo() -> Image.Image:
    sz = 360
    im = Image.new("RGBA", (sz, sz), (16, 6, 36, 255))
    dr = ImageDraw.Draw(im)
    for y in range(sz):
        k = math.sin((y / sz) * math.pi)
        dr.line([(0, y), (sz, y)], fill=(int(45 + 135 * k), int(15 + 55 * k), int(85 + 145 * k), 255))
    dr.text((34, 102), "Bombych", font=_load_bold_font(74), fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(160, 40, 240, 255))
    dr.text((88, 188), "Store", font=_load_bold_font(62), fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(160, 40, 240, 255))
    return im


def _build_atmospheric_sphere(logo_img: Image.Image, diameter: int, angle: float, tint_mode: str, opacity: float = 0.85) -> Image.Image:
    src = logo_img.convert("RGBA").resize((diameter, diameter), Image.Resampling.LANCZOS)
    r, g, b, a = src.split()
    if tint_mode == "red":
        src = Image.merge("RGBA", (b, g.point(lambda p: p // 3), r.point(lambda p: p // 4), a))
    elif tint_mode == "cyan":
        src = Image.merge("RGBA", (g.point(lambda p: int(p * 0.6)), b, b, a))
    elif tint_mode == "gold":
        src = Image.merge("RGBA", (b, b.point(lambda p: int(p * 0.72)), g.point(lambda p: p // 3), a))
    elif tint_mode == "emerald":
        src = Image.merge("RGBA", (g.point(lambda p: p // 2), b, g.point(lambda p: int(p * 0.7)), a))

    src = src.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse([2, 2, diameter - 2, diameter - 2], fill=int(255 * opacity))

    shade = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shade)
    cx = cy = rad = diameter // 2
    for step in range(rad, int(rad * 0.68), -3):
        ratio = (step / rad - 0.68) / 0.32
        s_draw.ellipse([cx - step, cy - step, cx + step, cy + step], outline=(4, 2, 14, int((ratio ** 1.7) * 200)), width=4)

    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return Image.alpha_composite(out, shade)


def _draw_foreground_foliage_and_grass(base: Image.Image, pal: dict, rng: random.Random):
    w, h = base.size
    fg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(fg)
    rdraw = ImageDraw.Draw(rim)

    dark_sil = (3, 4, 12, 248)
    mid_sil = (6, 8, 22, 215)
    rim_l = (*pal["corner_left"], 110)
    rim_r = (*pal["corner_right"], 110)
    rim_c = (*pal["glow"], 95)

    for side in ("left", "right"):
        for i in range(42):
            if side == "left":
                cx = rng.randint(-30, 125)
                rx = rng.randint(24, 65)
                rc = rim_l
                edge_shift = 5
            else:
                cx = rng.randint(w - 125, w + 30)
                rx = rng.randint(24, 65)
                rc = rim_r
                edge_shift = -5
            cy = rng.randint(-20, h + 15)
            ry = rng.randint(20, 55)
            rdraw.ellipse([cx - rx + edge_shift, cy - ry, cx + rx + edge_shift, cy + ry], fill=rc)
            fdraw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=dark_sil if i % 2 == 0 else mid_sil)

        for _ in range(38):
            if side == "left":
                x0 = rng.randint(25, 110)
                x1 = x0 + rng.randint(25, 90)
                rc = rim_l
            else:
                x0 = rng.randint(w - 110, w - 25)
                x1 = x0 - rng.randint(25, 90)
                rc = rim_r
            y0 = rng.randint(10, h - 20)
            y1 = y0 + rng.randint(-40, 35)
            xm, ym = (x0 + x1) // 2, (y0 + y1) // 2 - rng.randint(4, 14)
            rdraw.polygon([(x0, y0 - 4), (xm, ym - 4), (x1, y1), (xm, ym + 4), (x0, y0 + 5)], fill=rc)
            fdraw.polygon([(x0, y0 - 3), (xm, ym - 3), (x1, y1), (xm, ym + 3), (x0, y0 + 4)], fill=dark_sil)

    for b_idx in range(6):
        bx = int(w * (0.28 + b_idx * 0.085) + rng.randint(-25, 25))
        length = rng.randint(65, 135)
        angle = math.radians(rng.uniform(72, 118))
        ex = bx + int(math.cos(angle) * length)
        ey = int(math.sin(angle) * length)
        fdraw.line([(bx, -10), (ex, ey)], fill=dark_sil, width=5)
        steps = rng.randint(16, 26)
        for s in range(steps):
            t = s / steps
            px = int(bx + (ex - bx) * t)
            py = int(-10 + (ey + 10) * t)
            for side_sign in (-1, 1):
                na = angle + side_sign * math.radians(rng.uniform(22, 52))
                nl = rng.randint(18, 42) * (1.0 - 0.35 * t)
                nx = px + int(math.cos(na) * nl)
                ny = py + int(math.sin(na) * nl)
                rdraw.line([(px, py + 1), (nx, ny + 1)], fill=rim_c, width=2)
                fdraw.line([(px, py), (nx, ny)], fill=dark_sil, width=2)

    for _ in range(135):
        gx = rng.randint(-10, w + 10)
        dist_center = abs(gx - w / 2) / (w / 2)
        max_h = int(52 + 65 * (dist_center ** 1.3))
        gh = rng.randint(24, max_h)
        lean = rng.randint(-38, 38)
        bw = rng.randint(3, 7)
        tip_x, tip_y = gx + lean, h - gh
        mid_x, mid_y = gx + lean // 2, h - int(gh * 0.55)
        r_col = rim_l if gx < w * 0.35 else (rim_r if gx > w * 0.65 else rim_c)
        rdraw.polygon([(gx - bw, h + 4), (mid_x - 2, mid_y), (tip_x, tip_y - 2), (mid_x + 2, mid_y), (gx + bw, h + 4)], fill=r_col)
        fdraw.polygon([(gx - bw, h + 4), (mid_x - 1, mid_y), (tip_x, tip_y), (mid_x + 2, mid_y), (gx + bw, h + 4)], fill=dark_sil)

    base.alpha_composite(rim.filter(ImageFilter.GaussianBlur(3.2)))
    base.alpha_composite(fg.filter(ImageFilter.GaussianBlur(1.1)))


def _render_chisel_3d_text(canvas: Image.Image, line1: str, line2: str, pal: dict):
    w, h = canvas.size
    text_mask = Image.new("L", (w, h), 0)
    mdraw = ImageDraw.Draw(text_mask)
    max_text_w = w - 90

    if line2:
        f1, b1 = _fit_font(mdraw, line1, max_text_w, 104 if len(line1) <= 9 else 84)
        f2, b2 = _fit_font(mdraw, line2, max_text_w, 86 if len(line2) <= 10 else 72)
        w1, h1, w2, h2 = b1[2] - b1[0], b1[3] - b1[1], b2[2] - b2[0], b2[3] - b2[1]
        gap = 18
        x1 = (w - w1) // 2 - b1[0]
        y1 = (h - (h1 + h2 + gap)) // 2 - b1[1] - 4
        x2 = (w - w2) // 2 - b2[0]
        y2 = y1 + b1[1] + h1 + gap - b2[1]
        mdraw.text((x1, y1), line1, font=f1, fill=255)
        mdraw.text((x2, y2), line2, font=f2, fill=255)
    else:
        start_sz = 146 if len(line1) <= 7 else (112 if len(line1) <= 10 else 92)
        f1, b1 = _fit_font(mdraw, line1, max_text_w, start_sz)
        w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
        mdraw.text(((w - w1) // 2 - b1[0], (h - h1) // 2 - b1[1] - 4), line1, font=f1, fill=255)

    neon_mask = text_mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(12))
    neon_layer = Image.new("RGBA", (w, h), (*pal["glow"], 0))
    neon_layer.putalpha(neon_mask.point(lambda p: int(p * 0.72)))
    canvas.alpha_composite(neon_layer)

    sh_mask = text_mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(6))
    sh_layer = Image.new("RGBA", (w, h), (4, 2, 12, 0))
    sh_layer.putalpha(sh_mask.point(lambda p: int(p * 0.85)))
    canvas.alpha_composite(sh_layer, dest=(0, 6))

    st_layer = Image.new("RGBA", (w, h), (*pal["stroke"], 255))
    st_layer.putalpha(text_mask.filter(ImageFilter.MaxFilter(5)))
    canvas.alpha_composite(st_layer)

    height_map = Image.new("L", (w, h), 0)
    cur = text_mask
    for _ in range(8):
        height_map = ImageChops.add(height_map, cur.point(lambda p: 31 if p > 128 else 0))
        cur = cur.filter(ImageFilter.MinFilter(3))

    h_ul, h_dr = Image.new("L", (w, h), 0), Image.new("L", (w, h), 0)
    h_ul.paste(height_map, (-3, -3))
    h_dr.paste(height_map, (3, 3))
    light_f = ImageChops.subtract(h_dr, height_map).point(lambda p: min(255, int(p * 3.8)))
    dark_f = ImageChops.subtract(h_ul, height_map).point(lambda p: min(255, int(p * 3.8)))

    face = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(face)
    r1, g1, b1 = pal["text_top"]
    r2, g2, b2 = pal["text_bot"]
    for y in range(h):
        t = y / h
        fdraw.line([(0, y), (w, y)], fill=(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t), 255))
    face.putalpha(text_mask)
    canvas.alpha_composite(face)

    hl_layer = Image.new("RGBA", (w, h), (255, 240, 255, 0))
    hl_layer.putalpha(ImageChops.multiply(light_f, text_mask).point(lambda p: int(p * 0.85)))
    canvas.alpha_composite(hl_layer)

    dk_layer = Image.new("RGBA", (w, h), (*pal["stroke"], 0))
    dk_layer.putalpha(ImageChops.multiply(dark_f, text_mask).point(lambda p: int(p * 0.85)))
    canvas.alpha_composite(dk_layer)


def generate_scenic_banner(filepath: str, logo_img: Image.Image, theme: str, line1: str, line2: str):
    w, h = 900, 300
    pal = THEME_PALETTES.get(theme, THEME_PALETTES["purple_forest"])
    rng = random.Random(sum(ord(c) for c in f"{theme}_{line1}_{line2}"))

    base = Image.new("RGBA", (w, h), (*pal["bg"], 255))
    bdraw = ImageDraw.Draw(base)
    bg_r, bg_g, bg_b = pal["bg"]
    gl_r, gl_g, gl_b = pal["glow"]
    for y in range(h):
        t = math.sin((y / h) * math.pi)
        bdraw.line([(0, y), (w, y)], fill=(
            min(255, int(bg_r + gl_r * 0.24 * t)),
            min(255, int(bg_g + gl_g * 0.24 * t)),
            min(255, int(bg_b + gl_b * 0.28 * t)),
            255
        ))

    light_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(light_layer)
    ldraw.ellipse([-60, 125, 290, 360], fill=(*pal["corner_left"], 155))
    ldraw.ellipse([610, 95, 960, 355], fill=(*pal["corner_right"], 130))
    ldraw.ellipse([185, 20, 715, 295], fill=(*pal["glow"], 155))
    star_pts = [(465, 58), (542, 148), (690, 178), (558, 240), (590, 298),
                (448, 258), (275, 292), (332, 222), (235, 168), (378, 148)]
    ldraw.polygon(star_pts, fill=(*pal["star"], 215))
    base = Image.alpha_composite(base, light_layer.filter(ImageFilter.GaussianBlur(28)))

    spheres = [
        (295, -24, 215, -18, 1.8, 0.88),
        (455, 240, 145, 25, 2.5, 0.72),
        (690, 185, 185, -35, 2.2, 0.75),
    ]
    for sx, sy, diam, ang, br, op in spheres:
        orb = _build_atmospheric_sphere(logo_img, diam, ang, pal["tint_mode"], opacity=op)
        orb = orb.filter(ImageFilter.GaussianBlur(br))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.paste(orb, (sx, sy), orb)
        base = Image.alpha_composite(base, layer)

    sparks = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sp_draw = ImageDraw.Draw(sparks)
    for _ in range(42):
        px = rng.randint(40, w - 40)
        py = rng.randint(25, h - 25)
        pr = rng.randint(2, 6)
        alpha = rng.randint(90, 220)
        sp_draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(*pal["spark"], alpha))
    base = Image.alpha_composite(base, sparks.filter(ImageFilter.GaussianBlur(1.6)))

    _draw_foreground_foliage_and_grass(base, pal, rng)
    _render_chisel_3d_text(base, line1, line2, pal)
    base.convert("RGB").save(filepath, "JPEG", quality=82, optimize=True)


def _compute_assets_stamp() -> str:
    h = hashlib.md5()
    h.update((_resolve_font_path() or "default").encode("utf-8"))
    for img_name, theme, (t1, t2) in SERVICE_BANNERS:
        h.update(f"{img_name}:{theme}:{t1}:{t2}".encode("utf-8"))
    for d in (os.path.join(BASE_DIR, "img"), os.path.join(BASE_DIR, "images")):
        if os.path.isdir(d):
            for fname in sorted(os.listdir(d)):
                fp = os.path.join(d, fname)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    h.update(f"{fname}:{st.st_size}:{int(st.st_mtime)}".encode("utf-8"))
    return h.hexdigest()


def target_not_uploaded(img_name: str) -> bool:
    cands = USER_UPLOADED_MAP.get(img_name, [])
    return _find_user_file(cands) is None if cands else True


def prepare_all_banners():
    cleanup_old_files()
    os.makedirs(IMG_DIR, exist_ok=True)

    stamp_file = os.path.join(IMG_DIR, ".stamp")
    current_stamp = _compute_assets_stamp()
    need_rebuild = True
    if os.path.exists(stamp_file):
        try:
            with open(stamp_file, "r", encoding="utf-8") as f:
                if f.read().strip() == current_stamp:
                    need_rebuild = False
        except OSError:
            pass

    if need_rebuild:
        lp = _find_user_file(USER_UPLOADED_MAP["logo.jpg"])
        logo_img = Image.open(lp).convert("RGBA") if lp else _make_fallback_logo()

        for target, candidates in USER_UPLOADED_MAP.items():
            if target != "logo.jpg":
                dest = os.path.join(IMG_DIR, target)
                found = _find_user_file(candidates)
                if found:
                    Image.open(found).convert("RGB").save(dest, "JPEG", quality=86, optimize=True)

        for _, _, _, img_name, theme, (t1, t2), _, _ in CATEGORIES_DATA:
            dest = os.path.join(IMG_DIR, img_name)
            found = _find_user_file([img_name, img_name.replace(".jpg", ".png")])
            if found:
                Image.open(found).convert("RGB").save(dest, "JPEG", quality=86, optimize=True)
            elif not os.path.exists(dest) or target_not_uploaded(img_name):
                generate_scenic_banner(dest, logo_img, theme, t1, t2)

        for img_name, theme, (t1, t2) in SERVICE_BANNERS:
            dest = os.path.join(IMG_DIR, img_name)
            found = _find_user_file([img_name, img_name.replace(".jpg", ".png")])
            if found:
                Image.open(found).convert("RGB").save(dest, "JPEG", quality=86, optimize=True)
            elif not os.path.exists(dest) or target_not_uploaded(img_name):
                generate_scenic_banner(dest, logo_img, theme, t1, t2)

        with open(stamp_file, "w", encoding="utf-8") as f:
            f.write(current_stamp)

    FILE_HASHES.clear()
    for fname in os.listdir(IMG_DIR):
        if fname.endswith((".jpg", ".png")) and not fname.endswith("_thumb.jpg"):
            FILE_HASHES[fname] = _file_md5(os.path.join(IMG_DIR, fname))

    prepare_legal_documents()


# ================= БАЗА ДАННЫХ И RAM-КЭШИРОВАНИЕ =================
async def init_db_and_cache():
    global DB_CONN
    DB_CONN = await aiosqlite.connect(DB_PATH, timeout=15)
    await DB_CONN.execute("PRAGMA journal_mode=WAL")
    await DB_CONN.execute("PRAGMA synchronous=NORMAL")
    await DB_CONN.execute("PRAGMA busy_timeout=5000")
    await DB_CONN.execute("PRAGMA temp_store=MEMORY")

    async with DB_LOCK:
        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0,
                joined_at TEXT,
                accepted_terms INTEGER DEFAULT 0
            )
        """)
        async with DB_CONN.execute("PRAGMA table_info(users)") as cur:
            user_cols = {row[1] for row in await cur.fetchall()}
        if "accepted_terms" not in user_cols:
            await DB_CONN.execute("ALTER TABLE users ADD COLUMN accepted_terms INTEGER DEFAULT 0")

        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY,
                short_name TEXT NOT NULL,
                full_title TEXT NOT NULL,
                image_name TEXT,
                description TEXT
            )
        """)
        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                full_name TEXT NOT NULL,
                btn_label TEXT NOT NULL,
                old_price REAL NOT NULL,
                price REAL NOT NULL,
                image_name TEXT
            )
        """)
        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_name TEXT,
                price REAL,
                pay_method TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS media_cache_v2 (
                image_name TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_hash TEXT NOT NULL
            )
        """)
        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        async with DB_CONN.execute("SELECT COUNT(*) FROM categories") as cur:
            cat_count = (await cur.fetchone())[0]

        if cat_count == 0:
            for cid, short_n, full_t, cimg, _, _, cdesc, items in CATEGORIES_DATA:
                await DB_CONN.execute(
                    "INSERT INTO categories (id, short_name, full_title, image_name, description) VALUES (?, ?, ?, ?, ?)",
                    (cid, short_n, full_t, cimg, cdesc)
                )
                for fname, short_btn, old_p, new_p in items:
                    btn_lbl = short_btn if "₽" in short_btn else f"{short_btn} • {new_p}₽"
                    await DB_CONN.execute(
                        "INSERT INTO products (category_id, full_name, btn_label, old_price, price, image_name) VALUES (?, ?, ?, ?, ?, ?)",
                        (cid, fname, btn_lbl, old_p, new_p, cimg)
                    )
        else:
            async with DB_CONN.execute("SELECT value FROM settings WHERE key = 'catalog_ver'") as cur:
                row = await cur.fetchone()
                cur_ver = row[0] if row else None

            if cur_ver != CATALOG_SCHEMA_VERSION:
                for cid, short_n, full_t, cimg, _, _, cdesc, items in CATEGORIES_DATA:
                    async with DB_CONN.execute("SELECT 1 FROM categories WHERE id = ?", (cid,)) as c2:
                        exists = await c2.fetchone()
                    if exists:
                        await DB_CONN.execute(
                            "UPDATE categories SET short_name = ?, full_title = ?, image_name = ?, description = ? WHERE id = ?",
                            (short_n, full_t, cimg, cdesc, cid)
                        )
                    else:
                        await DB_CONN.execute(
                            "INSERT INTO categories (id, short_name, full_title, image_name, description) VALUES (?, ?, ?, ?, ?)",
                            (cid, short_n, full_t, cimg, cdesc)
                        )
                        for fname, short_btn, old_p, new_p in items:
                            btn_lbl = short_btn if "₽" in short_btn else f"{short_btn} • {new_p}₽"
                            await DB_CONN.execute(
                                "INSERT INTO products (category_id, full_name, btn_label, old_price, price, image_name) VALUES (?, ?, ?, ?, ?, ?)",
                                (cid, fname, btn_lbl, old_p, new_p, cimg)
                            )

        await DB_CONN.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('catalog_ver', ?)",
            (CATALOG_SCHEMA_VERSION,)
        )
        await DB_CONN.commit()

        PHOTO_CACHE.clear()
        DOC_CACHE.clear()
        async with DB_CONN.execute("SELECT image_name, file_id, file_hash FROM media_cache_v2") as cur:
            for item_key, fid, fhash in await cur.fetchall():
                if FILE_HASHES.get(item_key) == fhash:
                    if item_key.startswith("doc:"):
                        DOC_CACHE[item_key] = fid
                    else:
                        PHOTO_CACHE[item_key] = fid

        KNOWN_USERS.clear()
        ACCEPTED_USERS.clear()
        async with DB_CONN.execute("SELECT user_id, COALESCE(accepted_terms, 0) FROM users") as cur:
            for uid, acc in await cur.fetchall():
                KNOWN_USERS.add(uid)
                if acc == 1:
                    ACCEPTED_USERS.add(uid)

    logging.info(f"БД загружена ({DB_PATH}): участников={len(KNOWN_USERS)}, приняли условия={len(ACCEPTED_USERS)}")
    await reload_catalog_cache()


async def reload_catalog_cache():
    global RAM_CATALOG_KB, RAM_FORTNITE_KB
    RAM_CATS.clear()
    RAM_CAT_ORDER.clear()
    RAM_PRODS.clear()
    RAM_CAT_KBS.clear()
    RAM_CAT_CAPTIONS.clear()

    async with DB_LOCK:
        async with DB_CONN.execute("SELECT id, short_name, full_title, image_name, description FROM categories ORDER BY id") as cur:
            cats = await cur.fetchall()
        async with DB_CONN.execute("SELECT id, category_id, full_name, btn_label, old_price, price, image_name FROM products ORDER BY id") as cur:
            all_prods = await cur.fetchall()

    cat_builder = InlineKeyboardBuilder()
    cat_builder.button(text="🎮 Fortnite", callback_data="nav_fortnite")
    fn_builder = InlineKeyboardBuilder()

    for cid, sname, ftitle, cimg, cdesc in cats:
        RAM_CAT_ORDER.append(cid)
        RAM_CATS[cid] = {
            "id": cid, "short_name": sname, "full_title": ftitle,
            "image_name": cimg, "description": cdesc
        }
        if cid in FORTNITE_CAT_IDS:
            fn_builder.button(text=sname, callback_data=f"cat_{cid}")
        else:
            cat_builder.button(text=sname, callback_data=f"cat_{cid}")

    cat_builder.adjust(2)
    cat_builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home"))
    RAM_CATALOG_KB = cat_builder.as_markup()

    fn_builder.adjust(2, 1)
    fn_builder.row(InlineKeyboardButton(text="🧶 Инструкция по привязке Xbox", callback_data="nav_xbox"))
    fn_builder.row(
        InlineKeyboardButton(text="⬅️ В каталог", callback_data="nav_catalog"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home")
    )
    RAM_FORTNITE_KB = fn_builder.as_markup()

    prods_by_cat: dict[int, list] = {cid: [] for cid in RAM_CAT_ORDER}
    for pid, cid, fname, btn_lbl, old_p, price, pimg in all_prods:
        prod_obj = {
            "id": pid, "category_id": cid, "full_name": fname,
            "btn_label": btn_lbl, "old_price": old_p, "price": price, "image_name": pimg
        }
        RAM_PRODS[pid] = prod_obj
        prods_by_cat.setdefault(cid, []).append(prod_obj)

    for cid, cat in RAM_CATS.items():
        items = prods_by_cat.get(cid, [])
        pb = InlineKeyboardBuilder()
        lines = []
        for p in items:
            pb.button(text=p["btn_label"], callback_data=f"prod_{p['id']}")
            lines.append(f"▫️ <b>{html.escape(p['full_name'])}</b> — <s>{p['old_price']:.0f}₽</s> <b><code>{p['price']:.0f} ₽</code></b>")
        pb.adjust(2)
        if cid in (1, 3):
            pb.row(InlineKeyboardButton(text="🧶 Инструкция по привязке Xbox", callback_data="nav_xbox"))
        if cid in FORTNITE_CAT_IDS:
            pb.row(
                InlineKeyboardButton(text="⬅️ К Fortnite", callback_data="nav_fortnite"),
                InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home")
            )
        else:
            pb.row(
                InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_catalog"),
                InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home")
            )
        RAM_CAT_KBS[cid] = pb.as_markup()
        RAM_CAT_CAPTIONS[cid] = (
            f"<b>{cat['full_title']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{cat['description']}\n\n"
            f"<blockquote>" + "\n".join(lines) + "</blockquote>\n"
            f"👇 <b>Выберите нужную позицию:</b>"
        )


async def _save_file_id_bg(cache_key: str, file_id: str):
    try:
        fhash = FILE_HASHES.get(cache_key, "")
        async with DB_LOCK:
            await DB_CONN.execute(
                "INSERT OR REPLACE INTO media_cache_v2 (image_name, file_id, file_hash) VALUES (?, ?, ?)",
                (cache_key, file_id, fhash)
            )
            await DB_CONN.commit()
    except Exception as e:
        logging.debug(f"Не удалось сохранить file_id для {cache_key}: {e}")


def _clean_username(uname: str | None) -> str:
    if not uname:
        return ""
    u = uname.strip().lstrip("@")
    if not u or u.lower() in ("клиент", "none", "без_ника"):
        return ""
    if re.fullmatch(r"[A-Za-z0-9_]{3,64}", u):
        return u
    return ""


async def register_user(user, force_update: bool = False):
    uname = user.username or ""
    fname = user.first_name or "Гость"

    if user.id in KNOWN_USERS and not force_update:
        return

    is_new = user.id not in KNOWN_USERS
    KNOWN_USERS.add(user.id)
    try:
        async with DB_LOCK:
            if is_new:
                await DB_CONN.execute(
                    "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, accepted_terms) VALUES (?, ?, ?, ?, 0)",
                    (user.id, uname, fname, datetime.now().strftime("%d.%m.%Y"))
                )
            await DB_CONN.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (uname, fname, user.id)
            )
            await DB_CONN.commit()
    except Exception as e:
        if is_new:
            KNOWN_USERS.discard(user.id)
        logging.warning(f"Ошибка регистрации пользователя {user.id}: {e}")


async def set_user_accepted(user, accepted: bool):
    uname = user.username or ""
    fname = user.first_name or "Гость"
    val = 1 if accepted else 0
    now_date = datetime.now().strftime("%d.%m.%Y")

    async with DB_LOCK:
        await DB_CONN.execute(
            """
            INSERT INTO users (user_id, username, first_name, joined_at, accepted_terms)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                accepted_terms = excluded.accepted_terms
            """,
            (user.id, uname, fname, now_date, val)
        )
        await DB_CONN.commit()

    KNOWN_USERS.add(user.id)
    if accepted:
        ACCEPTED_USERS.add(user.id)
    else:
        ACCEPTED_USERS.discard(user.id)


# ================= БЫСТРАЯ ОТРИСОВКА ЭКРАНОВ =================
def _is_duplicate_click(user_id: int, data: str | None) -> bool:
    if not data:
        return False
    now = time.monotonic()
    if len(LAST_CLICK) > 4000:
        cutoff = now - 5.0
        for k in [k for k, v in LAST_CLICK.items() if v < cutoff]:
            LAST_CLICK.pop(k, None)
    key = (user_id, data)
    prev = LAST_CLICK.get(key, 0.0)
    if now - prev < 0.35:
        return True
    LAST_CLICK[key] = now
    return False


def _remember_screen(chat_id: int, message_id: int, tag: str):
    if len(LAST_SCREEN_TAG) > 5000:
        for k in list(LAST_SCREEN_TAG.keys())[:2500]:
            LAST_SCREEN_TAG.pop(k, None)
    LAST_SCREEN_TAG[(chat_id, message_id)] = tag


async def _safe_delete(msg: Message | None):
    if not msg:
        return
    try:
        await msg.delete(request_timeout=5)
    except Exception:
        pass


async def _quick_answer(call: CallbackQuery, text: str | None = None, show_alert: bool = False):
    try:
        await call.answer(text=text, show_alert=show_alert, request_timeout=5)
    except Exception:
        pass


async def _send_fresh_photo(
    msg_target: Message,
    image_name: str,
    caption: str,
    kb: InlineKeyboardMarkup | None
):
    cached_fid = PHOTO_CACHE.get(image_name)
    media_file = cached_fid or FSInputFile(os.path.join(IMG_DIR, image_name))

    sent = await msg_target.answer_photo(
        photo=media_file, caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT
    )
    _remember_screen(sent.chat.id, sent.message_id, f"photo:{image_name}")
    if not cached_fid and sent.photo:
        fid = sent.photo[-1].file_id
        PHOTO_CACHE[image_name] = fid
        asyncio.create_task(_save_file_id_bg(image_name, fid))
    return sent


async def _send_fresh_doc(
    msg_target: Message,
    doc_key: str,
    caption: str,
    kb: InlineKeyboardMarkup | None
):
    meta = DOC_META[doc_key]
    cache_key = meta["cache_key"]
    cached_fid = DOC_CACHE.get(cache_key)

    if cached_fid:
        sent = await msg_target.answer_document(
            document=cached_fid, caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT
        )
    else:
        thumb = FSInputFile(meta["thumb_path"]) if os.path.exists(meta["thumb_path"]) else None
        sent = await msg_target.answer_document(
            document=FSInputFile(meta["disk_path"], filename=meta["send_name"]),
            thumbnail=thumb,
            caption=caption,
            reply_markup=kb,
            request_timeout=REQ_TIMEOUT
        )

    _remember_screen(sent.chat.id, sent.message_id, cache_key)
    if not cached_fid and sent.document:
        fid = sent.document.file_id
        DOC_CACHE[cache_key] = fid
        asyncio.create_task(_save_file_id_bg(cache_key, fid))
    return sent


async def show_doc_screen(
    target: Message | CallbackQuery,
    doc_key: str,
    caption: str,
    kb: InlineKeyboardMarkup
):
    meta = DOC_META[doc_key]
    cache_key = meta["cache_key"]

    if isinstance(target, CallbackQuery):
        asyncio.create_task(_quick_answer(target))
        msg = target.message
        if not msg:
            return
        chat_id, msg_id = msg.chat.id, msg.message_id

        if LAST_SCREEN_TAG.get((chat_id, msg_id)) == cache_key and msg.document:
            try:
                await msg.edit_caption(caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except Exception:
                pass

        if msg.document:
            cached_fid = DOC_CACHE.get(cache_key)
            if cached_fid:
                media = InputMediaDocument(media=cached_fid, caption=caption, parse_mode=ParseMode.HTML)
            else:
                thumb = FSInputFile(meta["thumb_path"]) if os.path.exists(meta["thumb_path"]) else None
                media = InputMediaDocument(
                    media=FSInputFile(meta["disk_path"], filename=meta["send_name"]),
                    thumbnail=thumb,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
            try:
                edited = await msg.edit_media(media=media, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                _remember_screen(chat_id, msg_id, cache_key)
                if not cached_fid and edited and edited.document:
                    fid = edited.document.file_id
                    DOC_CACHE[cache_key] = fid
                    asyncio.create_task(_save_file_id_bg(cache_key, fid))
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except Exception:
                pass

        LAST_SCREEN_TAG.pop((chat_id, msg_id), None)
        await _send_fresh_doc(msg, doc_key, caption, kb)
        asyncio.create_task(_safe_delete(msg))
    else:
        await _send_fresh_doc(target, doc_key, caption, kb)


async def show_screen(
    target: Message | CallbackQuery,
    image_name: str,
    caption: str,
    kb: InlineKeyboardMarkup,
    answer_cb: bool = True
):
    tag = f"photo:{image_name}"

    if isinstance(target, CallbackQuery):
        if answer_cb:
            asyncio.create_task(_quick_answer(target))
        msg = target.message
        if not msg:
            return
        chat_id, msg_id = msg.chat.id, msg.message_id
        has_photo = bool(msg.photo)

        if has_photo and LAST_SCREEN_TAG.get((chat_id, msg_id)) == tag:
            try:
                await msg.edit_caption(caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except TelegramRetryAfter as e:
                await asyncio.sleep(min(e.retry_after, 2.0))
                try:
                    await msg.edit_caption(caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                    return
                except Exception:
                    pass
            except Exception:
                pass

        if has_photo:
            cached_fid = PHOTO_CACHE.get(image_name)
            media_file = cached_fid or FSInputFile(os.path.join(IMG_DIR, image_name))
            try:
                edited = await msg.edit_media(
                    media=InputMediaPhoto(media=media_file, caption=caption, parse_mode=ParseMode.HTML),
                    reply_markup=kb,
                    request_timeout=REQ_TIMEOUT
                )
                _remember_screen(chat_id, msg_id, tag)
                if not cached_fid and edited and edited.photo:
                    fid = edited.photo[-1].file_id
                    PHOTO_CACHE[image_name] = fid
                    asyncio.create_task(_save_file_id_bg(image_name, fid))
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except TelegramRetryAfter as e:
                await asyncio.sleep(min(e.retry_after, 2.0))
            except Exception:
                pass

        LAST_SCREEN_TAG.pop((chat_id, msg_id), None)
        await _send_fresh_photo(msg, image_name, caption, kb)
        asyncio.create_task(_safe_delete(msg))
    else:
        await _send_fresh_photo(target, image_name, caption, kb)


async def show_dynamic_photo(
    call: CallbackQuery,
    photo_file_id: str | None,
    fallback_image: str,
    caption: str,
    kb: InlineKeyboardMarkup
):
    if not photo_file_id:
        await show_screen(call, fallback_image, caption, kb)
        return

    asyncio.create_task(_quick_answer(call))
    msg = call.message
    if not msg:
        return
    chat_id, msg_id = msg.chat.id, msg.message_id
    LAST_SCREEN_TAG.pop((chat_id, msg_id), None)

    if msg.photo:
        try:
            await msg.edit_media(
                media=InputMediaPhoto(media=photo_file_id, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=kb,
                request_timeout=REQ_TIMEOUT
            )
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return
        except Exception:
            pass

    try:
        await msg.answer_photo(photo=photo_file_id, caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
    except Exception:
        await _send_fresh_photo(msg, fallback_image, caption, kb)
    asyncio.create_task(_safe_delete(msg))


# ================= КЛАВИАТУРЫ =================
def reply_main_kb(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🛒 Каталог"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🧶 Привязка"), KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="📕 Правила")],
        [KeyboardButton(text="🆘 Поддержка")],
    ]
    if user_id == ADMIN_ID:
        rows[-1].append(KeyboardButton(text="⚙️ Админка"))
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="Меню Bombych Store...")


def inline_home_kb(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🛒 Каталог", callback_data="nav_catalog")
    b.button(text="👤 Профиль", callback_data="nav_profile")
    b.button(text="🧶 Привязка", callback_data="nav_xbox")
    b.button(text="ℹ️ Инфо", callback_data="nav_info")
    b.button(text="📕 Правила", callback_data="nav_rules")
    b.button(text="🆘 Поддержка", callback_data="nav_support")
    b.button(text="📄 Соглашение", callback_data="nav_terms")
    b.button(text="🔒 Политика", callback_data="nav_privacy")
    b.adjust(2, 2, 2, 2)
    if user_id == ADMIN_ID:
        b.row(InlineKeyboardButton(text="⚙️ Панель управления", callback_data="nav_admin"))
    return b.as_markup()


HOME_KB_USER = inline_home_kb(0)
HOME_KB_ADMIN = inline_home_kb(ADMIN_ID)

GATE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📄 Пользовательское соглашение", callback_data="gate_terms")],
    [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="gate_privacy")],
    [InlineKeyboardButton(text="✅ Принимаю условия", callback_data="legal_accept")],
    [InlineKeyboardButton(text="❌ Отказаться и выйти", callback_data="legal_decline")],
])

GATE_DOC_KB = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📄 Соглашение", callback_data="gate_terms"),
        InlineKeyboardButton(text="🔒 Политика", callback_data="gate_privacy"),
    ],
    [
        InlineKeyboardButton(text="✅ Принимаю условия", callback_data="legal_accept"),
        InlineKeyboardButton(text="❌ Отказаться", callback_data="legal_decline"),
    ],
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="gate_back")],
])

INFO_KB = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📄 Соглашение", callback_data="nav_terms"),
        InlineKeyboardButton(text="🔒 Политика", callback_data="nav_privacy")
    ],
    [
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="nav_support"),
        InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")
    ],
    [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="nav_home")]
])

RULES_KB = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📄 Соглашение", callback_data="nav_terms"),
        InlineKeyboardButton(text="🔒 Политика", callback_data="nav_privacy")
    ],
    [
        InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_home"),
        InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")
    ]
])

LEGAL_KB = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📄 Соглашение", callback_data="nav_terms"),
        InlineKeyboardButton(text="🔒 Политика", callback_data="nav_privacy")
    ],
    [
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="nav_support"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")
    ]
])

SUPPORT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=f"💬 Написать нам ({SUPPORT_USERNAME})", url=SUPPORT_LINK)],
    [
        InlineKeyboardButton(text="⬅️ Главное меню", callback_data="nav_home"),
        InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")
    ]
])

BACK_XBOX_KB = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="⬅️ В Fortnite", callback_data="nav_fortnite"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home")
    ]
])


# ================= ТЕКСТЫ ВИТРИНЫ И ДОКУМЕНТОВ =================
SAFE_SUPPORT_USER = html.escape(SUPPORT_USERNAME)

GATE_TEXT = (
    "💜 <b>Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>Чтобы начать пользоваться магазином, подтвердите согласие с "
    "<b>Пользовательским соглашением</b> и <b>Политикой конфиденциальности</b>.</blockquote>\n"
    "👇 Вы можете открыть файлы документов ниже или сразу перейти в магазин:"
)

TERMS_DOC_CAPTION = (
    "📄 <b>Пользовательское соглашение • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>Правила оформления, оплаты и выдачи заказов (05:00–22:00 МСК), "
    "условия возврата цифровых товаров и ответственность сторон.</blockquote>\n"
    "👆 <b>Нажмите на файл выше, чтобы открыть полный документ.</b>"
)

PRIVACY_DOC_CAPTION = (
    "🔒 <b>Политика конфиденциальности • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>Порядок сбора, хранения и защиты данных, запрет на передачу третьим лицам "
    "и правила удаления вашего профиля.</blockquote>\n"
    "👆 <b>Нажмите на файл выше, чтобы открыть полный документ.</b>"
)

HOME_TEXT = (
    "💜 <b>Bombych Store • Магазин игрового доната</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>🎮 <b>Fortnite:</b> В-Баксы, В-Баксы подарком и Наборы\n"
    "🌴 <b>Новинка:</b> GTA VI для PlayStation и Xbox\n"
    "📱 <b>Игры:</b> Brawl Stars, Roblox, Genshin, Standoff 2, Clash Royale, CoC, Free Fire, PUBG, Вирты\n"
    "💻 <b>Сервисы:</b> Telegram (Premium и Звёзды), Steam, Discord Nitro, ChatGPT, Spotify, ExitLag, Банки</blockquote>\n"
    "⏰ <b>График выдачи:</b> <code>05:00 – 22:00 (МСК)</code>\n"
    "⚡ Прием заказов через бота — <b>круглосуточно (24/7)</b>\n\n"
    "👇 <b>Выберите нужный раздел:</b>"
)

CATALOG_TEXT = (
    "🛒 <b>Каталог • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>🔥 <b>Выгодные цены</b> на игры, донат и подписки\n"
    "🛡 Официальное пополнение и 100% гарантия выдачи\n"
    "⚡ Быстрая обработка заказа сразу после оплаты</blockquote>\n"
    "👇 <b>Выберите интересующую категорию:</b>"
)

FORTNITE_TEXT = (
    "🎮 <b>Fortnite • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>💎 <b>В-Баксы</b> — официальное пополнение на ваш аккаунт\n"
    "🎁 <b>ВБ подарком</b> — скины, кирки и эмоции подарком из магазина\n"
    "📦 <b>Наборы</b> — Отряд Fortnite, стартер-паки, БП и игры Epic</blockquote>\n"
    "👇 <b>Выберите нужный раздел Fortnite:</b>"
)

INFO_TEXT = (
    "❗ <b>Информация • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "⏰ <b>Время работы:</b> <code>05:00 — 22:00 (МСК)</code>\n\n"
    "📌 <b>Безопасность и конфиденциальность:</b>\n"
    "<blockquote>Мы не сохраняем данные от ваших аккаунтов после выполнения заказа. "
    "Вся информация используется исключительно для зачисления доната и сразу удаляется. "
    "Безопасность ваших аккаунтов и ресурсов — наш главный приоритет.</blockquote>\n"
    "➡️ <i>Оформить и оплатить заказ можно в любое время суток — выдача производится сразу в рабочие часы!</i>"
)

RULES_TEXT = (
    "📕 <b>Правила • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<b>1. Уважение</b>\n"
    "<blockquote>Общайтесь вежливо с поддержкой и администрацией магазина.</blockquote>\n"
    "<b>2. Оформление заказов</b>\n"
    "<blockquote>Не дублируйте заявки и прикрепляйте только действительные чеки об оплате.</blockquote>\n"
    "<b>3. Гарантии магазина</b>\n"
    "<blockquote>Мы принимаем платежи через указанные методы, обеспечивая безопасность ваших данных, "
    "и гарантируем полную выдачу оплаченного товара.</blockquote>"
)

SUPPORT_TEXT = (
    "🆘 <b>Поддержка • Bombych Store</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote>По любым вопросам — помощь с выбором товара, оплата, статус заказа, "
    "привязка аккаунта, возврат или сотрудничество — обращайтесь к нам в Telegram.</blockquote>\n"
    f"👤 <b>Контакт поддержки:</b> {SAFE_SUPPORT_USER}\n"
    "⏰ <b>Время ответа:</b> <code>05:00 – 22:00 (МСК)</code>\n\n"
    "👇 <b>Нажмите кнопку ниже, чтобы сразу написать нам:</b>"
)

XBOX_TEXT = (
    "✅ <b>Инструкция по привязке аккаунта Xbox</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<b>1.</b> Создайте учётную запись Microsoft (при регистрации укажите регион <b>«РОССИЯ»</b> и возраст <b>18+</b>):\n"
    "🔗 <a href='https://www.microsoft.com/ru-ru'>microsoft.com/ru-ru</a>\n\n"
    "<b>2.</b> В личном кабинете Epic Games откройте вкладку <b>«Соединения» → XBOX → Подключить</b>:\n"
    "🔗 <a href='https://www.epicgames.com/account/connections'>epicgames.com/account/connections</a>\n\n"
    "<b>3.</b> Готово! Теперь вы можете приобретать В-Баксы и наборы Fortnite.\n\n"
    "<blockquote>⛔ Если появилась ошибка авторизации сторонней системы, откройте "
    "<a href='https://www.epicgames.com/help/ru/uchyotnye-zapisi-epic-c74/podklyuchit-uchyotnye-zapisi-c110/kak-ustranit-oshibku-pri-obrabotke-dannyh-poluchennyh-ot-storonnej-sistemy-avtorizacii-proizoshla-oshibka-obratites-v-podderzhku-a8580'>официальную инструкцию Epic Games</a> и выполните указанные шаги.</blockquote>"
)


# ================= ОДНОКРАТНОЕ СОГЛАСИЕ И ЗАЩИТА ОТ ДАБЛ-КЛИКОВ =================
async def send_consent_gate(message: Message):
    await _send_fresh_photo(message, "main.jpg", GATE_TEXT, GATE_KB)


class TermsGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        # Единая защита от случайного двойного нажатия одной и той же кнопки
        if isinstance(event, CallbackQuery):
            if _is_duplicate_click(user.id, event.data):
                await _quick_answer(event)
                return None

        if user.id in ACCEPTED_USERS:
            return await handler(event, data)

        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/start") or (user.id == ADMIN_ID and text.startswith("/reset_terms")):
                return await handler(event, data)
            await send_consent_gate(event)
            return None

        if isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            if cb_data in {"legal_accept", "legal_decline", "gate_terms", "gate_privacy", "gate_back"}:
                return await handler(event, data)
            await _quick_answer(
                event,
                "Сначала подтвердите согласие с Пользовательским соглашением и Политикой конфиденциальности.",
                show_alert=True
            )
            await show_screen(event, "main.jpg", GATE_TEXT, GATE_KB, answer_cb=False)
            return None

        return await handler(event, data)


router.message.middleware(TermsGateMiddleware())
router.callback_query.middleware(TermsGateMiddleware())


@router.callback_query(F.data == "gate_terms")
async def cb_gate_terms(call: CallbackQuery):
    await show_doc_screen(call, "terms", TERMS_DOC_CAPTION, GATE_DOC_KB)


@router.callback_query(F.data == "gate_privacy")
async def cb_gate_privacy(call: CallbackQuery):
    await show_doc_screen(call, "privacy", PRIVACY_DOC_CAPTION, GATE_DOC_KB)


@router.callback_query(F.data == "gate_back")
async def cb_gate_back(call: CallbackQuery):
    await show_screen(call, "main.jpg", GATE_TEXT, GATE_KB)


@router.callback_query(F.data == "legal_accept")
async def cb_legal_accept(call: CallbackQuery, state: FSMContext):
    asyncio.create_task(_quick_answer(call, "✅ Условия приняты!"))
    if await state.get_state():
        await state.clear()
    await set_user_accepted(call.from_user, True)

    msg = call.message
    if not msg:
        return
    uid = call.from_user.id
    LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)

    await msg.answer(
        "💜 <b>Добро пожаловать в официальный магазин Bombych Store!</b>",
        reply_markup=reply_main_kb(uid),
        request_timeout=REQ_TIMEOUT
    )
    kb = HOME_KB_ADMIN if uid == ADMIN_ID else HOME_KB_USER
    await _send_fresh_photo(msg, "main.jpg", HOME_TEXT, kb)
    asyncio.create_task(_safe_delete(msg))


@router.callback_query(F.data == "legal_decline")
async def cb_legal_decline(call: CallbackQuery, state: FSMContext):
    await _quick_answer(
        call,
        "Без принятия условий использование магазина невозможно.",
        show_alert=True
    )
    if await state.get_state():
        await state.clear()
    await set_user_accepted(call.from_user, False)

    msg = call.message
    if not msg:
        return
    LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)
    await msg.answer(
        "🚪 <b>Вы вышли из Bombych Store.</b>\n\n"
        "Для работы с магазином необходимо принять Пользовательское соглашение и Политику конфиденциальности.\n\n"
        "Чтобы вернуться — нажмите /start.",
        reply_markup=ReplyKeyboardRemove(),
        request_timeout=REQ_TIMEOUT
    )
    asyncio.create_task(_safe_delete(msg))


@router.message(Command("reset_terms"))
async def cmd_reset_terms(message: Message, state: FSMContext):
    """Служебная команда только для админа, чтобы повторно проверить окно первого входа."""
    if message.from_user.id != ADMIN_ID:
        return
    if await state.get_state():
        await state.clear()
    await set_user_accepted(message.from_user, False)
    await send_consent_gate(message)


# ================= НАВИГАЦИЯ =================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await register_user(message.from_user, force_update=True)

    if message.from_user.id not in ACCEPTED_USERS:
        await send_consent_gate(message)
        return

    kb = HOME_KB_ADMIN if message.from_user.id == ADMIN_ID else HOME_KB_USER
    await message.answer(
        "💜 <b>Добро пожаловать в официальный магазин Bombych Store!</b>",
        reply_markup=reply_main_kb(message.from_user.id),
        request_timeout=REQ_TIMEOUT
    )
    await show_screen(message, "main.jpg", HOME_TEXT, kb)


@router.callback_query(F.data == "nav_home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    kb = HOME_KB_ADMIN if call.from_user.id == ADMIN_ID else HOME_KB_USER
    await show_screen(call, "main.jpg", HOME_TEXT, kb)


@router.message(Command("catalog"))
@router.message(F.text == "🛒 Каталог")
async def msg_catalog(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(message, "catalog.jpg", CATALOG_TEXT, RAM_CATALOG_KB)


@router.callback_query(F.data == "nav_catalog")
async def cb_catalog(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(call, "catalog.jpg", CATALOG_TEXT, RAM_CATALOG_KB)


@router.callback_query(F.data == "nav_fortnite")
async def cb_fortnite(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(call, "fortnite.jpg", FORTNITE_TEXT, RAM_FORTNITE_KB)


@router.message(Command("info"))
@router.message(F.text.in_({"ℹ️ Инфо", "ℹ️ Информация"}))
async def msg_info(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(message, "info.jpg", INFO_TEXT, INFO_KB)


@router.callback_query(F.data == "nav_info")
async def cb_info(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(call, "info.jpg", INFO_TEXT, INFO_KB)


@router.message(Command("rules"))
@router.message(F.text == "📕 Правила")
async def msg_rules(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(message, "rules.jpg", RULES_TEXT, RULES_KB)


@router.callback_query(F.data == "nav_rules")
async def cb_rules(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(call, "rules.jpg", RULES_TEXT, RULES_KB)


@router.message(Command("terms"))
async def msg_terms(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_doc_screen(message, "terms", TERMS_DOC_CAPTION, LEGAL_KB)


@router.callback_query(F.data == "nav_terms")
async def cb_terms(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_doc_screen(call, "terms", TERMS_DOC_CAPTION, LEGAL_KB)


@router.message(Command("privacy"))
async def msg_privacy(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_doc_screen(message, "privacy", PRIVACY_DOC_CAPTION, LEGAL_KB)


@router.callback_query(F.data == "nav_privacy")
async def cb_privacy(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_doc_screen(call, "privacy", PRIVACY_DOC_CAPTION, LEGAL_KB)


@router.message(Command("xbox"))
@router.message(F.text.in_({"🧶 Привязка", "🧶 Привязка Xbox"}))
async def msg_xbox(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(message, "xbox.jpg", XBOX_TEXT, BACK_XBOX_KB)


@router.callback_query(F.data == "nav_xbox")
async def cb_xbox(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(call, "xbox.jpg", XBOX_TEXT, BACK_XBOX_KB)


@router.message(Command("support"))
@router.message(F.text == "🆘 Поддержка")
async def cmd_support(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(message, "support.jpg", SUPPORT_TEXT, SUPPORT_KB)


@router.callback_query(F.data == "nav_support")
async def cb_support(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    await show_screen(call, "support.jpg", SUPPORT_TEXT, SUPPORT_KB)


# ================= ПРОФИЛЬ И ИСТОРИЯ ЗАКАЗОВ =================
async def build_profile_view(user):
    await register_user(user)
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT balance, joined_at FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
        async with DB_CONN.execute(
            "SELECT COUNT(*), COALESCE(SUM(price), 0) FROM orders WHERE user_id = ? AND status = 'completed'",
            (user.id,)
        ) as cur:
            done_cnt, total_spent = await cur.fetchone()

    balance, joined_at = row if row else (0.0, datetime.now().strftime("%d.%m.%Y"))

    if user.id == ADMIN_ID:
        role = "Основатель ♦"
    elif done_cnt >= 5:
        role = "VIP Покупатель 👑"
    elif done_cnt > 0:
        role = "Покупатель 💲"
    else:
        role = "Клиент 🛴"

    safe_name = html.escape(user.first_name or "Гость")
    text = (
        f"👤 <b>Личный кабинет • {safe_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Ваш ID:</b> <code>{user.id}</code>\n"
        f"🎭 <b>Статус:</b> <b>{role}</b>\n"
        f"📅 <b>Дата регистрации:</b> <code>{joined_at}</code>\n\n"
        f"<blockquote>💰 <b>Баланс:</b> <code>{balance:.0f} ₽</code>\n"
        f"📦 <b>Выполнено заказов:</b> <code>{done_cnt} шт.</code>\n"
        f"💎 <b>Сумма покупок:</b> <code>{total_spent:.0f} ₽</code></blockquote>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"),
            InlineKeyboardButton(text="🛒 В каталог", callback_data="nav_catalog")
        ],
        [
            InlineKeyboardButton(text="⬅️ Главное меню", callback_data="nav_home")
        ]
    ])
    return text, kb


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def msg_profile(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    text, kb = await build_profile_view(message.from_user)
    await show_screen(message, "profile.jpg", text, kb)


@router.callback_query(F.data == "nav_profile")
async def cb_profile(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    text, kb = await build_profile_view(call.from_user)
    await show_screen(call, "profile.jpg", text, kb)


@router.callback_query(F.data == "my_orders")
async def cb_my_orders(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    async with DB_LOCK:
        async with DB_CONN.execute(
            "SELECT id, product_name, price, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 8",
            (call.from_user.id,)
        ) as cur:
            rows = await cur.fetchall()

    st_icons = {
        "pending": "⏳ Ожидает оплаты",
        "checking": "🔎 На проверке",
        "completed": "✅ Выдан",
        "rejected": "❌ Отклонен"
    }
    if not rows:
        body = "<i>У вас пока нет завершенных или активных заказов.</i>"
    else:
        body = "\n".join([
            f"• <b>#{oid}</b> | {html.escape(pname)} (<b>{price:.0f}₽</b>) — {st_icons.get(st, st)}"
            for oid, pname, price, st in rows
        ])

    text = f"📦 <b>История заказов</b>\n━━━━━━━━━━━━━━━━━━━━\n{body}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ Профиль", callback_data="nav_profile"),
            InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")
        ]
    ])
    await show_screen(call, "profile.jpg", text, kb)


# ================= КАТЕГОРИИ, ТОВАРЫ И ОПЛАТА =================
@router.callback_query(F.data.startswith("cat_"))
async def cb_category(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    try:
        cat_id = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        return await _quick_answer(call, "Раздел не найден", show_alert=True)

    cat = RAM_CATS.get(cat_id)
    if not cat:
        return await _quick_answer(call, "Раздел не найден", show_alert=True)

    await show_screen(call, cat["image_name"], RAM_CAT_CAPTIONS[cat_id], RAM_CAT_KBS[cat_id])


@router.callback_query(F.data.startswith("prod_"))
async def cb_product(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    try:
        pid = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        return await _quick_answer(call, "Товар не найден", show_alert=True)

    prod = RAM_PRODS.get(pid)
    if not prod:
        return await _quick_answer(call, "Товар не найден", show_alert=True)

    cat = RAM_CATS[prod["category_id"]]
    caption = (
        f"🛍 <b>Оформление заказа</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📂 Категория: <b>{cat['full_title']}</b>\n"
        f"💎 Товар: <b>{html.escape(prod['full_name'])}</b>\n"
        f"💰 Стоимость: <s>{prod['old_price']:.0f} ₽</s> <b><code>{prod['price']:.0f} ₽</code></b>\n\n"
        f"<blockquote>{cat['description']}</blockquote>\n"
        f"👇 <b>Выберите удобный способ оплаты:</b>"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🧡 DonationAlerts", callback_data=f"pay_da_{pid}")
    b.button(text="🪙 Криптовалюта", callback_data=f"pay_crypto_{pid}")
    b.button(text="💳 СБП / Карта", callback_data="pay_sbp_soon")
    b.button(text="⬅️ Назад", callback_data=f"cat_{prod['category_id']}")
    if prod["category_id"] in FORTNITE_CAT_IDS:
        b.button(text="🎮 Fortnite", callback_data="nav_fortnite")
    else:
        b.button(text="🛒 Каталог", callback_data="nav_catalog")
    b.adjust(2, 1, 2)
    await show_screen(call, prod["image_name"], caption, b.as_markup())


@router.callback_query(F.data == "pay_sbp_soon")
async def cb_sbp_soon(call: CallbackQuery):
    await _quick_answer(
        call,
        "⏳ Оплата по СБП в скором времени будет добавлена!\n"
        "Сейчас доступны DonationAlerts и Криптовалюта.",
        show_alert=True
    )


@router.callback_query(F.data.startswith(("pay_da_", "pay_crypto_")))
async def cb_pay(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    try:
        method, pid = parts[1], int(parts[2])
    except (IndexError, ValueError):
        return await _quick_answer(call, "Ошибка товара", show_alert=True)

    prod = RAM_PRODS.get(pid)
    if not prod:
        return await _quick_answer(call, "Товар не найден", show_alert=True)

    asyncio.create_task(_quick_answer(call))
    await register_user(call.from_user)

    m_name = "DonationAlerts" if method == "da" else "Криптовалюта (TON)"
    async with DB_LOCK:
        async with DB_CONN.execute(
            "INSERT INTO orders (user_id, product_name, price, pay_method, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (call.from_user.id, prod["full_name"], prod["price"], m_name, datetime.now().strftime("%d.%m.%Y %H:%M"))
        ) as cur:
            order_id = cur.lastrowid
        await DB_CONN.commit()

    await state.update_data(order_id=order_id, fname=prod["full_name"], price=prod["price"], pid=pid)
    pay_info = PAYMENT_DA_TEXT if method == "da" else PAYMENT_CRYPTO_TEXT

    caption = (
        f"🧾 <b>Счет на оплату • Заказ #{order_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Товар: <b>{html.escape(prod['full_name'])}</b>\n"
        f"💰 К оплате: <b><code>{prod['price']:.0f} ₽</code></b>\n\n"
        f"{pay_info}"
    )

    buttons = []
    if method == "da":
        buttons.append([InlineKeyboardButton(text="🧡 Перейти к оплате (DonationAlerts)", url=DONATIONALERTS_URL)])
    buttons.append([InlineKeyboardButton(text="📸 Отправить чек", callback_data=f"sendcheck_{order_id}_{pid}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"prod_{pid}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"cat_{prod['category_id']}")
    ])

    await show_screen(call, prod["image_name"], caption, InlineKeyboardMarkup(inline_keyboard=buttons), answer_cb=False)


@router.callback_query(F.data.startswith("sendcheck_"))
async def cb_sendcheck(call: CallbackQuery, state: FSMContext):
    asyncio.create_task(_quick_answer(call))
    parts = call.data.split("_")
    data = await state.get_data()

    try:
        order_id = int(parts[1])
    except (IndexError, ValueError):
        order_id = data.get("order_id", 0)

    try:
        pid = int(parts[2])
    except (IndexError, ValueError):
        pid = data.get("pid", 1)

    fname = data.get("fname")
    price = data.get("price")

    if (not fname or price is None) and order_id:
        async with DB_LOCK:
            async with DB_CONN.execute("SELECT product_name, price FROM orders WHERE id = ?", (order_id,)) as cur:
                row = await cur.fetchone()
        if row:
            fname, price = row

    await state.update_data(order_id=order_id, fname=fname or "Товар", price=price or 0, pid=pid)
    await state.set_state(OrderFlow.waiting_receipt)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ К товару", callback_data=f"prod_{pid}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="nav_home")
        ]
    ])
    await call.message.answer(
        f"📸 <b>Прикрепите скриншот или файл чека по заказу #{order_id} в этот чат.</b>\n"
        "<i>В подписи к файлу вы можете сразу указать игровой ID, UID, тег или почту для быстрого выполнения заказа.</i>",
        reply_markup=kb,
        request_timeout=REQ_TIMEOUT
    )


@router.message(OrderFlow.waiting_receipt, F.photo | F.document)
async def receive_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order_id = data.get("order_id", 0)
    fname = data.get("fname", "Товар")
    price = data.get("price", 0)
    comment = html.escape(message.caption or "Без комментария")
    await state.clear()

    if order_id:
        async with DB_LOCK:
            await DB_CONN.execute("UPDATE orders SET status = 'checking' WHERE id = ?", (order_id,))
            await DB_CONN.commit()

    adm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выдать заказ", callback_data=f"adm_ok_{order_id}_{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_no_{order_id}_{message.from_user.id}")
        ]
    ])
    safe_user = html.escape(message.from_user.username or "без_ника")
    adm_caption = (
        f"🔔 <b>Новый чек • Заказ #{order_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Клиент: @{safe_user} (<code>{message.from_user.id}</code>)\n"
        f"💎 Товар: <b>{html.escape(str(fname))}</b>\n"
        f"💰 Сумма: <b>{price:.0f} ₽</b>\n"
        f"💬 Комментарий: <blockquote>{comment}</blockquote>"
    )

    try:
        if message.photo:
            await bot.send_photo(
                chat_id=ADMIN_ID, photo=message.photo[-1].file_id,
                caption=adm_caption, reply_markup=adm_kb, request_timeout=REQ_TIMEOUT
            )
        else:
            await bot.send_document(
                chat_id=ADMIN_ID, document=message.document.file_id,
                caption=adm_caption, reply_markup=adm_kb, request_timeout=REQ_TIMEOUT
            )
    except Exception as e:
        logging.error(f"Не удалось переслать чек #{order_id} администратору: {e}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")
        ]
    ])
    await message.answer(
        f"✅ <b>Чек по заказу #{order_id} отправлен на проверку!</b>\n"
        "Уведомление о выполнении заказа придет в этот чат.",
        reply_markup=kb,
        request_timeout=REQ_TIMEOUT
    )


@router.message(OrderFlow.waiting_receipt)
async def wrong_receipt(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить отправку чека", callback_data="nav_home")]
    ])
    await message.answer(
        "⚠️ Пожалуйста, отправьте <b>скриншот, фотографию или файл</b> чека.",
        reply_markup=kb,
        request_timeout=REQ_TIMEOUT
    )


# ================= АДМИН-ПАНЕЛЬ И УЧАСТНИКИ =================
@router.callback_query(F.data.startswith("adm_ok_"))
async def cb_adm_ok(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    _, _, oid_s, uid_s = call.data.split("_")
    oid, uid = int(oid_s), int(uid_s)

    async with DB_LOCK:
        await DB_CONN.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (oid,))
        await DB_CONN.commit()

    try:
        await bot.send_message(
            chat_id=uid,
            text=(
                f"🎉 <b>Оплата по заказу #{oid} подтверждена!</b>\n"
                "Ваш заказ принят к выдаче. При необходимости уточнения данных администратор свяжется с вами в ЛС.\n"
                "💜 Спасибо за покупку в <b>Bombych Store</b>!"
            ),
            request_timeout=REQ_TIMEOUT
        )
    except Exception as e:
        logging.warning(f"Не удалось уведомить клиента {uid} о заказе #{oid}: {e}")

    try:
        await call.message.edit_caption(
            caption=(call.message.caption or "") + "\n\n✅ <b>ВЫПОЛНЕНО</b>",
            request_timeout=REQ_TIMEOUT
        )
    except Exception:
        pass
    await _quick_answer(call, "Заказ подтвержден!")


@router.callback_query(F.data.startswith("adm_no_"))
async def cb_adm_no(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    _, _, oid_s, uid_s = call.data.split("_")
    oid, uid = int(oid_s), int(uid_s)

    async with DB_LOCK:
        await DB_CONN.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        await DB_CONN.commit()

    try:
        await bot.send_message(
            chat_id=uid,
            text=f"❌ <b>Заказ #{oid} отклонен.</b>\nОплата не найдена. Проверьте чек или напишите нам в поддержку ({SAFE_SUPPORT_USER}).",
            request_timeout=REQ_TIMEOUT
        )
    except Exception as e:
        logging.warning(f"Не удалось уведомить клиента {uid} об отказе #{oid}: {e}")

    try:
        await call.message.edit_caption(
            caption=(call.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>",
            request_timeout=REQ_TIMEOUT
        )
    except Exception:
        pass
    await _quick_answer(call, "Отклонено.")


@router.message(Command("admin"))
@router.message(F.text.in_({"⚙️ Админка", "⚙️ Админ-панель"}))
async def msg_admin(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
    if message.from_user.id == ADMIN_ID:
        await render_admin(message)


@router.callback_query(F.data == "nav_admin")
async def cb_admin(call: CallbackQuery, state: FSMContext):
    if await state.get_state():
        await state.clear()
    if call.from_user.id == ADMIN_ID:
        await render_admin(call)
    else:
        await _quick_answer(call)


async def render_admin(target):
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT COUNT(*) FROM users") as cur:
            u_cnt = (await cur.fetchone())[0]
        async with DB_CONN.execute("SELECT COUNT(*), COALESCE(SUM(price), 0) FROM orders WHERE status = 'completed'") as cur:
            o_cnt, rev = await cur.fetchone()

    text = (
        "⚙️ <b>Панель управления • Bombych Store</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Клиентов в базе:</b> <code>{u_cnt}</code>\n"
        f"✅ <b>Выполнено заказов:</b> <code>{o_cnt}</code>\n"
        f"💰 <b>Общая выручка:</b> <code>{rev:.0f} ₽</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👥 Участники ({u_cnt})", callback_data="adm_users_0")],
        [
            InlineKeyboardButton(text="➕ Добавить товар", callback_data="adm_add_item"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")
        ],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")]
    ])
    await show_screen(target, "main.jpg", text, kb)


@router.callback_query(F.data.startswith("adm_users_"))
async def cb_adm_users(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    if await state.get_state():
        await state.clear()

    try:
        page = max(0, int(call.data.split("_")[2]))
    except (IndexError, ValueError):
        page = 0

    async with DB_LOCK:
        async with DB_CONN.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        total_pages = max(1, math.ceil(total / USERS_PER_PAGE))
        if page >= total_pages:
            page = total_pages - 1
        offset = page * USERS_PER_PAGE
        async with DB_CONN.execute(
            "SELECT user_id, username, first_name, joined_at FROM users ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (USERS_PER_PAGE, offset)
        ) as cur:
            rows = await cur.fetchall()

    b = InlineKeyboardBuilder()
    lines = []
    if not rows:
        lines.append("<i>В базе пока нет участников.</i>")
    else:
        for idx, (uid, uname, fname, joined_at) in enumerate(rows, start=offset + 1):
            clean_u = _clean_username(uname)
            safe_fname = html.escape((fname or "Гость")[:24])
            u_display = f"@{html.escape(clean_u)}" if clean_u else "без юзернейма"
            lines.append(f"{idx}. <b>{safe_fname}</b> ({u_display}) • <code>{uid}</code>")

            btn_title = f"@{clean_u}" if clean_u else (fname or str(uid))
            if len(btn_title) > 18:
                btn_title = btn_title[:17] + "…"
            b.button(text=f"👤 {btn_title}", callback_data=f"adm_user_{uid}_{page}")

    b.adjust(2)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"adm_users_{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page + 1 < total_pages:
        nav_row.append(InlineKeyboardButton(text="След. ➡️", callback_data=f"adm_users_{page + 1}"))
    if nav_row:
        b.row(*nav_row)

    b.row(
        InlineKeyboardButton(text="⚙️ В админку", callback_data="nav_admin"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home")
    )

    text = (
        f"👥 <b>Участники • Всего: {total}</b> (стр. {page + 1}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>" + "\n".join(lines) + "</blockquote>\n"
        f"👇 <b>Нажмите на участника, чтобы открыть профиль и аватарку:</b>"
    )
    await show_screen(call, "profile.jpg", text, b.as_markup())


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await _quick_answer(call)


@router.callback_query(F.data.startswith("adm_user_"))
async def cb_adm_user_card(call: CallbackQuery, state: FSMContext, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    if await state.get_state():
        await state.clear()

    parts = call.data.split("_")
    try:
        uid = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
    except (IndexError, ValueError):
        return await _quick_answer(call, "Участник не найден", show_alert=True)

    async with DB_LOCK:
        async with DB_CONN.execute(
            "SELECT username, first_name, balance, joined_at FROM users WHERE user_id = ?",
            (uid,)
        ) as cur:
            row = await cur.fetchone()
        async with DB_CONN.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), "
            "COALESCE(SUM(CASE WHEN status = 'completed' THEN price ELSE 0 END), 0) "
            "FROM orders WHERE user_id = ?",
            (uid,)
        ) as cur:
            total_orders, done_orders, total_spent = await cur.fetchone()

    if not row:
        return await _quick_answer(call, "Участник не найден в базе", show_alert=True)

    uname, fname, balance, joined_at = row
    done_orders = done_orders or 0

    try:
        chat = await bot.get_chat(uid, request_timeout=5)
        fresh_uname = chat.username or ""
        fresh_fname = chat.first_name or fname or "Гость"
        if fresh_uname != (uname or "") or fresh_fname != (fname or ""):
            uname, fname = fresh_uname, fresh_fname
            async with DB_LOCK:
                await DB_CONN.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (uname, fname, uid)
                )
                await DB_CONN.commit()
    except Exception:
        pass

    avatar_fid = None
    try:
        photos = await bot.get_user_profile_photos(user_id=uid, limit=1, request_timeout=5)
        if photos.total_count > 0 and photos.photos:
            avatar_fid = photos.photos[0][-1].file_id
    except Exception:
        pass

    clean_u = _clean_username(uname)
    u_line = f"@{html.escape(clean_u)}" if clean_u else "<i>не установлен</i>"
    avatar_note = "" if avatar_fid else "\n🖼 <i>Аватар скрыт настройками приватности или не установлен</i>"

    caption = (
        f"👤 <b>Карточка участника</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 <b>Имя:</b> {html.escape(fname or 'Гость')}\n"
        f"🔗 <b>Юзернейм:</b> {u_line}\n"
        f"🆔 <b>ID:</b> <code>{uid}</code>\n"
        f"📅 <b>В боте с:</b> <code>{joined_at or '—'}</code>\n\n"
        f"<blockquote>💰 <b>Баланс:</b> <code>{balance:.0f} ₽</code>\n"
        f"📦 <b>Заказов всего / выдано:</b> <code>{total_orders} / {done_orders}</code>\n"
        f"💎 <b>Сумма покупок:</b> <code>{total_spent:.0f} ₽</code></blockquote>"
        f"{avatar_note}"
    )

    buttons = []
    if clean_u:
        buttons.append([InlineKeyboardButton(text=f"💬 Написать @{clean_u}", url=f"https://t.me/{clean_u}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ К списку", callback_data=f"adm_users_{page}"),
        InlineKeyboardButton(text="⚙️ Админка", callback_data="nav_admin")
    ])

    await show_dynamic_photo(call, avatar_fid, "profile.jpg", caption, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "adm_add_item")
async def cb_adm_add_item(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    asyncio.create_task(_quick_answer(call))
    b = InlineKeyboardBuilder()
    for cid in RAM_CAT_ORDER:
        label = f"FN: {RAM_CATS[cid]['short_name']}" if cid in FORTNITE_CAT_IDS else RAM_CATS[cid]["short_name"]
        b.button(text=label, callback_data=f"admcat_{cid}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="nav_admin"))
    await call.message.answer(
        "📂 <b>Выберите категорию для нового товара:</b>",
        reply_markup=b.as_markup(),
        request_timeout=REQ_TIMEOUT
    )


@router.callback_query(F.data.startswith("admcat_"))
async def cb_adm_pick_cat(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    asyncio.create_task(_quick_answer(call))
    cid = int(call.data.split("_")[1])
    await state.update_data(cid=cid)
    await state.set_state(AdminFlow.add_full_name)
    await call.message.answer(
        "✏️ Введите <b>полное название товара</b> (например: <code>4500 В-Баксов</code>):",
        request_timeout=REQ_TIMEOUT
    )


@router.message(AdminFlow.add_full_name)
async def adm_set_fname(message: Message, state: FSMContext):
    await state.update_data(fname=(message.text or "").strip())
    await state.set_state(AdminFlow.add_short_btn)
    await message.answer(
        "🔘 Введите <b>короткое название для кнопки</b> до 10 символов (например: <code>💎 4500 ВБ</code>):",
        request_timeout=REQ_TIMEOUT
    )


@router.message(AdminFlow.add_short_btn)
async def adm_set_sbtn(message: Message, state: FSMContext):
    await state.update_data(sbtn=(message.text or "").strip())
    await state.set_state(AdminFlow.add_price)
    await message.answer(
        "💰 Введите <b>цену в рублях</b> (бот сам сделает скидку -20%, либо введите две цены через пробел: <code>старая новая</code>):",
        request_timeout=REQ_TIMEOUT
    )


@router.message(AdminFlow.add_price)
async def adm_save_product(message: Message, state: FSMContext):
    parts = (message.text or "").replace(",", ".").split()
    try:
        if len(parts) >= 2:
            old_p, new_p = int(float(parts[0])), int(float(parts[1]))
        else:
            old_p = int(float(parts[0]))
            new_p = max(10, int(round(old_p * 0.80)))
    except (ValueError, IndexError):
        return await message.answer(
            "⚠️ Введите число (например <code>500</code> или <code>500 400</code>):",
            request_timeout=REQ_TIMEOUT
        )

    data = await state.get_data()
    await state.clear()

    cimg = RAM_CATS.get(data["cid"], {}).get("image_name", "catalog.jpg")
    btn_lbl = f"{data['sbtn']} • {new_p}₽"
    async with DB_LOCK:
        await DB_CONN.execute(
            "INSERT INTO products (category_id, full_name, btn_label, old_price, price, image_name) VALUES (?, ?, ?, ?, ?, ?)",
            (data["cid"], data["fname"], btn_lbl, old_p, new_p, cimg)
        )
        await DB_CONN.commit()
    await reload_catalog_cache()

    await message.answer(
        f"✅ Товар <b>{html.escape(data['fname'])}</b> добавлен!\n"
        f"Цена: <s>{old_p}₽</s> → <b>{new_p}₽</b> (Кнопка: <code>{html.escape(btn_lbl)}</code>)",
        request_timeout=REQ_TIMEOUT
    )


@router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await _quick_answer(call)
    asyncio.create_task(_quick_answer(call))
    await state.set_state(AdminFlow.waiting_broadcast)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="nav_admin")]])
    await call.message.answer(
        "📢 Введите текст рассылки для всех клиентов:",
        reply_markup=kb,
        request_timeout=REQ_TIMEOUT
    )


@router.message(AdminFlow.waiting_broadcast)
async def run_broadcast(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()
    safe_text = html.escape(message.text or "")
    sent = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Новости • Bombych Store</b>\n\n{safe_text}", request_timeout=8)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Рассылка доставлена <b>{sent}</b> клиентам.", request_timeout=REQ_TIMEOUT)


# ================= ГЛОБАЛЬНЫЙ ПЕРЕХВАТЧИК ОШИБОК =================
@router.error()
async def global_error_handler(event: ErrorEvent):
    logging.exception(f"Ошибка в апдейте: {event.exception}")
    if event.update.callback_query:
        await _quick_answer(event.update.callback_query, "⚠️ Временный сбой, нажмите кнопку ещё раз.")


# ================= МЕНЮ «☰» И ЗАПУСК =================
async def setup_menu_commands(bot: Bot):
    cmds = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="catalog", description="🛒 Каталог товаров"),
        BotCommand(command="profile", description="👤 Личный кабинет"),
        BotCommand(command="xbox", description="🧶 Привязка Xbox"),
        BotCommand(command="info", description="ℹ️ Информация"),
        BotCommand(command="rules", description="📕 Правила"),
        BotCommand(command="terms", description="📄 Пользовательское соглашение"),
        BotCommand(command="privacy", description="🔒 Политика конфиденциальности"),
        BotCommand(command="support", description="🆘 Поддержка"),
    ]
    await bot.set_my_commands(cmds, scope=BotCommandScopeDefault())


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN! Укажите токен бота во вкладке «Переменные» на хостинге.")

    prepare_all_banners()
    await init_db_and_cache()

    session = AiohttpSession(timeout=25)
    if hasattr(session, "_connector_init") and isinstance(session._connector_init, dict):
        session._connector_init["keepalive_timeout"] = 10

    bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await setup_menu_commands(bot)

    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bombych Store v16.1 успешно запущен!")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=10
        )
    finally:
        await bot.session.close()
        if DB_CONN:
            await DB_CONN.close()


if __name__ == "__main__":
    asyncio.run(main())
