import asyncio, glob, hashlib, html, logging, math, os, random, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
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
    Message, CallbackQuery, ErrorEvent, FSInputFile, InputMediaPhoto, InputMediaDocument,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, BotCommand, BotCommandScopeDefault, TelegramObject
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or "6829445274:AAFFjpX1AS6ZaO7I5WgBucHMpzyKsLt6tDQ"
ADMIN_ID = 5157852376

SUPPORT_USERNAME = "@bombych"
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
DONATIONALERTS_URL = "https://www.donationalerts.com/r/bombychyt"
TON_WALLET = "UQAmhiehcvEaSqZZ-aTZK0RPDw2CDEzjSkiZymwYiyrMWbPw"

REF_PERCENT = 25
BOT_USERNAME = ""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

CURRENT_DB_NAME = "bombystore_v10.db"
DB_PATH = os.path.join(DATA_DIR, CURRENT_DB_NAME)
IMG_DIR = os.path.join(BASE_DIR, "assets_v18")
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

# ================= СОСТОЯНИЕ И КЭШ =================
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
    (1, "💎 В-Баксы", "💎 В-Баксы Fortnite", "vbucks.jpg", "purple_forest", ("VBUCKS", ""),
     "💎 <b>Официальное пополнение В-Баксов Fortnite на ваш аккаунт.</b>\nПеред покупкой убедитесь, что к профилю Epic Games привязан Xbox.",
     [("800 В-Баксов", "💎 800 ВБ", 499, 399), ("2 400 В-Баксов", "💎 2400 ВБ", 1279, 1023), ("4 500 В-Баксов", "💎 4500 ВБ", 1949, 1559), ("12 500 В-Баксов", "💎 12500 ВБ", 4599, 3679)]),
    (2, "🎁 ВБ подарком", "🎁 В-Баксы подарком", "gift_vbucks.jpg", "purple_forest", ("GIFT", "VBUCKS"),
     "🎁 <b>Отправка скинов, кирок и эмоций из магазина Fortnite подарком!</b>\nДобавьте наши аккаунты в друзья за 48 часов до покупки.",
     [("200 В-Баксов (Подарком)", "🎁 200 ВБ", 170, 136), ("500 В-Баксов (Подарком)", "🎁 500 ВБ", 290, 232), ("800 В-Баксов (Подарком)", "🎁 800 ВБ", 390, 312), ("1 200 В-Баксов (Подарком)", "🎁 1200 ВБ", 550, 440), ("1 500 В-Баксов (Подарком)", "🎁 1500 ВБ", 720, 576), ("1 800 В-Баксов (Подарком)", "🎁 1800 ВБ", 970, 776), ("2 000 В-Баксов (Подарком)", "🎁 2000 ВБ", 1150, 920), ("2 500 В-Баксов (Подарком)", "🎁 2500 ВБ", 1250, 1000)]),
    (3, "📦 Наборы", "📦 Наборы", "packs.jpg", "purple_forest", ("НАБОРЫ", "FORTNITE"),
     "📦 <b>Отряд Fortnite (Fortnite Crew), наборы Xbox и покупка игр Epic Games.</b>",
     [("Отряд Fortnite (Fortnite Crew)", "👑 Отряд", 444, 355), ("Стартер-пак Fortnite (600 ВБ)", "📦 Стартер", 349, 279), ("Боевой Пропуск сезона", "🎫 БП Сезона", 599, 479), ("Набор «Искусный взлом» / ПВЕ", "🛡 Набор ПВЕ", 1199, 959), ("Покупка игр / DLC Epic Games", "🎮 Игры Epic", 215, 172), ("Активация вашего кода Xbox", "🔑 Код Xbox", 100, 80)]),
    (4, "🌴 GTA VI", "🌴 Покупка игры Grand Theft Auto VI", "gta6.jpg", "gta6_sunset", ("GTA VI", ""),
     "🌴 <b>Официальная покупка Grand Theft Auto VI для PlayStation и Xbox!</b>",
     [("GTA VI PlayStation", "🎮 PS • 6479₽", 7199, 6479), ("GTA VI Xbox", "🎮 Xbox • 6209₽", 6899, 6209)]),
    (5, "🔫 Brawl Stars", "🟢 Гемы и Пропуски Brawl Stars", "brawl.jpg", "violet_neon", ("BRAWL", "STARS"),
     "🟢 <b>Официальное пополнение гемов и Brawl Pass по вашему Supercell ID.</b>",
     [("30 Гемов Brawl Stars", "🟢 30 Гемов", 199, 159), ("80 Гемов Brawl Stars", "🟢 80 Гемов", 489, 391), ("170 Гемов Brawl Stars", "🟢 170 Гемов", 979, 783), ("180 Гемов (Акция)", "🔥 180 Акция", 999, 799), ("360 Гемов Brawl Stars", "🟢 360 Гемов", 1949, 1559), ("950 Гемов Brawl Stars", "🟢 950 Гемов", 4199, 3359), ("2000 Гемов Brawl Stars", "🟢 2000 Гемов", 8199, 6559), ("BRAWL PASS", "🎫 PASS", 949, 759), ("BRAWL PASS +", "🎫 PASS+", 969, 775)]),
    (6, "👑 Clash Royale", "👑 Гемы и Pass Clash Royale", "clash.jpg", "blue_royal", ("CLASH", "ROYALE"),
     "👑 <b>Пополнение гемов и боевых пропусков Clash Royale через Supercell ID.</b>",
     [("80 + 8 Гемов CR", "💎 88 Гемов", 169, 135), ("500 + 50 Гемов CR", "💎 550 Гемов", 479, 383), ("1200 + 120 Гемов CR", "💎 1320 Гемов", 919, 735), ("2500 + 250 Гемов CR", "💎 2750 Гемов", 1679, 1343), ("6500 + 650 Гемов CR", "💎 7150 Гемов", 3979, 3183), ("14000 + 1400 Гемов CR", "💎 15400 Гем", 7499, 5999), ("GOLD PASS", "🎫 GOLD", 549, 439), ("DIAMOND PASS", "🎫 DIAMOND", 999, 799)]),
    (7, "⚔️ Clash of Clans", "⚔️ Гемы и Пропуски Clash of Clans", "coc.jpg", "gold_forest", ("CLASH OF", "CLANS"),
     "⚔️ <b>Пополнение гемов и пропусков событий Clash of Clans по Supercell ID.</b>",
     [("80 Гемов Clash of Clans", "💎 80 Гемов", 119, 95), ("500 Гемов Clash of Clans", "💎 500 Гемов", 499, 399), ("1200 Гемов Clash of Clans", "💎 1200 Гемов", 999, 799), ("2500 Гемов Clash of Clans", "💎 2500 Гемов", 1899, 1519), ("6500 Гемов Clash of Clans", "💎 6500 Гемов", 4499, 3599), ("Мини-пропуск события CC", "🎫 Мини-Пасс", 339, 271)]),
    (8, "🎲 Roblox", "🎲 Коды Robux для РФ — Roblox", "roblox.jpg", "red_forest", ("ROBLOX", "ROBUX"),
     "🎲 <b>Цифровые коды пополнения Robux для аккаунтов РФ и любого региона.</b>",
     [("199 Robux (Код РФ)", "🎲 199 R$", 279, 223), ("255 Robux (Код РФ)", "🎲 255 R$", 364, 291), ("395 Robux (Код РФ)", "🎲 395 R$", 559, 447), ("715 Robux (Код РФ)", "🎲 715 R$", 1009, 807), ("1500 Robux (Код РФ)", "🎲 1500 R$", 2099, 1679), ("4500 Robux (Код РФ)", "🎲 4500 R$", 5999, 4799)]),
    (9, "🌙 Genshin Impact", "🌙 Пополнение Genshin Impact по UID", "genshin.jpg", "cyan_night", ("GENSHIN", "IMPACT"),
     "🌙 <b>Моментальное пополнение Кристаллов Сотворения и Луны по UID и серверу.</b>",
     [("Гранулы времени", "⏳ Гранулы", 105, 84), ("Благословение полой луны", "🌙 Полая Луна", 491, 393), ("Кристаллы Сотворения (Пакет)", "💎 Пакет 500", 500, 400), ("980 + 110 Кристаллов", "💎 1090 Крист", 1399, 1119), ("1980 + 260 Кристаллов", "💎 2240 Крист", 2799, 2239), ("6480 + 1600 Кристаллов", "💎 8080 Крист", 8499, 6799)]),
    (10, "🎯 Standoff 2", "🎯 Голда Standoff 2 по ID", "standoff.jpg", "red_forest", ("STANDOFF 2", "GOLD"),
     "🎯 <b>Быстрое пополнение голды (Gold) в Standoff 2 по игровому ID.</b>",
     [("100 Gold (По ID)", "🎯 100 G", 109, 87), ("200 Gold (По ID)", "🎯 200 G", 219, 175), ("500 Gold (По ID)", "🎯 500 G", 600, 480), ("1000 Gold (По ID)", "🎯 1000 G", 1100, 880), ("3000 Gold (По ID)", "🎯 3000 G", 2600, 2080)]),
    (11, "🔥 Free Fire", "💎 Алмазы Free Fire", "freefire.jpg", "red_forest", ("FREE", "FIRE"),
     "💎 <b>Быстрое зачисление алмазов (Diamonds) на ваш аккаунт Free Fire.</b>",
     [("100 Diamonds", "💎 100 Алм.", 179, 143), ("210 Diamonds", "💎 210 Алм.", 269, 215), ("530 Diamonds", "💎 530 Алм.", 579, 463), ("645 Diamonds", "💎 645 Алм.", 749, 599), ("1080 Diamonds", "💎 1080 Алм.", 1049, 839), ("2200 Diamonds", "💎 2200 Алм.", 2049, 1639), ("4450 Diamonds", "💎 4450 Алм.", 4499, 3599), ("6900 Diamonds", "💎 6900 Алм.", 6749, 5399)]),
    (12, "🪂 PUBG / Шутеры", "🪂 G-Coin PUBG и Arena Breakout", "pubg.jpg", "gold_forest", ("PUBG", "G-COIN"),
     "🪂 <b>Коды G-Coin для Steam-версии PUBG и облигации для Arena Breakout.</b>",
     [("100 G-Coin PUBG", "🪂 100 GC", 85, 68), ("500 + 10 G-Coin PUBG", "🪂 510 GC", 419, 335), ("1000 + 50 G-Coin PUBG", "🪂 1050 GC", 839, 671), ("2500 + 200 G-Coin PUBG", "🪂 2700 GC", 2099, 1679), ("5000 + 500 G-Coin PUBG", "🪂 5500 GC", 4189, 3351), ("Облигации Arena Breakout", "🎖 Arena 60", 119, 95)]),
    (13, "💰 Вирты GTA/BR", "💰 Вирты GTA 5 и Black Russia", "virts.jpg", "gold_forest", ("ВИРТЫ", ""),
     "💰 <b>Быстрая доставка игровой валюты на ваш сервер.</b>",
     [("1kk Виртов", "💰 1kk", 149, 119), ("5kk Виртов", "💰 5kk", 689, 551), ("10kk Виртов", "💰 10kk", 999, 799), ("15kk Виртов", "💰 15kk", 1299, 1039), ("30kk Виртов", "💰 30kk", 1899, 1519)]),
    (14, "⭐ Telegram", "⭐ Telegram Premium и Звёзды (Stars)", "tg_prem.jpg", "blue_royal", ("Telegram", "Premium"),
     "⭐ <b>Telegram Premium и Звёзды (Stars) по @username без входа в аккаунт.</b>",
     [("Telegram Premium 30 дней", "⭐ Prem 30д", 249, 199), ("Telegram Premium 90 дней", "⭐ Prem 90д", 749, 599), ("Telegram Premium 365 дней", "⭐ Prem 1 Год", 1999, 1599), ("100 Звёзд Telegram (Stars)", "✨ 100 Stars", 199, 159), ("250 Звёзд Telegram (Stars)", "✨ 250 Stars", 489, 391), ("500 Звёзд Telegram (Stars)", "✨ 500 Stars", 949, 759), ("1000 Звёзд Telegram (Stars)", "✨ 1000 Stars", 1849, 1479), ("2500 Звёзд Telegram (Stars)", "✨ 2500 Stars", 4499, 3599)]),
    (15, "🧿 Steam", "🧿 Пополнение баланса и Игры Steam", "steam.jpg", "cyan_night", ("STEAM", "STORE"),
     "🧿 <b>Пополнение кошелька Steam (РФ / СНГ / КЗ) по логину и игры подарком.</b>",
     [("Пополнение Steam на 250 ₽", "🧿 250 ₽", 290, 232), ("Пополнение Steam на 500 ₽", "🧿 500 ₽", 560, 448), ("Пополнение Steam на 1000 ₽", "🧿 1000 ₽", 1120, 896), ("Пополнение Steam на 2000 ₽", "🧿 2000 ₽", 2200, 1760), ("Пополнение Steam на 5000 ₽", "🧿 5000 ₽", 5450, 4360), ("Игра подарком (Steam Gift)", "🎁 Steam Gift", 499, 399)]),
    (16, "🔮 Discord Nitro", "🔮 Discord N1tro (Любой аккаунт)", "nitro.jpg", "violet_neon", ("Discord", "N1tro"),
     "🔮 <b>Официальная подписка Discord Nitro Classic и Full на любой аккаунт!</b>",
     [("Discord Nitro Classic 30 дн.", "🔮 Clas 30д", 250, 200), ("Discord Nitro Classic 365 дн.", "🔮 Clas Год", 1500, 1200), ("Discord Nitro Full 30 дн.", "🚀 Full 30д", 400, 320), ("Discord Nitro Full 365 дн.", "🚀 Full Год", 3050, 2440)]),
    (17, "🤖 ИИ и Spotify", "🤖 Подписки ChatGPT и Spotify Premium", "ai_spotify.jpg", "emerald_forest", ("SPOTIFY", "& AI"),
     "🤖 <b>Оформление зарубежных подписок ChatGPT и Spotify Premium.</b>",
     [("ChatGPT GO (1 месяц)", "🤖 GPT GO", 499, 399), ("ChatGPT Plus (1 месяц)", "🧠 GPT Plus", 1999, 1599), ("Spotify Premium 1 мес.", "🎧 Spotify 1м", 349, 279), ("Spotify Premium 3 мес.", "🎧 Spotify 3м", 899, 719), ("Spotify Premium 12 мес.", "🎧 Spotify 1г", 2499, 1999)]),
    (18, "🔻 ExitLag", "🔻 Ключи активации ExitLag", "exitlag.jpg", "red_forest", ("ExitLag", ""),
     "🔻 <b>Лицензионные коды ExitLag для снижения пинга в играх.</b>",
     [("ExitLag 3 дня", "🔻 3 дня", 20, 16), ("ExitLag 15 дней", "🔻 15 дней", 120, 96), ("ExitLag 30 дней", "🔻 30 дней", 200, 160), ("ExitLag 60 дней", "🔻 60 дней", 400, 320), ("ExitLag 100 дней", "🔻 100 дней", 500, 400), ("ExitLag 150 дней", "🔻 150 дней", 550, 440), ("ExitLag 200 дней", "🔻 200 дней", 600, 480), ("ExitLag 300 дней", "🔻 300 дней", 700, 560)]),
    (19, "💳 Банки / Биржи", "💳 Зарубежные Банки и Верификация", "banks.jpg", "cyan_night", ("БАНКИ", "ВЕРИФИКАЦИЯ"),
     "💳 <b>Готовые личные кабинеты зарубежных банков и верификация криптобирж.</b>",
     [("Ozan (Банк Турции)", "💳 Ozan", 999, 799), ("Belo (Банк Аргентины)", "💳 Belo", 1499, 1199), ("Bybit (Верификация)", "📈 Bybit", 1499, 1199), ("Binance (Верификация)", "📈 Binance", 1599, 1279), ("Huobi (Верификация)", "📈 Huobi", 1299, 1039), ("Ozon (Верификация)", "💳 Ozon", 999, 799), ("Yoomoney/Qiwi (Турция)", "💳 ЮMoney", 249, 199)]),
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
    ("referral.jpg", "emerald_forest", ("РЕФЕРАЛКА", f"{REF_PERCENT}% БОНУС")),
    ("info.jpg", "purple_forest", ("INFORMATION", "")),
    ("rules.jpg", "purple_forest", ("ПРАВИЛА", "")),
    ("xbox.jpg", "cyan_night", ("ПРИВЯЗКА", "")),
    ("support.jpg", "blue_royal", ("ПОДДЕРЖКА", "")),
    ("terms.jpg", "violet_neon", ("ПОЛЬЗОВАТЕЛЬСКОЕ", "СОГЛАШЕНИЕ")),
    ("privacy.jpg", "cyan_night", ("ПОЛИТИКА", "КОНФИДЕНЦИАЛЬНОСТИ")),
]

TERMS_SECTIONS = [
    ("1. Общие положения", [
        "1.1. Настоящее Пользовательское соглашение регулирует отношения между администрацией Telegram-бота Bombych Store (Сервис) и Пользователем.",
        "1.2. Нажимая «Принимаю условия» и используя Сервис, Пользователь подтверждает полное согласие со всеми условиями Соглашения.",
        "1.3. Пользователь подтверждает достижение 18 лет либо наличие согласия законных представителей на покупки в Сервисе."
    ]),
    ("2. Предмет соглашения", [
        "2.1. Сервис оказывает услуги по приобретению и зачислению цифровых товаров: игровой валюты, наборов, ключей активации и подписок.",
        "2.2. Сервис является независимой площадкой и не аффилирован с Epic Games, Supercell, Valve, Telegram, Discord, Roblox, miHoYo и иными правообладателями."
    ]),
    ("3. Оформление и оплата заказов", [
        "3.1. Актуальные цены указаны в каталоге. Для оплаченных заказов цена фиксируется на момент оплаты.",
        "3.2. Оплата производится по реквизитам из счёта. После перевода Пользователь прикрепляет скриншот или файл чека в бот.",
        "3.3. Заказ принимается в работу после проверки администратором фактического поступления оплаты."
    ]),
    ("4. Сроки выдачи и возврат", [
        "4.1. Приём заявок ведётся 24/7. Выдача цифровых товаров выполняется ежедневно с 05:00 до 22:00 (МСК).",
        "4.2. Цифровые товары, ключи, подписки и внутриигровые зачисления надлежащего качества после передачи или активации возврату не подлежат.",
        "4.3. При невозможности выполнить оплаченный заказ по вине Сервиса осуществляется полный возврат средств."
    ]),
    ("5. Ответственность и ограничения", [
        "5.1. Пользователь отвечает за точность переданных данных (ID, UID, @username, регион, привязка Xbox / Supercell ID).",
        "5.2. При указании ошибочных реквизитов, повлекших зачисление на иной аккаунт, услуга считается оказанной и возврату не подлежит.",
        "5.3. Запрещены поддельные чеки, спам, попытки взлома и оскорбления поддержки. При нарушении доступ блокируется."
    ]),
    ("6. Заключительные положения", [
        "6.1. Администрация вправе обновлять Соглашение. Актуальная версия всегда доступна в боте.",
        f"6.2. По всем вопросам обращайтесь к нам в поддержку Telegram: {SUPPORT_USERNAME}."
    ]),
]

PRIVACY_SECTIONS = [
    ("1. Общие положения", [
        "1.1. Политика конфиденциальности определяет порядок сбора, хранения, обработки и защиты данных пользователей Bombych Store.",
        "1.2. Обработка данных ведётся с соблюдением базовых принципов ФЗ № 152-ФЗ «О персональных данных».",
        "1.3. Нажимая кнопку согласия при первом запуске, Пользователь принимает условия Политики."
    ]),
    ("2. Состав собираемых данных", [
        "• Данные Telegram: Telegram ID, @username, отображаемое имя и дата первого обращения.",
        "• Данные заказов: выбранные товары, суммы, способ оплаты, статусы, чеки и комментарии.",
        "• Данные для зачисления: игровой ID, UID, тег, почта или временные данные доступа, переданные для выполнения заказа."
    ]),
    ("3. Цели обработки", [
        "• Идентификация Пользователя, работа личного кабинета, реферальной программы и истории покупок.",
        "• Проверка оплаты, выполнение заказов и оказание технической поддержки.",
        "• Уведомления о статусах заказов, бонусах и важных новостях Сервиса."
    ]),
    ("4. Хранение и защита данных", [
        "4.1. Технические данные и история заказов хранятся в защищённой базе данных с ограниченным доступом.",
        "4.2. Данные доступа к игровым аккаунтам используются однократно для зачисления товара и удаляются сразу после выдачи.",
        "4.3. Администрация принимает необходимые меры для защиты данных от утечки и несанкционированного доступа."
    ]),
    ("5. Нераспространение и передача третьим лицам", [
        "5.1. Личные данные строго конфиденциальны: они не продаются, не публикуются и не распространяются среди третьих лиц.",
        "5.2. Передача допускается только если это необходимо для проведения платежа/зачисления либо по законному запросу госорганов."
    ]),
    ("6. Права пользователя и удаление данных", [
        "6.1. Пользователь вправе запросить свои данные, их исправление, отказ от рассылок или полное удаление профиля.",
        f"6.2. Для удаления данных и по вопросам конфиденциальности напишите нам в поддержку: {SUPPORT_USERNAME}."
    ]),
]


# ================= ГЕНЕРАТОР АТМОСФЕРНЫХ БАННЕРОВ И PDF =================
THEME_PALETTES = {
    "purple_forest": {"bg": (5, 7, 22), "glow": (115, 38, 255), "corner_left": (15, 195, 255), "corner_right": (185, 35, 245), "star": (245, 220, 255), "text_top": (195, 65, 255), "text_bot": (105, 20, 225), "stroke": (35, 8, 75), "spark": (125, 235, 255), "tint_mode": "purple"},
    "gta6_sunset": {"bg": (18, 6, 28), "glow": (255, 55, 165), "corner_left": (255, 145, 40), "corner_right": (145, 50, 255), "star": (255, 225, 195), "text_top": (255, 220, 120), "text_bot": (255, 65, 175), "stroke": (48, 10, 58), "spark": (255, 200, 140), "tint_mode": "purple"},
    "violet_neon": {"bg": (10, 5, 28), "glow": (165, 45, 255), "corner_left": (235, 45, 210), "corner_right": (70, 125, 255), "star": (250, 225, 255), "text_top": (230, 80, 255), "text_bot": (120, 35, 235), "stroke": (42, 10, 80), "spark": (255, 165, 255), "tint_mode": "purple"},
    "blue_royal": {"bg": (4, 10, 28), "glow": (40, 130, 255), "corner_left": (0, 215, 255), "corner_right": (110, 65, 255), "star": (225, 242, 255), "text_top": (135, 225, 255), "text_bot": (40, 110, 245), "stroke": (12, 30, 75), "spark": (160, 235, 255), "tint_mode": "cyan"},
    "cyan_night": {"bg": (3, 14, 24), "glow": (15, 185, 245), "corner_left": (0, 245, 220), "corner_right": (85, 95, 255), "star": (215, 252, 255), "text_top": (115, 248, 255), "text_bot": (25, 145, 235), "stroke": (10, 42, 68), "spark": (150, 255, 245), "tint_mode": "cyan"},
    "red_forest": {"bg": (20, 4, 9), "glow": (235, 25, 55), "corner_left": (255, 95, 25), "corner_right": (200, 15, 95), "star": (255, 185, 195), "text_top": (255, 65, 105), "text_bot": (175, 12, 48), "stroke": (55, 6, 18), "spark": (255, 175, 100), "tint_mode": "red"},
    "gold_forest": {"bg": (18, 12, 5), "glow": (245, 165, 25), "corner_left": (255, 210, 60), "corner_right": (220, 85, 25), "star": (255, 242, 195), "text_top": (255, 225, 95), "text_bot": (215, 115, 15), "stroke": (58, 32, 5), "spark": (255, 235, 145), "tint_mode": "gold"},
    "emerald_forest": {"bg": (4, 18, 14), "glow": (25, 215, 120), "corner_left": (20, 240, 195), "corner_right": (95, 225, 60), "star": (220, 255, 235), "text_top": (105, 255, 170), "text_bot": (15, 165, 90), "stroke": (8, 52, 32), "spark": (165, 255, 210), "tint_mode": "emerald"},
}


def cleanup_old_files():
    cur_f = os.path.basename(IMG_DIR)
    for pat in ("img_v*", "assets_v*"):
        for fp in glob.glob(os.path.join(BASE_DIR, pat)):
            if os.path.isdir(fp) and os.path.basename(fp) != cur_f:
                shutil.rmtree(fp, ignore_errors=True)
    for sdir in {BASE_DIR, DATA_DIR}:
        for pat in ("bombystore.db*", "bombystore_v*.db*", "shop.db*", "bot.db*"):
            for dbf in glob.glob(os.path.join(sdir, pat)):
                if not os.path.basename(dbf).startswith(CURRENT_DB_NAME):
                    try:
                        os.remove(dbf)
                    except OSError:
                        pass


def _find_user_file(filenames: list) -> str | None:
    home = os.path.expanduser("~")
    for d in (os.path.join(BASE_DIR, "img"), os.path.join(BASE_DIR, "images"), BASE_DIR, os.path.join(home, "Downloads"), os.path.join(home, "Desktop")):
        if not os.path.isdir(d):
            continue
        try:
            emap = {e.lower(): e for e in os.listdir(d)}
        except OSError:
            continue
        for t in [fn.lower() for fn in filenames]:
            if t in emap and os.path.isfile(os.path.join(d, emap[t])):
                return os.path.join(d, emap[t])
    return None


def _file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_font(urls: list[str], dest: str) -> str | None:
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        try:
            ImageFont.truetype(dest, 24)
            return dest
        except Exception:
            pass
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = r.read()
            if len(data) > 10000:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)
                ImageFont.truetype(dest, 24)
                return dest
        except Exception:
            continue
    return None


def _resolve_font_path() -> str | None:
    global _RESOLVED_FONT_PATH, _FONT_SEARCHED
    if _FONT_SEARCHED:
        return _RESOLVED_FONT_PATH
    _FONT_SEARCHED = True
    for d in (os.path.join(BASE_DIR, "img"), os.path.join(BASE_DIR, "images"), BASE_DIR):
        if not os.path.isdir(d):
            continue
        files = os.listdir(d)
        fmap = {f.lower(): f for f in files}
        for pref in ("impact.ttf", "arialbd.ttf", "font.ttf"):
            if pref in fmap:
                p = os.path.join(d, fmap[pref])
                try:
                    ImageFont.truetype(p, 48)
                    _RESOLVED_FONT_PATH = p
                    return p
                except Exception:
                    pass
        for f in files:
            if f.lower().endswith((".ttf", ".otf")):
                p = os.path.join(d, f)
                try:
                    ImageFont.truetype(p, 48)
                    _RESOLVED_FONT_PATH = p
                    return p
                except Exception:
                    pass
    for p in ("C:\\Windows\\Fonts\\impact.ttf", "C:\\Windows\\Fonts\\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            try:
                ImageFont.truetype(p, 48)
                _RESOLVED_FONT_PATH = p
                return p
            except Exception:
                pass
    _RESOLVED_FONT_PATH = _download_font(["https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PTSans-Bold.ttf"], os.path.join(IMG_DIR, "_banner_bold.ttf"))
    return _RESOLVED_FONT_PATH


def _resolve_doc_fonts() -> tuple[str | None, str | None]:
    reg = next((p for p in (os.path.join(IMG_DIR, "_doc_regular.ttf"), "C:\\Windows\\Fonts\\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if os.path.exists(p)), None)
    bold = next((p for p in (os.path.join(IMG_DIR, "_doc_bold.ttf"), "C:\\Windows\\Fonts\\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if os.path.exists(p)), None)
    if not reg:
        reg = _download_font(["https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PTSans-Regular.ttf", "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ptsans/PTSans-Regular.ttf"], os.path.join(IMG_DIR, "_doc_regular.ttf"))
    if not bold:
        bold = _download_font(["https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PTSans-Bold.ttf", "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/ptsans/PTSans-Bold.ttf"], os.path.join(IMG_DIR, "_doc_bold.ttf")) or reg
    if not reg:
        reg = bold = _resolve_font_path()
    return reg, bold


def _load_bold_font(size: int):
    fp = _resolve_font_path()
    if fp:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit_font(draw, text: str, max_w: int, start_sz: int, min_sz: int = 34):
    sz = start_sz
    while sz >= min_sz:
        f = _load_bold_font(sz)
        bb = draw.textbbox((0, 0), text, font=f)
        if (bb[2] - bb[0]) <= max_w:
            return f, bb
        sz -= 4
    f = _load_bold_font(min_sz)
    return f, draw.textbbox((0, 0), text, font=f)


def _wrap_text(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split(" "):
        cand = f"{cur} {w}".strip() if cur else w
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _make_doc_thumbnail(banner_path: str, thumb_path: str):
    src = Image.open(banner_path).convert("RGB")
    bg = Image.blend(src.resize((320, 320), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(12)), Image.new("RGB", (320, 320), (10, 6, 26)), 0.45)
    bh = int(src.height * (320 / src.width))
    bg.paste(src.resize((320, bh), Image.Resampling.LANCZOS), (0, (320 - bh) // 2))
    bg.save(thumb_path, "JPEG", quality=85, optimize=True)


def _generate_legal_pdf(pdf_path: str, banner_path: str, title: str, subtitle: str, sections: list, reg_fp: str, bold_fp: str):
    W, H, ML, MR, MT, MB = 1000, 1414, 68, 68, 64, 88
    CW = W - ML - MR
    f_sub, f_sec, f_body, f_foot = ImageFont.truetype(reg_fp, 16), ImageFont.truetype(bold_fp, 22), ImageFont.truetype(reg_fp, 19), ImageFont.truetype(reg_fp, 15)
    f_title = ImageFont.truetype(bold_fp, 26)
    pages = []

    def new_page(first=False):
        pg = Image.new("RGB", (W, H), (255, 255, 255))
        dr = ImageDraw.Draw(pg)
        if first:
            yc = 0
            if os.path.exists(banner_path):
                bi = Image.open(banner_path).convert("RGB")
                bh = int(bi.height * (W / bi.width))
                pg.paste(bi.resize((W, bh), Image.Resampling.LANCZOS), (0, 0))
                yc = bh
            dr.rectangle([0, yc, W, yc + 6], fill=(138, 43, 226))
            dr.text((ML, yc + 28), title, font=f_title, fill=(24, 16, 48))
            dr.text((ML, yc + 66), subtitle, font=f_sub, fill=(112, 116, 134))
            return pg, dr, yc + 100
        dr.rectangle([0, 0, W, 8], fill=(138, 43, 226))
        return pg, dr, MT

    page, draw, y = new_page(True)
    pages.append(page)
    for st, paras in sections:
        if y + 84 > H - MB:
            page, draw, y = new_page(False)
            pages.append(page)
        draw.text((ML, y), st, font=f_sec, fill=(72, 24, 148))
        y += 32
        draw.line([(ML, y), (W - MR, y)], fill=(230, 222, 248), width=2)
        y += 14
        for p in paras:
            ind = 16 if p.startswith("•") else 0
            for ln in _wrap_text(draw, p, f_body, CW - ind):
                if y + 27 > H - MB:
                    page, draw, y = new_page(False)
                    pages.append(page)
                draw.text((ML + ind, y), ln, font=f_body, fill=(32, 34, 44))
                y += 27
            y += 9
        y += 12

    for i, pg in enumerate(pages, 1):
        dr = ImageDraw.Draw(pg)
        dr.line([(ML, H - 64), (W - MR, H - 64)], fill=(228, 226, 238), width=1)
        dr.text((ML, H - 48), f"Bombych Store • Поддержка: {SUPPORT_USERNAME}", font=f_foot, fill=(125, 128, 145))
        lbl = f"Стр. {i} из {len(pages)}"
        dr.text((W - MR - dr.textlength(lbl, font=f_foot), H - 48), lbl, font=f_foot, fill=(125, 128, 145))

    pages[0].save(pdf_path, "PDF", resolution=120.0, save_all=(len(pages) > 1), append_images=pages[1:])


def prepare_legal_documents():
    os.makedirs(IMG_DIR, exist_ok=True)
    reg_f, bold_f = _resolve_doc_fonts()
    specs = [
        ("terms", "terms.jpg", "Пользовательское соглашение", "Bombych Store • Актуальная редакция", TERMS_SECTIONS, "terms_doc", "Пользовательское_соглашение_BombychStore"),
        ("privacy", "privacy.jpg", "Политика конфиденциальности", "Bombych Store • Актуальная редакция", PRIVACY_SECTIONS, "privacy_doc", "Политика_конфиденциальности_BombychStore"),
    ]
    DOC_META.clear()
    for key, bname, title, sub, secs, dbase, sbase in specs:
        bpath = os.path.join(IMG_DIR, bname)
        tpath = os.path.join(IMG_DIR, f"{key}_thumb.jpg")
        if os.path.exists(bpath):
            _make_doc_thumbnail(bpath, tpath)
        ext = ".pdf" if (reg_f and bold_f) else ".txt"
        dpath = os.path.join(IMG_DIR, f"{dbase}{ext}")
        if ext == ".pdf":
            try:
                _generate_legal_pdf(dpath, bpath, title, sub, secs, reg_f, bold_f)
            except Exception:
                ext = ".txt"
                dpath = os.path.join(IMG_DIR, f"{dbase}.txt")
        if ext == ".txt":
            with open(dpath, "w", encoding="utf-8") as f:
                f.write(f"{title}\n\n" + "\n\n".join(f"{s}\n" + "\n".join(ps) for s, ps in secs))
        ckey = f"doc:{key}"
        DOC_META[key] = {"disk_path": dpath, "thumb_path": tpath, "send_name": f"{sbase}{ext}", "cache_key": ckey}
        FILE_HASHES[ckey] = f"{_file_md5(dpath)}:{_file_md5(tpath) if os.path.exists(tpath) else ''}"


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
    sd = ImageDraw.Draw(shade)
    cx = cy = rad = diameter // 2
    for step in range(rad, int(rad * 0.68), -3):
        ratio = (step / rad - 0.68) / 0.32
        sd.ellipse([cx - step, cy - step, cx + step, cy + step], outline=(4, 2, 14, int((ratio ** 1.7) * 200)), width=4)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return Image.alpha_composite(out, shade)


def _draw_foreground_foliage_and_grass(base: Image.Image, pal: dict, rng: random.Random):
    w, h = base.size
    fg, rim = Image.new("RGBA", (w, h), (0, 0, 0, 0)), Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fdraw, rdraw = ImageDraw.Draw(fg), ImageDraw.Draw(rim)
    dark_sil, mid_sil = (3, 4, 12, 248), (6, 8, 22, 215)
    rim_l, rim_r, rim_c = (*pal["corner_left"], 110), (*pal["corner_right"], 110), (*pal["glow"], 95)

    for side in ("left", "right"):
        for i in range(42):
            cx = rng.randint(-30, 125) if side == "left" else rng.randint(w - 125, w + 30)
            rx, cy, ry = rng.randint(24, 65), rng.randint(-20, h + 15), rng.randint(20, 55)
            rc, es = (rim_l, 5) if side == "left" else (rim_r, -5)
            rdraw.ellipse([cx - rx + es, cy - ry, cx + rx + es, cy + ry], fill=rc)
            fdraw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=dark_sil if i % 2 == 0 else mid_sil)
        for _ in range(38):
            x0 = rng.randint(25, 110) if side == "left" else rng.randint(w - 110, w - 25)
            x1 = x0 + rng.randint(25, 90) if side == "left" else x0 - rng.randint(25, 90)
            y0, rc = rng.randint(10, h - 20), (rim_l if side == "left" else rim_r)
            y1 = y0 + rng.randint(-40, 35)
            xm, ym = (x0 + x1) // 2, (y0 + y1) // 2 - rng.randint(4, 14)
            rdraw.polygon([(x0, y0 - 4), (xm, ym - 4), (x1, y1), (xm, ym + 4), (x0, y0 + 5)], fill=rc)
            fdraw.polygon([(x0, y0 - 3), (xm, ym - 3), (x1, y1), (xm, ym + 3), (x0, y0 + 4)], fill=dark_sil)

    for b_idx in range(6):
        bx = int(w * (0.28 + b_idx * 0.085) + rng.randint(-25, 25))
        length, angle = rng.randint(65, 135), math.radians(rng.uniform(72, 118))
        ex, ey = bx + int(math.cos(angle) * length), int(math.sin(angle) * length)
        fdraw.line([(bx, -10), (ex, ey)], fill=dark_sil, width=5)
        steps = rng.randint(16, 26)
        for s in range(steps):
            t = s / steps
            px, py = int(bx + (ex - bx) * t), int(-10 + (ey + 10) * t)
            for ss in (-1, 1):
                na, nl = angle + ss * math.radians(rng.uniform(22, 52)), rng.randint(18, 42) * (1.0 - 0.35 * t)
                nx, ny = px + int(math.cos(na) * nl), py + int(math.sin(na) * nl)
                rdraw.line([(px, py + 1), (nx, ny + 1)], fill=rim_c, width=2)
                fdraw.line([(px, py), (nx, ny)], fill=dark_sil, width=2)

    for _ in range(135):
        gx = rng.randint(-10, w + 10)
        gh = rng.randint(24, int(52 + 65 * ((abs(gx - w / 2) / (w / 2)) ** 1.3)))
        lean, bw = rng.randint(-38, 38), rng.randint(3, 7)
        tip_x, tip_y, mid_x, mid_y = gx + lean, h - gh, gx + lean // 2, h - int(gh * 0.55)
        r_col = rim_l if gx < w * 0.35 else (rim_r if gx > w * 0.65 else rim_c)
        rdraw.polygon([(gx - bw, h + 4), (mid_x - 2, mid_y), (tip_x, tip_y - 2), (mid_x + 2, mid_y), (gx + bw, h + 4)], fill=r_col)
        fdraw.polygon([(gx - bw, h + 4), (mid_x - 1, mid_y), (tip_x, tip_y), (mid_x + 2, mid_y), (gx + bw, h + 4)], fill=dark_sil)

    base.alpha_composite(rim.filter(ImageFilter.GaussianBlur(3.2)))
    base.alpha_composite(fg.filter(ImageFilter.GaussianBlur(1.1)))


def _render_chisel_3d_text(canvas: Image.Image, line1: str, line2: str, pal: dict):
    w, h = canvas.size
    tm = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(tm)
    if line2:
        f1, b1 = _fit_font(md, line1, w - 90, 104 if len(line1) <= 9 else 84)
        f2, b2 = _fit_font(md, line2, w - 90, 86 if len(line2) <= 10 else 72)
        w1, h1, w2, h2 = b1[2] - b1[0], b1[3] - b1[1], b2[2] - b2[0], b2[3] - b2[1]
        y1 = (h - (h1 + h2 + 18)) // 2 - b1[1] - 4
        md.text(((w - w1) // 2 - b1[0], y1), line1, font=f1, fill=255)
        md.text(((w - w2) // 2 - b2[0], y1 + b1[1] + h1 + 18 - b2[1]), line2, font=f2, fill=255)
    else:
        f1, b1 = _fit_font(md, line1, w - 90, 146 if len(line1) <= 7 else (112 if len(line1) <= 10 else 92))
        md.text(((w - (b1[2] - b1[0])) // 2 - b1[0], (h - (b1[3] - b1[1])) // 2 - b1[1] - 4), line1, font=f1, fill=255)

    nl = Image.new("RGBA", (w, h), (*pal["glow"], 0))
    nl.putalpha(tm.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(12)).point(lambda p: int(p * 0.72)))
    canvas.alpha_composite(nl)

    sh = Image.new("RGBA", (w, h), (4, 2, 12, 0))
    sh.putalpha(tm.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(6)).point(lambda p: int(p * 0.85)))
    canvas.alpha_composite(sh, dest=(0, 6))

    st = Image.new("RGBA", (w, h), (*pal["stroke"], 255))
    st.putalpha(tm.filter(ImageFilter.MaxFilter(5)))
    canvas.alpha_composite(st)

    hm, cur = Image.new("L", (w, h), 0), tm
    for _ in range(8):
        hm = ImageChops.add(hm, cur.point(lambda p: 31 if p > 128 else 0))
        cur = cur.filter(ImageFilter.MinFilter(3))
    h_ul, h_dr = Image.new("L", (w, h), 0), Image.new("L", (w, h), 0)
    h_ul.paste(hm, (-3, -3))
    h_dr.paste(hm, (3, 3))
    lf = ImageChops.subtract(h_dr, hm).point(lambda p: min(255, int(p * 3.8)))
    df = ImageChops.subtract(h_ul, hm).point(lambda p: min(255, int(p * 3.8)))

    face = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)
    r1, g1, b1 = pal["text_top"]
    r2, g2, b2 = pal["text_bot"]
    for y in range(h):
        t = y / h
        fd.line([(0, y), (w, y)], fill=(int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t), 255))
    face.putalpha(tm)
    canvas.alpha_composite(face)

    hl = Image.new("RGBA", (w, h), (255, 240, 255, 0))
    hl.putalpha(ImageChops.multiply(lf, tm).point(lambda p: int(p * 0.85)))
    canvas.alpha_composite(hl)
    dk = Image.new("RGBA", (w, h), (*pal["stroke"], 0))
    dk.putalpha(ImageChops.multiply(df, tm).point(lambda p: int(p * 0.85)))
    canvas.alpha_composite(dk)


def generate_scenic_banner(filepath: str, logo_img: Image.Image, theme: str, line1: str, line2: str):
    w, h = 900, 300
    pal = THEME_PALETTES.get(theme, THEME_PALETTES["purple_forest"])
    rng = random.Random(sum(ord(c) for c in f"{theme}_{line1}_{line2}"))
    base = Image.new("RGBA", (w, h), (*pal["bg"], 255))
    bdraw = ImageDraw.Draw(base)
    for y in range(h):
        t = math.sin((y / h) * math.pi)
        bdraw.line([(0, y), (w, y)], fill=(min(255, int(pal["bg"][0] + pal["glow"][0] * 0.24 * t)), min(255, int(pal["bg"][1] + pal["glow"][1] * 0.24 * t)), min(255, int(pal["bg"][2] + pal["glow"][2] * 0.28 * t)), 255))

    ll = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(ll)
    ld.ellipse([-60, 125, 290, 360], fill=(*pal["corner_left"], 155))
    ld.ellipse([610, 95, 960, 355], fill=(*pal["corner_right"], 130))
    ld.ellipse([185, 20, 715, 295], fill=(*pal["glow"], 155))
    ld.polygon([(465, 58), (542, 148), (690, 178), (558, 240), (590, 298), (448, 258), (275, 292), (332, 222), (235, 168), (378, 148)], fill=(*pal["star"], 215))
    base = Image.alpha_composite(base, ll.filter(ImageFilter.GaussianBlur(28)))

    for sx, sy, diam, ang, br, op in ((295, -24, 215, -18, 1.8, 0.88), (455, 240, 145, 25, 2.5, 0.72), (690, 185, 185, -35, 2.2, 0.75)):
        orb = _build_atmospheric_sphere(logo_img, diam, ang, pal["tint_mode"], opacity=op).filter(ImageFilter.GaussianBlur(br))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.paste(orb, (sx, sy), orb)
        base = Image.alpha_composite(base, layer)

    sp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    spd = ImageDraw.Draw(sp)
    for _ in range(42):
        px, py, pr = rng.randint(40, w - 40), rng.randint(25, h - 25), rng.randint(2, 6)
        spd.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(*pal["spark"], rng.randint(90, 220)))
    base = Image.alpha_composite(base, sp.filter(ImageFilter.GaussianBlur(1.6)))

    _draw_foreground_foliage_and_grass(base, pal, rng)
    _render_chisel_3d_text(base, line1, line2, pal)
    base.convert("RGB").save(filepath, "JPEG", quality=82, optimize=True)


def prepare_all_banners():
    cleanup_old_files()
    os.makedirs(IMG_DIR, exist_ok=True)
    lp = _find_user_file(USER_UPLOADED_MAP["logo.jpg"])
    logo_img = Image.open(lp).convert("RGBA") if lp else _make_fallback_logo()

    for target, cands in USER_UPLOADED_MAP.items():
        if target != "logo.jpg":
            found = _find_user_file(cands)
            if found:
                Image.open(found).convert("RGB").save(os.path.join(IMG_DIR, target), "JPEG", quality=86, optimize=True)

    for _, _, _, img_name, theme, (t1, t2), _, _ in CATEGORIES_DATA:
        dest = os.path.join(IMG_DIR, img_name)
        if not os.path.exists(dest):
            found = _find_user_file([img_name, img_name.replace(".jpg", ".png")])
            if found:
                Image.open(found).convert("RGB").save(dest, "JPEG", quality=86, optimize=True)
            else:
                generate_scenic_banner(dest, logo_img, theme, t1, t2)

    for img_name, theme, (t1, t2) in SERVICE_BANNERS:
        dest = os.path.join(IMG_DIR, img_name)
        if not os.path.exists(dest):
            found = _find_user_file([img_name, img_name.replace(".jpg", ".png")])
            if found:
                Image.open(found).convert("RGB").save(dest, "JPEG", quality=86, optimize=True)
            else:
                generate_scenic_banner(dest, logo_img, theme, t1, t2)

    FILE_HASHES.clear()
    for fn in os.listdir(IMG_DIR):
        if fn.endswith((".jpg", ".png")) and not fn.endswith("_thumb.jpg"):
            FILE_HASHES[fn] = _file_md5(os.path.join(IMG_DIR, fn))
    prepare_legal_documents()


# ================= БАЗА ДАННЫХ И КЭШ =================
async def init_db_and_cache():
    global DB_CONN
    DB_CONN = await aiosqlite.connect(DB_PATH, timeout=15)
    await DB_CONN.execute("PRAGMA journal_mode=WAL")
    await DB_CONN.execute("PRAGMA synchronous=NORMAL")
    await DB_CONN.execute("PRAGMA busy_timeout=5000")

    async with DB_LOCK:
        await DB_CONN.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, balance REAL DEFAULT 0, joined_at TEXT, accepted_terms INTEGER DEFAULT 0, referrer_id INTEGER DEFAULT NULL, ref_earnings REAL DEFAULT 0)")
        async with DB_CONN.execute("PRAGMA table_info(users)") as cur:
            ucols = {r[1] for r in await cur.fetchall()}
        if "accepted_terms" not in ucols:
            await DB_CONN.execute("ALTER TABLE users ADD COLUMN accepted_terms INTEGER DEFAULT 0")
        if "referrer_id" not in ucols:
            await DB_CONN.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        if "ref_earnings" not in ucols:
            await DB_CONN.execute("ALTER TABLE users ADD COLUMN ref_earnings REAL DEFAULT 0")
        await DB_CONN.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")

        await DB_CONN.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, short_name TEXT NOT NULL, full_title TEXT NOT NULL, image_name TEXT, description TEXT)")
        await DB_CONN.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, full_name TEXT NOT NULL, btn_label TEXT NOT NULL, old_price REAL NOT NULL, price REAL NOT NULL, image_name TEXT)")
        await DB_CONN.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_name TEXT, price REAL, pay_method TEXT, status TEXT DEFAULT 'pending', created_at TEXT, ref_paid INTEGER DEFAULT 0)")
        async with DB_CONN.execute("PRAGMA table_info(orders)") as cur:
            ocols = {r[1] for r in await cur.fetchall()}
        if "ref_paid" not in ocols:
            await DB_CONN.execute("ALTER TABLE orders ADD COLUMN ref_paid INTEGER DEFAULT 0")

        await DB_CONN.execute("CREATE TABLE IF NOT EXISTS media_cache_v2 (image_name TEXT PRIMARY KEY, file_id TEXT NOT NULL, file_hash TEXT NOT NULL)")
        await DB_CONN.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")

        async with DB_CONN.execute("SELECT COUNT(*) FROM categories") as cur:
            cat_count = (await cur.fetchone())[0]
        if cat_count == 0:
            for cid, sn, ft, cimg, _, _, cd, items in CATEGORIES_DATA:
                await DB_CONN.execute("INSERT INTO categories (id, short_name, full_title, image_name, description) VALUES (?, ?, ?, ?, ?)", (cid, sn, ft, cimg, cd))
                for fn, sb, op, np in items:
                    lbl = sb if "₽" in sb else f"{sb} • {np}₽"
                    await DB_CONN.execute("INSERT INTO products (category_id, full_name, btn_label, old_price, price, image_name) VALUES (?, ?, ?, ?, ?, ?)", (cid, fn, lbl, op, np, cimg))
        else:
            async with DB_CONN.execute("SELECT value FROM settings WHERE key = 'catalog_ver'") as cur:
                row = await cur.fetchone()
            if (row[0] if row else None) != CATALOG_SCHEMA_VERSION:
                for cid, sn, ft, cimg, _, _, cd, _ in CATEGORIES_DATA:
                    await DB_CONN.execute("UPDATE categories SET short_name = ?, full_title = ?, image_name = ?, description = ? WHERE id = ?", (sn, ft, cimg, cd, cid))

        await DB_CONN.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('catalog_ver', ?)", (CATALOG_SCHEMA_VERSION,))
        await DB_CONN.commit()

        PHOTO_CACHE.clear()
        DOC_CACHE.clear()
        async with DB_CONN.execute("SELECT image_name, file_id, file_hash FROM media_cache_v2") as cur:
            for k, fid, fh in await cur.fetchall():
                if FILE_HASHES.get(k) == fh:
                    (DOC_CACHE if k.startswith("doc:") else PHOTO_CACHE)[k] = fid

        KNOWN_USERS.clear()
        ACCEPTED_USERS.clear()
        async with DB_CONN.execute("SELECT user_id, COALESCE(accepted_terms, 0) FROM users") as cur:
            for uid, acc in await cur.fetchall():
                KNOWN_USERS.add(uid)
                if acc == 1:
                    ACCEPTED_USERS.add(uid)

    await reload_catalog_cache()


async def reload_catalog_cache():
    global RAM_CATALOG_KB, RAM_FORTNITE_KB
    RAM_CATS.clear(); RAM_CAT_ORDER.clear(); RAM_PRODS.clear(); RAM_CAT_KBS.clear(); RAM_CAT_CAPTIONS.clear()
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT id, short_name, full_title, image_name, description FROM categories ORDER BY id") as cur:
            cats = await cur.fetchall()
        async with DB_CONN.execute("SELECT id, category_id, full_name, btn_label, old_price, price, image_name FROM products ORDER BY id") as cur:
            prods = await cur.fetchall()

    cb, fb = InlineKeyboardBuilder(), InlineKeyboardBuilder()
    cb.button(text="🎮 Fortnite", callback_data="nav_fortnite")
    for cid, sn, ft, cimg, cd in cats:
        RAM_CAT_ORDER.append(cid)
        RAM_CATS[cid] = {"id": cid, "short_name": sn, "full_title": ft, "image_name": cimg, "description": cd}
        (fb if cid in FORTNITE_CAT_IDS else cb).button(text=sn, callback_data=f"cat_{cid}")
    cb.adjust(2); cb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home"))
    RAM_CATALOG_KB = cb.as_markup()

    fb.adjust(2, 1)
    fb.row(InlineKeyboardButton(text="🧶 Инструкция по привязке Xbox", callback_data="nav_xbox"))
    fb.row(InlineKeyboardButton(text="⬅️ В каталог", callback_data="nav_catalog"), InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home"))
    RAM_FORTNITE_KB = fb.as_markup()

    by_cat: dict[int, list] = {cid: [] for cid in RAM_CAT_ORDER}
    for pid, cid, fn, bl, op, pr, pi in prods:
        p = {"id": pid, "category_id": cid, "full_name": fn, "btn_label": bl, "old_price": op, "price": pr, "image_name": pi}
        RAM_PRODS[pid] = p
        by_cat.setdefault(cid, []).append(p)

    for cid, cat in RAM_CATS.items():
        pb, lines = InlineKeyboardBuilder(), []
        for p in by_cat.get(cid, []):
            pb.button(text=p["btn_label"], callback_data=f"prod_{p['id']}")
            lines.append(f"▫️ <b>{html.escape(p['full_name'])}</b> — <s>{p['old_price']:.0f}₽</s> <b><code>{p['price']:.0f} ₽</code></b>")
        pb.adjust(2)
        if cid in (1, 3):
            pb.row(InlineKeyboardButton(text="🧶 Инструкция по привязке Xbox", callback_data="nav_xbox"))
        back_cb = ("⬅️ К Fortnite", "nav_fortnite") if cid in FORTNITE_CAT_IDS else ("⬅️ Назад", "nav_catalog")
        pb.row(InlineKeyboardButton(text=back_cb[0], callback_data=back_cb[1]), InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home"))
        RAM_CAT_KBS[cid] = pb.as_markup()
        RAM_CAT_CAPTIONS[cid] = f"<b>{cat['full_title']}</b>\n━━━━━━━━━━━━━━━━━━━━\n{cat['description']}\n\n<blockquote>" + "\n".join(lines) + "</blockquote>\n👇 <b>Выберите нужную позицию:</b>"


async def _save_file_id_bg(k: str, fid: str):
    try:
        async with DB_LOCK:
            await DB_CONN.execute("INSERT OR REPLACE INTO media_cache_v2 (image_name, file_id, file_hash) VALUES (?, ?, ?)", (k, fid, FILE_HASHES.get(k, "")))
            await DB_CONN.commit()
    except Exception:
        pass


def _clean_username(u: str | None) -> str:
    u = (u or "").strip().lstrip("@")
    return u if (u and u.lower() not in ("клиент", "none", "без_ника") and re.fullmatch(r"[A-Za-z0-9_]{3,64}", u)) else ""


async def register_user(user, force_update: bool = False, referrer_id: int | None = None):
    uname, fname = user.username or "", user.first_name or "Гость"
    if user.id in KNOWN_USERS and not force_update:
        return
    is_new = user.id not in KNOWN_USERS
    valid_ref = referrer_id if (is_new and referrer_id and referrer_id != user.id and referrer_id in KNOWN_USERS) else None
    KNOWN_USERS.add(user.id)
    try:
        async with DB_LOCK:
            if is_new:
                await DB_CONN.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, accepted_terms, referrer_id) VALUES (?, ?, ?, ?, 0, ?)", (user.id, uname, fname, datetime.now().strftime("%d.%m.%Y"), valid_ref))
            await DB_CONN.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (uname, fname, user.id))
            await DB_CONN.commit()
    except Exception:
        if is_new:
            KNOWN_USERS.discard(user.id)


async def set_user_accepted(user, accepted: bool):
    val = 1 if accepted else 0
    async with DB_LOCK:
        await DB_CONN.execute(
            "INSERT INTO users (user_id, username, first_name, joined_at, accepted_terms) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, accepted_terms=excluded.accepted_terms",
            (user.id, user.username or "", user.first_name or "Гость", datetime.now().strftime("%d.%m.%Y"), val)
        )
        await DB_CONN.commit()
    KNOWN_USERS.add(user.id)
    (ACCEPTED_USERS.add if accepted else ACCEPTED_USERS.discard)(user.id)


# ================= ОТРИСОВКА ЭКРАНОВ =================
def _is_duplicate_click(uid: int, data: str | None) -> bool:
    if not data:
        return False
    now = time.monotonic()
    key = (uid, data)
    if now - LAST_CLICK.get(key, 0.0) < 0.35:
        return True
    LAST_CLICK[key] = now
    return False


async def _safe_delete(msg: Message | None):
    if msg:
        try:
            await msg.delete(request_timeout=5)
        except Exception:
            pass


async def _quick_answer(call: CallbackQuery, text: str | None = None, show_alert: bool = False):
    try:
        await call.answer(text=text, show_alert=show_alert, request_timeout=5)
    except Exception:
        pass


async def _send_fresh_photo(msg: Message, image_name: str, caption: str, kb: InlineKeyboardMarkup | None):
    fid = PHOTO_CACHE.get(image_name)
    sent = await msg.answer_photo(photo=fid or FSInputFile(os.path.join(IMG_DIR, image_name)), caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
    LAST_SCREEN_TAG[(sent.chat.id, sent.message_id)] = f"photo:{image_name}"
    if not fid and sent.photo:
        PHOTO_CACHE[image_name] = sent.photo[-1].file_id
        asyncio.create_task(_save_file_id_bg(image_name, sent.photo[-1].file_id))
    return sent


async def _send_fresh_doc(msg: Message, doc_key: str, caption: str, kb: InlineKeyboardMarkup | None):
    meta = DOC_META[doc_key]
    ckey = meta["cache_key"]
    fid = DOC_CACHE.get(ckey)
    if fid:
        sent = await msg.answer_document(document=fid, caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
    else:
        thumb = FSInputFile(meta["thumb_path"]) if os.path.exists(meta["thumb_path"]) else None
        sent = await msg.answer_document(document=FSInputFile(meta["disk_path"], filename=meta["send_name"]), thumbnail=thumb, caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
    LAST_SCREEN_TAG[(sent.chat.id, sent.message_id)] = ckey
    if not fid and sent.document:
        DOC_CACHE[ckey] = sent.document.file_id
        asyncio.create_task(_save_file_id_bg(ckey, sent.document.file_id))
    return sent


async def show_doc_screen(target: Message | CallbackQuery, doc_key: str, caption: str, kb: InlineKeyboardMarkup):
    meta = DOC_META[doc_key]
    ckey = meta["cache_key"]
    if isinstance(target, CallbackQuery):
        asyncio.create_task(_quick_answer(target))
        msg = target.message
        if not msg:
            return
        if LAST_SCREEN_TAG.get((msg.chat.id, msg.message_id)) == ckey and msg.document:
            try:
                await msg.edit_caption(caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                return
            except Exception:
                pass
        if msg.document:
            fid = DOC_CACHE.get(ckey)
            media = InputMediaDocument(media=fid, caption=caption, parse_mode=ParseMode.HTML) if fid else InputMediaDocument(media=FSInputFile(meta["disk_path"], filename=meta["send_name"]), thumbnail=FSInputFile(meta["thumb_path"]) if os.path.exists(meta["thumb_path"]) else None, caption=caption, parse_mode=ParseMode.HTML)
            try:
                ed = await msg.edit_media(media=media, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                LAST_SCREEN_TAG[(msg.chat.id, msg.message_id)] = ckey
                if not fid and ed and ed.document:
                    DOC_CACHE[ckey] = ed.document.file_id
                    asyncio.create_task(_save_file_id_bg(ckey, ed.document.file_id))
                return
            except Exception:
                pass
        LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)
        await _send_fresh_doc(msg, doc_key, caption, kb)
        asyncio.create_task(_safe_delete(msg))
    else:
        await _send_fresh_doc(target, doc_key, caption, kb)


async def show_screen(target: Message | CallbackQuery, image_name: str, caption: str, kb: InlineKeyboardMarkup, answer_cb: bool = True):
    tag = f"photo:{image_name}"
    if isinstance(target, CallbackQuery):
        if answer_cb:
            asyncio.create_task(_quick_answer(target))
        msg = target.message
        if not msg:
            return
        if msg.photo and LAST_SCREEN_TAG.get((msg.chat.id, msg.message_id)) == tag:
            try:
                await msg.edit_caption(caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except Exception:
                pass
        if msg.photo:
            fid = PHOTO_CACHE.get(image_name)
            try:
                ed = await msg.edit_media(media=InputMediaPhoto(media=fid or FSInputFile(os.path.join(IMG_DIR, image_name)), caption=caption, parse_mode=ParseMode.HTML), reply_markup=kb, request_timeout=REQ_TIMEOUT)
                LAST_SCREEN_TAG[(msg.chat.id, msg.message_id)] = tag
                if not fid and ed and ed.photo:
                    PHOTO_CACHE[image_name] = ed.photo[-1].file_id
                    asyncio.create_task(_save_file_id_bg(image_name, ed.photo[-1].file_id))
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except Exception:
                pass
        LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)
        await _send_fresh_photo(msg, image_name, caption, kb)
        asyncio.create_task(_safe_delete(msg))
    else:
        await _send_fresh_photo(target, image_name, caption, kb)


async def show_dynamic_photo(call: CallbackQuery, fid: str | None, fallback: str, caption: str, kb: InlineKeyboardMarkup):
    if not fid:
        return await show_screen(call, fallback, caption, kb)
    asyncio.create_task(_quick_answer(call))
    msg = call.message
    if not msg:
        return
    LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)
    if msg.photo:
        try:
            await msg.edit_media(media=InputMediaPhoto(media=fid, caption=caption, parse_mode=ParseMode.HTML), reply_markup=kb, request_timeout=REQ_TIMEOUT)
            return
        except Exception:
            pass
    try:
        await msg.answer_photo(photo=fid, caption=caption, reply_markup=kb, request_timeout=REQ_TIMEOUT)
    except Exception:
        await _send_fresh_photo(msg, fallback, caption, kb)
    asyncio.create_task(_safe_delete(msg))


# ================= КЛАВИАТУРЫ И ТЕКСТЫ =================
def reply_main_kb(uid: int) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="🛒 Каталог"), KeyboardButton(text="👤 Профиль")], [KeyboardButton(text="👥 Рефералка"), KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="📕 Правила")], [KeyboardButton(text="🆘 Поддержка")]]
    if uid == ADMIN_ID:
        rows[-1].append(KeyboardButton(text="⚙️ Админка"))
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="Меню Bombych Store...")


def inline_home_kb(uid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🛒 Каталог товаров", callback_data="nav_catalog")
    b.button(text="👤 Профиль", callback_data="nav_profile")
    b.button(text="👥 Рефералка", callback_data="nav_ref")
    b.button(text="🧶 Привязка Xbox", callback_data="nav_xbox")
    b.button(text="ℹ️ Информация", callback_data="nav_info")
    b.button(text="📕 Правила", callback_data="nav_rules")
    b.button(text="🆘 Поддержка", callback_data="nav_support")
    b.button(text="📄 Соглашение", callback_data="nav_terms")
    b.button(text="🔒 Политика", callback_data="nav_privacy")
    b.adjust(1, 2, 2, 2, 2)
    if uid == ADMIN_ID:
        b.row(InlineKeyboardButton(text="⚙️ Панель управления", callback_data="nav_admin"))
    return b.as_markup()


HOME_KB_USER, HOME_KB_ADMIN = inline_home_kb(0), inline_home_kb(ADMIN_ID)
GATE_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📄 Пользовательское соглашение", callback_data="gate_terms")], [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="gate_privacy")], [InlineKeyboardButton(text="✅ Принимаю условия", callback_data="legal_accept")], [InlineKeyboardButton(text="❌ Отказаться и выйти", callback_data="legal_decline")]])
GATE_DOC_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📄 Соглашение", callback_data="gate_terms"), InlineKeyboardButton(text="🔒 Политика", callback_data="gate_privacy")], [InlineKeyboardButton(text="✅ Принимаю условия", callback_data="legal_accept"), InlineKeyboardButton(text="❌ Отказаться", callback_data="legal_decline")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="gate_back")]])
INFO_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📄 Соглашение", callback_data="nav_terms"), InlineKeyboardButton(text="🔒 Политика", callback_data="nav_privacy")], [InlineKeyboardButton(text="🆘 Поддержка", callback_data="nav_support"), InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="nav_home")]])
RULES_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📄 Соглашение", callback_data="nav_terms"), InlineKeyboardButton(text="🔒 Политика", callback_data="nav_privacy")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav_home"), InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")]])
LEGAL_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📄 Соглашение", callback_data="nav_terms"), InlineKeyboardButton(text="🔒 Политика", callback_data="nav_privacy")], [InlineKeyboardButton(text="🆘 Поддержка", callback_data="nav_support"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")]])
SUPPORT_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"💬 Написать нам ({SUPPORT_USERNAME})", url=SUPPORT_LINK)], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="nav_home"), InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")]])
BACK_XBOX_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В Fortnite", callback_data="nav_fortnite"), InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home")]])

SAFE_SUPPORT_USER = html.escape(SUPPORT_USERNAME)
GATE_TEXT = "💜 <b>Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>Чтобы начать пользоваться магазином, подтвердите согласие с <b>Пользовательским соглашением</b> и <b>Политикой конфиденциальности</b>.</blockquote>\n👇 Вы можете открыть файлы документов ниже или сразу перейти в магазин:"
TERMS_DOC_CAPTION = "📄 <b>Пользовательское соглашение • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>Правила оформления, оплаты и выдачи заказов (05:00–22:00 МСК), условия возврата и ответственность сторон.</blockquote>\n👆 <b>Нажмите на файл выше, чтобы открыть полный документ.</b>"
PRIVACY_DOC_CAPTION = "🔒 <b>Политика конфиденциальности • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>Порядок сбора, хранения и защиты данных, запрет на передачу третьим лицам и правила удаления профиля.</blockquote>\n👆 <b>Нажмите на файл выше, чтобы открыть полный документ.</b>"
HOME_TEXT = f"💜 <b>Bombych Store • Магазин игрового доната</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>🎮 <b>Fortnite:</b> В-Баксы, ВБ подарком и Наборы\n🌴 <b>Новинка:</b> GTA VI для PlayStation и Xbox\n📱 <b>Игры:</b> Brawl Stars, Roblox, Genshin, Standoff 2, Clash, Free Fire, PUBG, Вирты\n💻 <b>Сервисы:</b> Telegram, Steam, Discord Nitro, ChatGPT, Spotify, ExitLag, Банки\n👥 <b>Рефералка:</b> приглашай друзей и получай <b>{REF_PERCENT}%</b> с их покупок!</blockquote>\n⏰ <b>График выдачи:</b> <code>05:00 – 22:00 (МСК)</code>\n⚡ Прием заказов — <b>24/7</b>\n\n👇 <b>Выберите нужный раздел:</b>"
CATALOG_TEXT = "🛒 <b>Каталог • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>🔥 <b>Выгодные цены</b> на игры, донат и подписки\n🛡 Официальное пополнение и 100% гарантия выдачи</blockquote>\n👇 <b>Выберите интересующую категорию:</b>"
FORTNITE_TEXT = "🎮 <b>Fortnite • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>💎 <b>В-Баксы</b> — пополнение на аккаунт\n🎁 <b>ВБ подарком</b> — скины и эмоции подарком\n📦 <b>Наборы</b> — Отряд Fortnite, стартер-паки и БП</blockquote>\n👇 <b>Выберите нужный раздел Fortnite:</b>"
INFO_TEXT = "❗ <b>Информация • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n⏰ <b>Время работы:</b> <code>05:00 — 22:00 (МСК)</code>\n\n<blockquote>Мы не сохраняем данные от ваших аккаунтов после выполнения заказа. Вся информация используется только для зачисления доната и сразу удаляется.</blockquote>"
RULES_TEXT = "📕 <b>Правила • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<b>1. Уважение</b> — общайтесь вежливо с поддержкой.\n<b>2. Заказы</b> — прикрепляйте только действительные чеки.\n<b>3. Гарантии</b> — 100% выдача оплаченного товара."
SUPPORT_TEXT = f"🆘 <b>Поддержка • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>По любым вопросам — помощь с выбором, оплата, статус заказа, возврат или сотрудничество — обращайтесь к нам в Telegram.</blockquote>\n👤 <b>Контакт поддержки:</b> {SAFE_SUPPORT_USER}\n⏰ <b>Время ответа:</b> <code>05:00 – 22:00 (МСК)</code>\n\n👇 <b>Нажмите кнопку ниже, чтобы написать нам:</b>"
XBOX_TEXT = "✅ <b>Инструкция по привязке аккаунта Xbox</b>\n━━━━━━━━━━━━━━━━━━━━\n<b>1.</b> Создайте учётную запись Microsoft (регион <b>РОССИЯ</b>, <b>18+</b>): <a href='https://www.microsoft.com/ru-ru'>microsoft.com/ru-ru</a>\n<b>2.</b> В Epic Games откройте <b>Соединения → XBOX → Подключить</b>: <a href='https://www.epicgames.com/account/connections'>epicgames.com/account/connections</a>\n<b>3.</b> Готово!"


# ================= MIDDLEWARE (СОГЛАСИЕ + АНТИ-ДАБЛКЛИК) =================
class TermsGateMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and _is_duplicate_click(user.id, event.data):
            await _quick_answer(event)
            return None
        if user.id in ACCEPTED_USERS:
            return await handler(event, data)
        if isinstance(event, Message):
            t = (event.text or "").strip()
            if t.startswith("/start") or (user.id == ADMIN_ID and t.startswith("/reset_terms")):
                return await handler(event, data)
            await _send_fresh_photo(event, "main.jpg", GATE_TEXT, GATE_KB)
            return None
        if isinstance(event, CallbackQuery):
            if (event.data or "") in {"legal_accept", "legal_decline", "gate_terms", "gate_privacy", "gate_back"}:
                return await handler(event, data)
            await _quick_answer(event, "Сначала подтвердите согласие с Соглашением и Политикой.", show_alert=True)
            await show_screen(event, "main.jpg", GATE_TEXT, GATE_KB, answer_cb=False)
            return None
        return await handler(event, data)


router.message.middleware(TermsGateMiddleware())
router.callback_query.middleware(TermsGateMiddleware())


# ================= СОГЛАСИЕ И НАВИГАЦИЯ =================
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
    await state.clear()
    await set_user_accepted(call.from_user, True)
    msg = call.message
    if msg:
        LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)
        await msg.answer("💜 <b>Добро пожаловать в официальный магазин Bombych Store!</b>", reply_markup=reply_main_kb(call.from_user.id), request_timeout=REQ_TIMEOUT)
        await _send_fresh_photo(msg, "main.jpg", HOME_TEXT, HOME_KB_ADMIN if call.from_user.id == ADMIN_ID else HOME_KB_USER)
        asyncio.create_task(_safe_delete(msg))


@router.callback_query(F.data == "legal_decline")
async def cb_legal_decline(call: CallbackQuery, state: FSMContext):
    await _quick_answer(call, "Без принятия условий использование магазина невозможно.", show_alert=True)
    await state.clear()
    await set_user_accepted(call.from_user, False)
    msg = call.message
    if msg:
        LAST_SCREEN_TAG.pop((msg.chat.id, msg.message_id), None)
        await msg.answer("🚪 <b>Вы вышли из Bombych Store.</b>\nЧтобы вернуться — нажмите /start.", reply_markup=ReplyKeyboardRemove(), request_timeout=REQ_TIMEOUT)
        asyncio.create_task(_safe_delete(msg))


@router.message(Command("reset_terms"))
async def cmd_reset_terms(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await state.clear()
        await set_user_accepted(message.from_user, False)
        await _send_fresh_photo(message, "main.jpg", GATE_TEXT, GATE_KB)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    ref_id = None
    parts = (message.text or "").split()
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            ref_id = int(parts[1][4:])
        except ValueError:
            pass
    await register_user(message.from_user, force_update=True, referrer_id=ref_id)
    if message.from_user.id not in ACCEPTED_USERS:
        await _send_fresh_photo(message, "main.jpg", GATE_TEXT, GATE_KB)
        return
    await message.answer("💜 <b>Добро пожаловать в официальный магазин Bombych Store!</b>", reply_markup=reply_main_kb(message.from_user.id), request_timeout=REQ_TIMEOUT)
    await show_screen(message, "main.jpg", HOME_TEXT, HOME_KB_ADMIN if message.from_user.id == ADMIN_ID else HOME_KB_USER)


@router.callback_query(F.data == "nav_home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(call, "main.jpg", HOME_TEXT, HOME_KB_ADMIN if call.from_user.id == ADMIN_ID else HOME_KB_USER)


@router.message(Command("catalog"))
@router.message(F.text == "🛒 Каталог")
async def msg_catalog(m: Message, state: FSMContext):
    await state.clear()
    await show_screen(m, "catalog.jpg", CATALOG_TEXT, RAM_CATALOG_KB)


@router.callback_query(F.data == "nav_catalog")
async def cb_catalog(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(c, "catalog.jpg", CATALOG_TEXT, RAM_CATALOG_KB)


@router.callback_query(F.data == "nav_fortnite")
async def cb_fortnite(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(c, "fortnite.jpg", FORTNITE_TEXT, RAM_FORTNITE_KB)


@router.message(Command("info"))
@router.message(F.text.in_({"ℹ️ Инфо", "ℹ️ Информация"}))
async def msg_info(m: Message, state: FSMContext):
    await state.clear()
    await show_screen(m, "info.jpg", INFO_TEXT, INFO_KB)


@router.callback_query(F.data == "nav_info")
async def cb_info(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(c, "info.jpg", INFO_TEXT, INFO_KB)


@router.message(Command("rules"))
@router.message(F.text == "📕 Правила")
async def msg_rules(m: Message, state: FSMContext):
    await state.clear()
    await show_screen(m, "rules.jpg", RULES_TEXT, RULES_KB)


@router.callback_query(F.data == "nav_rules")
async def cb_rules(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(c, "rules.jpg", RULES_TEXT, RULES_KB)


@router.message(Command("terms"))
async def msg_terms(m: Message, state: FSMContext):
    await state.clear()
    await show_doc_screen(m, "terms", TERMS_DOC_CAPTION, LEGAL_KB)


@router.callback_query(F.data == "nav_terms")
async def cb_terms(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_doc_screen(c, "terms", TERMS_DOC_CAPTION, LEGAL_KB)


@router.message(Command("privacy"))
async def msg_privacy(m: Message, state: FSMContext):
    await state.clear()
    await show_doc_screen(m, "privacy", PRIVACY_DOC_CAPTION, LEGAL_KB)


@router.callback_query(F.data == "nav_privacy")
async def cb_privacy(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_doc_screen(c, "privacy", PRIVACY_DOC_CAPTION, LEGAL_KB)


@router.message(Command("xbox"))
@router.message(F.text.in_({"🧶 Привязка", "🧶 Привязка Xbox"}))
async def msg_xbox(m: Message, state: FSMContext):
    await state.clear()
    await show_screen(m, "xbox.jpg", XBOX_TEXT, BACK_XBOX_KB)


@router.callback_query(F.data == "nav_xbox")
async def cb_xbox(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(c, "xbox.jpg", XBOX_TEXT, BACK_XBOX_KB)


@router.message(Command("support"))
@router.message(F.text == "🆘 Поддержка")
async def cmd_support(m: Message, state: FSMContext):
    await state.clear()
    await show_screen(m, "support.jpg", SUPPORT_TEXT, SUPPORT_KB)


@router.callback_query(F.data == "nav_support")
async def cb_support(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_screen(c, "support.jpg", SUPPORT_TEXT, SUPPORT_KB)


# ================= ПРОФИЛЬ И РЕФЕРАЛЬНАЯ ПРОГРАММА (25%) =================
async def build_ref_view(user):
    await register_user(user)
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT balance, COALESCE(ref_earnings, 0) FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
        async with DB_CONN.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user.id,)) as cur:
            invited = (await cur.fetchone())[0]
    bal, earned = row if row else (0.0, 0.0)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(link)}&text={urllib.parse.quote('🔥 Выгодный донат в игры и подписки в Bombych Store! Заходи по моей ссылке:')}"
    text = (
        f"👥 <b>Реферальная программа • {REF_PERCENT}% с покупок</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>Приглашайте друзей по своей ссылке и получайте <b>{REF_PERCENT}%</b> на баланс с каждого их оплаченного заказа!</blockquote>\n"
        f"🔗 <b>Ваша ссылка</b> (нажмите, чтобы скопировать):\n<code>{link}</code>\n\n"
        f"👤 <b>Приглашено друзей:</b> <code>{invited} чел.</code>\n"
        f"💸 <b>Заработано всего:</b> <code>{earned:.0f} ₽</code>\n"
        f"💰 <b>Текущий баланс:</b> <code>{bal:.0f} ₽</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться с другом", url=share_url)],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="nav_profile"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")]
    ])
    return text, kb


@router.message(Command("ref"))
@router.message(F.text == "👥 Рефералка")
async def msg_ref(m: Message, state: FSMContext):
    await state.clear()
    t, kb = await build_ref_view(m.from_user)
    await show_screen(m, "referral.jpg", t, kb)


@router.callback_query(F.data == "nav_ref")
async def cb_ref(c: CallbackQuery, state: FSMContext):
    await state.clear()
    t, kb = await build_ref_view(c.from_user)
    await show_screen(c, "referral.jpg", t, kb)


async def build_profile_view(user):
    await register_user(user)
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT balance, joined_at FROM users WHERE user_id = ?", (user.id,)) as cur:
            row = await cur.fetchone()
        async with DB_CONN.execute("SELECT COUNT(*), COALESCE(SUM(price), 0) FROM orders WHERE user_id = ? AND status = 'completed'", (user.id,)) as cur:
            done_cnt, spent = await cur.fetchone()
    bal, joined = row if row else (0.0, datetime.now().strftime("%d.%m.%Y"))
    role = "Основатель ♦" if user.id == ADMIN_ID else ("VIP Покупатель 👑" if done_cnt >= 5 else ("Покупатель 💲" if done_cnt > 0 else "Клиент 🛴"))
    text = f"👤 <b>Личный кабинет • {html.escape(user.first_name or 'Гость')}</b>\n━━━━━━━━━━━━━━━━━━━━\n🆔 <b>Ваш ID:</b> <code>{user.id}</code>\n🎭 <b>Статус:</b> <b>{role}</b>\n📅 <b>Дата регистрации:</b> <code>{joined}</code>\n\n<blockquote>💰 <b>Баланс:</b> <code>{bal:.0f} ₽</code>\n📦 <b>Выполнено заказов:</b> <code>{done_cnt} шт.</code>\n💎 <b>Сумма покупок:</b> <code>{spent:.0f} ₽</code></blockquote>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"), InlineKeyboardButton(text="👥 Рефералка", callback_data="nav_ref")],
        [InlineKeyboardButton(text="🛒 В каталог", callback_data="nav_catalog"), InlineKeyboardButton(text="⬅️ Меню", callback_data="nav_home")]
    ])
    return text, kb


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def msg_profile(m: Message, state: FSMContext):
    await state.clear()
    t, kb = await build_profile_view(m.from_user)
    await show_screen(m, "profile.jpg", t, kb)


@router.callback_query(F.data == "nav_profile")
async def cb_profile(c: CallbackQuery, state: FSMContext):
    await state.clear()
    t, kb = await build_profile_view(c.from_user)
    await show_screen(c, "profile.jpg", t, kb)


@router.callback_query(F.data == "my_orders")
async def cb_my_orders(c: CallbackQuery, state: FSMContext):
    await state.clear()
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT id, product_name, price, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 8", (c.from_user.id,)) as cur:
            rows = await cur.fetchall()
    st_map = {"pending": "⏳ Ожидает оплаты", "checking": "🔎 На проверке", "completed": "✅ Выдан", "rejected": "❌ Отклонен"}
    body = "\n".join(f"• <b>#{o}</b> | {html.escape(p)} (<b>{pr:.0f}₽</b>) — {st_map.get(s, s)}" for o, p, pr, s in rows) if rows else "<i>У вас пока нет заказов.</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Профиль", callback_data="nav_profile"), InlineKeyboardButton(text="🛒 Каталог", callback_data="nav_catalog")]])
    await show_screen(c, "profile.jpg", f"📦 <b>История заказов</b>\n━━━━━━━━━━━━━━━━━━━━\n{body}", kb)


# ================= КАТЕГОРИИ, ТОВАРЫ И ОПЛАТА =================
@router.callback_query(F.data.startswith("cat_"))
async def cb_category(c: CallbackQuery, state: FSMContext):
    await state.clear()
    cid = int(c.data.split("_")[1])
    if cid not in RAM_CATS:
        return await _quick_answer(c, "Раздел не найден", show_alert=True)
    await show_screen(c, RAM_CATS[cid]["image_name"], RAM_CAT_CAPTIONS[cid], RAM_CAT_KBS[cid])


@router.callback_query(F.data.startswith("prod_"))
async def cb_product(c: CallbackQuery, state: FSMContext):
    await state.clear()
    pid = int(c.data.split("_")[1])
    prod = RAM_PRODS.get(pid)
    if not prod:
        return await _quick_answer(c, "Товар не найден", show_alert=True)
    cat = RAM_CATS[prod["category_id"]]
    cap = f"🛍 <b>Оформление заказа</b>\n━━━━━━━━━━━━━━━━━━━━\n📂 Категория: <b>{cat['full_title']}</b>\n💎 Товар: <b>{html.escape(prod['full_name'])}</b>\n💰 Стоимость: <s>{prod['old_price']:.0f} ₽</s> <b><code>{prod['price']:.0f} ₽</code></b>\n\n<blockquote>{cat['description']}</blockquote>\n👇 <b>Выберите удобный способ оплаты:</b>"
    b = InlineKeyboardBuilder()
    b.button(text="🧡 DonationAlerts", callback_data=f"pay_da_{pid}")
    b.button(text="🪙 Криптовалюта", callback_data=f"pay_crypto_{pid}")
    b.button(text="💳 СБП / Карта", callback_data="pay_sbp_soon")
    b.button(text="⬅️ Назад", callback_data=f"cat_{prod['category_id']}")
    b.button(text="🎮 Fortnite" if prod["category_id"] in FORTNITE_CAT_IDS else "🛒 Каталог", callback_data="nav_fortnite" if prod["category_id"] in FORTNITE_CAT_IDS else "nav_catalog")
    b.adjust(2, 1, 2)
    await show_screen(c, prod["image_name"], cap, b.as_markup())


@router.callback_query(F.data == "pay_sbp_soon")
async def cb_sbp_soon(c: CallbackQuery):
    await _quick_answer(c, "⏳ Оплата по СБП скоро появится! Сейчас доступны DonationAlerts и Криптовалюта (TON).", show_alert=True)


@router.callback_query(F.data.startswith(("pay_da_", "pay_crypto_")))
async def cb_pay(c: CallbackQuery, state: FSMContext):
    parts = c.data.split("_")
    method, pid = parts[1], int(parts[2])
    prod = RAM_PRODS.get(pid)
    if not prod:
        return await _quick_answer(c, "Товар не найден", show_alert=True)
    asyncio.create_task(_quick_answer(c))
    await register_user(c.from_user)
    m_name = "DonationAlerts" if method == "da" else "Криптовалюта (TON)"
    async with DB_LOCK:
        async with DB_CONN.execute("INSERT INTO orders (user_id, product_name, price, pay_method, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)", (c.from_user.id, prod["full_name"], prod["price"], m_name, datetime.now().strftime("%d.%m.%Y %H:%M"))) as cur:
            oid = cur.lastrowid
        await DB_CONN.commit()
    await state.update_data(order_id=oid, fname=prod["full_name"], price=prod["price"], pid=pid)
    cap = f"🧾 <b>Счет на оплату • Заказ #{oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n💎 Товар: <b>{html.escape(prod['full_name'])}</b>\n💰 К оплате: <b><code>{prod['price']:.0f} ₽</code></b>\n\n{PAYMENT_DA_TEXT if method == 'da' else PAYMENT_CRYPTO_TEXT}"
    btns = []
    if method == "da":
        btns.append([InlineKeyboardButton(text="🧡 Перейти к оплате (DonationAlerts)", url=DONATIONALERTS_URL)])
    btns.append([InlineKeyboardButton(text="📸 Отправить чек", callback_data=f"sendcheck_{oid}_{pid}")])
    btns.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"prod_{pid}"), InlineKeyboardButton(text="❌ Отмена", callback_data=f"cat_{prod['category_id']}")])
    await show_screen(c, prod["image_name"], cap, InlineKeyboardMarkup(inline_keyboard=btns), answer_cb=False)


@router.callback_query(F.data.startswith("sendcheck_"))
async def cb_sendcheck(c: CallbackQuery, state: FSMContext):
    asyncio.create_task(_quick_answer(c))
    parts = c.data.split("_")
    oid, pid = int(parts[1]), int(parts[2])
    data = await state.get_data()
    fname, price = data.get("fname"), data.get("price")
    if not fname or price is None:
        async with DB_LOCK:
            async with DB_CONN.execute("SELECT product_name, price FROM orders WHERE id = ?", (oid,)) as cur:
                row = await cur.fetchone()
        if row:
            fname, price = row
    await state.update_data(order_id=oid, fname=fname or "Товар", price=price or 0, pid=pid)
    await state.set_state(OrderFlow.waiting_receipt)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ К товару", callback_data=f"prod_{pid}"), InlineKeyboardButton(text="❌ Отмена", callback_data="nav_home")]])
    await c.message.answer(f"📸 <b>Прикрепите скриншот или файл чека по заказу #{oid}.</b>\n<i>В подписи укажите игровой ID, UID, тег или почту.</i>", reply_markup=kb, request_timeout=REQ_TIMEOUT)


@router.message(OrderFlow.waiting_receipt, F.photo | F.document)
async def receive_receipt(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid, fname, price = data.get("order_id", 0), data.get("fname", "Товар"), data.get("price", 0)
    await state.clear()
    async with DB_LOCK:
        await DB_CONN.execute("UPDATE orders SET status = 'checking' WHERE id = ?", (oid,))
        await DB_CONN.commit()
    adm_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать заказ", callback_data=f"adm_ok_{oid}_{m.from_user.id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_no_{oid}_{m.from_user.id}")]])
    adm_cap = f"🔔 <b>Новый чек • Заказ #{oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 Клиент: @{html.escape(m.from_user.username or 'без_ника')} (<code>{m.from_user.id}</code>)\n💎 Товар: <b>{html.escape(str(fname))}</b>\n💰 Сумма: <b>{price:.0f} ₽</b>\n💬 Комментарий: <blockquote>{html.escape(m.caption or 'Без комментария')}</blockquote>"
    try:
        if m.photo:
            await bot.send_photo(ADMIN_ID, m.photo[-1].file_id, caption=adm_cap, reply_markup=adm_kb, request_timeout=REQ_TIMEOUT)
        else:
            await bot.send_document(ADMIN_ID, m.document.file_id, caption=adm_cap, reply_markup=adm_kb, request_timeout=REQ_TIMEOUT)
    except Exception as e:
        logging.error(f"Ошибка пересылки чека #{oid}: {e}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")]])
    await m.answer(f"✅ <b>Чек по заказу #{oid} отправлен на проверку!</b>", reply_markup=kb, request_timeout=REQ_TIMEOUT)


@router.message(OrderFlow.waiting_receipt)
async def wrong_receipt(m: Message):
    await m.answer("⚠️ Отправьте <b>скриншот, фото или файл</b> чека.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="nav_home")]]), request_timeout=REQ_TIMEOUT)


# ================= АДМИН-ПАНЕЛЬ, УЧАСТНИКИ И ВЫПЛАТА 25% =================
@router.callback_query(F.data.startswith("adm_ok_"))
async def cb_adm_ok(c: CallbackQuery, bot: Bot):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    _, _, oid_s, uid_s = c.data.split("_")
    oid, uid = int(oid_s), int(uid_s)
    reward, ref_uid = 0, None
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT price, COALESCE(ref_paid, 0) FROM orders WHERE id = ?", (oid,)) as cur:
            o_row = await cur.fetchone()
        await DB_CONN.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (oid,))
        if o_row and o_row[1] == 0:
            async with DB_CONN.execute("SELECT referrer_id FROM users WHERE user_id = ?", (uid,)) as cur:
                u_row = await cur.fetchone()
            if u_row and u_row[0]:
                ref_uid = u_row[0]
                reward = int(round(float(o_row[0] or 0) * REF_PERCENT / 100))
                if reward > 0:
                    await DB_CONN.execute("UPDATE users SET balance = balance + ?, ref_earnings = COALESCE(ref_earnings, 0) + ? WHERE user_id = ?", (reward, reward, ref_uid))
                    await DB_CONN.execute("UPDATE orders SET ref_paid = 1 WHERE id = ?", (oid,))
        await DB_CONN.commit()
    try:
        await bot.send_message(uid, f"🎉 <b>Оплата по заказу #{oid} подтверждена!</b>\nЗаказ принят к выдаче. Спасибо за покупку в <b>Bombych Store</b>!", request_timeout=REQ_TIMEOUT)
    except Exception:
        pass
    if ref_uid and reward > 0:
        try:
            await bot.send_message(ref_uid, f"💸 <b>Реферальный бонус +{reward} ₽!</b>\nВаш друг оплатил заказ, и вам начислено <b>{REF_PERCENT}%</b> на баланс.", request_timeout=REQ_TIMEOUT)
        except Exception:
            pass
    try:
        await c.message.edit_caption(caption=(c.message.caption or "") + "\n\n✅ <b>ВЫПОЛНЕНО</b>", request_timeout=REQ_TIMEOUT)
    except Exception:
        pass
    await _quick_answer(c, "Заказ подтвержден!")


@router.callback_query(F.data.startswith("adm_no_"))
async def cb_adm_no(c: CallbackQuery, bot: Bot):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    _, _, oid_s, uid_s = c.data.split("_")
    oid, uid = int(oid_s), int(uid_s)
    async with DB_LOCK:
        await DB_CONN.execute("UPDATE orders SET status = 'rejected' WHERE id = ?", (oid,))
        await DB_CONN.commit()
    try:
        await bot.send_message(uid, f"❌ <b>Заказ #{oid} отклонен.</b>\nОплата не найдена. Напишите нам в поддержку ({SAFE_SUPPORT_USER}).", request_timeout=REQ_TIMEOUT)
    except Exception:
        pass
    try:
        await c.message.edit_caption(caption=(c.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>", request_timeout=REQ_TIMEOUT)
    except Exception:
        pass
    await _quick_answer(c, "Отклонено.")


@router.message(Command("admin"))
@router.message(F.text.in_({"⚙️ Админка", "⚙️ Админ-панель"}))
async def msg_admin(m: Message, state: FSMContext):
    await state.clear()
    if m.from_user.id == ADMIN_ID:
        await render_admin(m)


@router.callback_query(F.data == "nav_admin")
async def cb_admin(c: CallbackQuery, state: FSMContext):
    await state.clear()
    if c.from_user.id == ADMIN_ID:
        await render_admin(c)
    else:
        await _quick_answer(c)


async def render_admin(target):
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT COUNT(*) FROM users") as cur:
            u_cnt = (await cur.fetchone())[0]
        async with DB_CONN.execute("SELECT COUNT(*), COALESCE(SUM(price), 0) FROM orders WHERE status = 'completed'") as cur:
            o_cnt, rev = await cur.fetchone()
    text = f"⚙️ <b>Панель управления • Bombych Store</b>\n━━━━━━━━━━━━━━━━━━━━\n👥 <b>Клиентов в базе:</b> <code>{u_cnt}</code>\n✅ <b>Выполнено заказов:</b> <code>{o_cnt}</code>\n💰 <b>Общая выручка:</b> <code>{rev:.0f} ₽</code>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"👥 Участники ({u_cnt})", callback_data="adm_users_0")], [InlineKeyboardButton(text="➕ Добавить товар", callback_data="adm_add_item"), InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")], [InlineKeyboardButton(text="🏠 Главное меню", callback_data="nav_home")]])
    await show_screen(target, "main.jpg", text, kb)


@router.callback_query(F.data.startswith("adm_users_"))
async def cb_adm_users(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    await state.clear()
    page = max(0, int(c.data.split("_")[2]))
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        tp = max(1, math.ceil(total / USERS_PER_PAGE))
        page = min(page, tp - 1)
        async with DB_CONN.execute("SELECT user_id, username, first_name FROM users ORDER BY rowid DESC LIMIT ? OFFSET ?", (USERS_PER_PAGE, page * USERS_PER_PAGE)) as cur:
            rows = await cur.fetchall()
    b, lines = InlineKeyboardBuilder(), []
    for i, (uid, un, fn) in enumerate(rows, page * USERS_PER_PAGE + 1):
        cu = _clean_username(un)
        lines.append(f"{i}. <b>{html.escape((fn or 'Гость')[:24])}</b> ({'@' + html.escape(cu) if cu else 'без ника'}) • <code>{uid}</code>")
        bt = f"@{cu}" if cu else (fn or str(uid))
        b.button(text=f"👤 {bt[:17]}", callback_data=f"adm_user_{uid}_{page}")
    b.adjust(2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"adm_users_{page - 1}"))
    if tp > 1:
        nav.append(InlineKeyboardButton(text=f"📄 {page + 1}/{tp}", callback_data="noop"))
    if page + 1 < tp:
        nav.append(InlineKeyboardButton(text="След. ➡️", callback_data=f"adm_users_{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⚙️ В админку", callback_data="nav_admin"), InlineKeyboardButton(text="🏠 Меню", callback_data="nav_home"))
    await show_screen(c, "profile.jpg", f"👥 <b>Участники • Всего: {total}</b> (стр. {page + 1}/{tp})\n━━━━━━━━━━━━━━━━━━━━\n<blockquote>" + ("\n".join(lines) or "<i>Пусто</i>") + "</blockquote>", b.as_markup())


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await _quick_answer(c)


@router.callback_query(F.data.startswith("adm_user_"))
async def cb_adm_user_card(c: CallbackQuery, state: FSMContext, bot: Bot):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    await state.clear()
    parts = c.data.split("_")
    uid, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT username, first_name, balance, joined_at FROM users WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        async with DB_CONN.execute("SELECT COUNT(*), SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), COALESCE(SUM(CASE WHEN status='completed' THEN price ELSE 0 END), 0) FROM orders WHERE user_id = ?", (uid,)) as cur:
            tot_o, done_o, spent = await cur.fetchone()
    if not row:
        return await _quick_answer(c, "Не найден", show_alert=True)
    uname, fname, bal, joined = row
    avatar_fid = None
    try:
        ph = await bot.get_user_profile_photos(uid, limit=1, request_timeout=5)
        if ph.total_count > 0:
            avatar_fid = ph.photos[0][-1].file_id
    except Exception:
        pass
    cu = _clean_username(uname)
    cap = f"👤 <b>Карточка участника</b>\n━━━━━━━━━━━━━━━━━━━━\n📛 <b>Имя:</b> {html.escape(fname or 'Гость')}\n🔗 <b>Юзернейм:</b> {'@' + html.escape(cu) if cu else '<i>нет</i>'}\n🆔 <b>ID:</b> <code>{uid}</code>\n📅 <b>В боте с:</b> <code>{joined or '—'}</code>\n\n<blockquote>💰 <b>Баланс:</b> <code>{bal:.0f} ₽</code>\n📦 <b>Заказов всего / выдано:</b> <code>{tot_o} / {done_o or 0}</code>\n💎 <b>Сумма покупок:</b> <code>{spent:.0f} ₽</code></blockquote>"
    btns = [[InlineKeyboardButton(text=f"💬 Написать @{cu}", url=f"https://t.me/{cu}")]] if cu else []
    btns.append([InlineKeyboardButton(text="⬅️ К списку", callback_data=f"adm_users_{page}"), InlineKeyboardButton(text="⚙️ Админка", callback_data="nav_admin")])
    await show_dynamic_photo(c, avatar_fid, "profile.jpg", cap, InlineKeyboardMarkup(inline_keyboard=btns))


@router.callback_query(F.data == "adm_add_item")
async def cb_adm_add_item(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    asyncio.create_task(_quick_answer(c))
    b = InlineKeyboardBuilder()
    for cid in RAM_CAT_ORDER:
        b.button(text=f"FN: {RAM_CATS[cid]['short_name']}" if cid in FORTNITE_CAT_IDS else RAM_CATS[cid]["short_name"], callback_data=f"admcat_{cid}")
    b.adjust(2); b.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="nav_admin"))
    await c.message.answer("📂 <b>Выберите категорию:</b>", reply_markup=b.as_markup(), request_timeout=REQ_TIMEOUT)


@router.callback_query(F.data.startswith("admcat_"))
async def cb_adm_pick_cat(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    asyncio.create_task(_quick_answer(c))
    await state.update_data(cid=int(c.data.split("_")[1]))
    await state.set_state(AdminFlow.add_full_name)
    await c.message.answer("✏️ Введите <b>полное название товара</b>:", request_timeout=REQ_TIMEOUT)


@router.message(AdminFlow.add_full_name)
async def adm_set_fname(m: Message, state: FSMContext):
    await state.update_data(fname=(m.text or "").strip())
    await state.set_state(AdminFlow.add_short_btn)
    await m.answer("🔘 Введите <b>короткое название для кнопки</b>:", request_timeout=REQ_TIMEOUT)


@router.message(AdminFlow.add_short_btn)
async def adm_set_sbtn(m: Message, state: FSMContext):
    await state.update_data(sbtn=(m.text or "").strip())
    await state.set_state(AdminFlow.add_price)
    await m.answer("💰 Введите <b>цену в рублях</b> (или две цены через пробел: <code>старая новая</code>):", request_timeout=REQ_TIMEOUT)


@router.message(AdminFlow.add_price)
async def adm_save_product(m: Message, state: FSMContext):
    parts = (m.text or "").replace(",", ".").split()
    try:
        old_p, new_p = (int(float(parts[0])), int(float(parts[1]))) if len(parts) >= 2 else (int(float(parts[0])), max(10, int(round(float(parts[0]) * 0.8))))
    except (ValueError, IndexError):
        return await m.answer("⚠️ Введите число:", request_timeout=REQ_TIMEOUT)
    d = await state.get_data()
    await state.clear()
    lbl = f"{d['sbtn']} • {new_p}₽"
    async with DB_LOCK:
        await DB_CONN.execute("INSERT INTO products (category_id, full_name, btn_label, old_price, price, image_name) VALUES (?, ?, ?, ?, ?, ?)", (d["cid"], d["fname"], lbl, old_p, new_p, RAM_CATS.get(d["cid"], {}).get("image_name", "catalog.jpg")))
        await DB_CONN.commit()
    await reload_catalog_cache()
    await m.answer(f"✅ Товар <b>{html.escape(d['fname'])}</b> добавлен ({new_p}₽)!", request_timeout=REQ_TIMEOUT)


@router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        return await _quick_answer(c)
    asyncio.create_task(_quick_answer(c))
    await state.set_state(AdminFlow.waiting_broadcast)
    await c.message.answer("📢 Введите текст рассылки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="nav_admin")]]), request_timeout=REQ_TIMEOUT)


@router.message(AdminFlow.waiting_broadcast)
async def run_broadcast(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    async with DB_LOCK:
        async with DB_CONN.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()
    txt, sent = html.escape(m.text or ""), 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Новости • Bombych Store</b>\n\n{txt}", request_timeout=8)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await m.answer(f"✅ Рассылка доставлена <b>{sent}</b> клиентам.", request_timeout=REQ_TIMEOUT)


@router.error()
async def global_error_handler(event: ErrorEvent):
    logging.exception(f"Ошибка: {event.exception}")
    if event.update.callback_query:
        await _quick_answer(event.update.callback_query, "⚠️ Временный сбой, нажмите ещё раз.")


async def main():
    global BOT_USERNAME
    if not BOT_TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN!")
    prepare_all_banners()
    await init_db_and_cache()

    session = AiohttpSession(timeout=25)
    if hasattr(session, "_connector_init") and isinstance(session._connector_init, dict):
        session._connector_init["keepalive_timeout"] = 10

    bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_USERNAME = (await bot.get_me()).username or ""

    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="catalog", description="🛒 Каталог"),
        BotCommand(command="profile", description="👤 Профиль"),
        BotCommand(command="ref", description="👥 Рефералка"),
        BotCommand(command="xbox", description="🧶 Привязка Xbox"),
        BotCommand(command="info", description="ℹ️ Информация"),
        BotCommand(command="rules", description="📕 Правила"),
        BotCommand(command="terms", description="📄 Соглашение"),
        BotCommand(command="privacy", description="🔒 Политика"),
        BotCommand(command="support", description="🆘 Поддержка"),
    ], scope=BotCommandScopeDefault())

    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info(f"Bombych Store v18 (@{BOT_USERNAME}) успешно запущен!")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), polling_timeout=10)
    finally:
        await bot.session.close()
        if DB_CONN:
            await DB_CONN.close()


if __name__ == "__main__":
    asyncio.run(main())
