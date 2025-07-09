from dotenv import load_dotenv
import os
import asyncio
import logging
import aiosqlite
import aiohttp
import json
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton
from aiogram.methods import DeleteWebhook
from aiogram.utils.keyboard import InlineKeyboardBuilder


# Загрузка переменных окружения из файла .env
load_dotenv()

# Проверка обязательных переменных
required_vars = ['TELEGRAM_TOKEN', 'MISTRAL_API_KEY', 'CRYPTOCLOUD_API_KEY', 'CRYPTOCLOUD_SHOP_ID']
missing_vars = [var for var in required_vars if os.getenv(var) is None]

if missing_vars:
    raise ValueError(f"Не заданы обязательные переменные окружения: {', '.join(missing_vars)}. Создайте файл .env с этими переменными.")

# Присваивание переменных
TOKEN = os.getenv('TELEGRAM_TOKEN')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
CRYPTOCLOUD_API_KEY = os.getenv('CRYPTOCLOUD_API_KEY')
CRYPTOCLOUD_SHOP_ID = os.getenv('CRYPTOCLOUD_SHOP_ID')
CRYPTOCLOUD_PAYMENT_LINK = f"https://pay.cryptocloud.plus/pos/{CRYPTOCLOUD_SHOP_ID}"

# Инициализация бота
logging.basicConfig(level=logging.INFO)
bot = Bot(str(TOKEN))
dp = Dispatcher()

# Настройки
SUBSCRIPTION_PRICE = 300  # 3 USD
SUBSCRIPTION_PRICE_3 = 3
MISTRAL_MODEL = "mistral-medium-latest"
MAX_FREE_REQUESTS_PER_DAY = 10  # Лимит бесплатных запросов


async def init_db():
    """Функция для создания бд."""
    async with aiosqlite.connect("users.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                subscribed_until TEXT,
                last_request_date TEXT,
                requests_today INTEGER DEFAULT 0,
                invoice_id TEXT
            )
        """)
        await db.commit()


async def reset_daily_limits():
    """Сбрасывает дневные лимиты для всех пользователей."""
    async with aiosqlite.connect("users.db") as db:
        await db.execute(
            "UPDATE users SET requests_today = 0"
        )
        await db.commit()


async def create_cryptocloud_invoice(user_id: int, amount: float) -> dict:
    """
    Создает новый счет на оплату в CryptoCloud.

    Args:
        user_id (int): ID пользователя Telegram
        amount (float): Сумма оплаты в USD

    Returns:
        dict: Ответ API CryptoCloud или словарь с ошибкой
    """
    headers = {
        "Authorization": f"Token {CRYPTOCLOUD_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "shop_id": CRYPTOCLOUD_SHOP_ID,
        "amount": str(amount),
        "currency": "USD",
        "order_id": f"sub_{user_id}_{int(datetime.now().timestamp())}",
        "add_fields": {
            "available_currencies": ["USDT_TRC20", "USDT_ERC20", "BTC"]
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.cryptocloud.plus/v2/invoice/create",
                headers=headers,
                json=data
            ) as resp:
                response_data = await resp.json()

                if resp.status != 200:
                    error_msg = response_data.get("message", "Unknown error")
                    logging.error(f"CryptoCloud Error {resp.status}: {error_msg}")
                    return {"error": f"Payment creation failed: {error_msg}"}

                if response_data.get("status") != "success":
                    logging.error(f"CryptoCloud API Error: {response_data}")
                    return {"error": "Payment creation failed"}

                return response_data

    except Exception as e:
        logging.error(f"CryptoCloud Connection Error: {str(e)}")
        return {"error": f"Connection error: {str(e)}"}


async def check_invoice_status(invoice_id: str) -> str:
    """
    Проверяет статус счета в CryptoCloud.

    Args:
        invoice_id (str): ID счета для проверки

    Returns:
        str: Статус счета ('paid', 'created' и т.д.) или 'error' при ошибке
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.cryptocloud.plus/v2/invoice/info?uuid={invoice_id}",
            headers={"Authorization": f"Token {CRYPTOCLOUD_API_KEY}"}
        ) as resp:
            data = await resp.json()
            return data.get("result", {}).get("status", "error")


async def get_mistral_response(prompt: str) -> str:
    """
    Получает ответ от Mistral AI на заданный промпт.

    Args:
        prompt (str): Текст запроса пользователя

    Returns:
        str: Ответ от модели или сообщение об ошибке
    """
    try:
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 2000
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"]
                elif response.status == 429:
                    return "⚠ Система перегружена. Пожалуйста, попробуйте позже."
                else:
                    error = await response.text()
                    raise Exception(f"Mistral API Error {response.status}: {error}")

    except Exception as e:
        logging.error(f"Mistral Error: {e}")
        return "⚠ Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже."


async def check_access(user_id: int) -> bool:
    """Проверяет доступ пользователя и обновляет счетчик запросов."""
    today = datetime.now().strftime("%Y-%m-%d")

    async with aiosqlite.connect("users.db") as db:
        # Получаем текущие данные пользователя
        cursor = await db.execute(
            "SELECT subscribed_until, last_request_date, requests_today FROM users WHERE user_id = ?",
            (user_id,)
        )
        user = await cursor.fetchone()

        if not user:
            # Новый пользователь - добавляем в базу
            await db.execute(
                "INSERT INTO users (user_id, last_request_date, requests_today) VALUES (?, ?, 1)",
                (user_id, today)
            )
            await db.commit()
            return True

        subscribed_until, last_request_date, requests_today = user

        # Проверяем подписку
        if subscribed_until and datetime.now() < datetime.fromisoformat(subscribed_until):
            return True

        # Проверяем дневной лимит
        if last_request_date != today:
            # Новый день - сбрасываем счетчик
            await db.execute(
                "UPDATE users SET last_request_date = ?, requests_today = 1 WHERE user_id = ?",
                (today, user_id)
            )
            await db.commit()
            return True
        elif requests_today < MAX_FREE_REQUESTS_PER_DAY:
            # Увеличиваем счетчик запросов
            await db.execute(
                "UPDATE users SET requests_today = requests_today + 1 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()
            return True

        return False


async def get_remaining_requests(user_id: int) -> int:
    """Возвращает количество оставшихся бесплатных запросов."""
    today = datetime.now().strftime("%Y-%m-%d")

    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute(
            "SELECT last_request_date, requests_today FROM users WHERE user_id = ?",
            (user_id,)
        )
        user = await cursor.fetchone()

        if not user:
            return MAX_FREE_REQUESTS_PER_DAY

        last_request_date, requests_today = user

        if last_request_date != today:
            return MAX_FREE_REQUESTS_PER_DAY
        else:
            return max(0, MAX_FREE_REQUESTS_PER_DAY - requests_today)


async def update_subscription(user_id: int, months: int = 1):
    """
    Обновляет дату окончания подписки пользователя.

    Args:
        user_id (int): ID пользователя Telegram
        months (int): Количество месяцев подписки (по умолчанию 1)
    """
    async with aiosqlite.connect("users.db") as db:
        subscribed_until = datetime.now() + timedelta(days=30*months)
        await db.execute(
            "UPDATE users SET subscribed_until = ? WHERE user_id = ?",
            (subscribed_until.isoformat(), user_id)
        )
        await db.commit()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """
    Обрабатывает команду /start.

    Приветствует пользователя и показывает количество оставшихся запросов.

    Args:
        message (Message): Входящее сообщение с командой /start
    """
    if message.from_user is None:
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="💳 Купить подписку (3 USD)", 
        callback_data="buy_subscription")
    )

    remaining = await get_remaining_requests(message.from_user.id)
    await message.answer(
        f"🤖 Привет! Я бот с Mistral AI.\n\n"
        f"🎁 У вас осталось {remaining} бесплатных запросов сегодня\n"
        f"🔓 Для неограниченного доступа оформите подписку.",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: types.CallbackQuery):
    """
    Обрабатывает запрос на покупку подписки.

    Создает счет в CryptoCloud и отправляет пользователю ссылку для оплаты.

    Args:
        callback (CallbackQuery): Колбэк от нажатия кнопки покупки подписки
    """
    if callback.from_user is None or callback.message is None:
        await callback.answer("⚠ Ошибка при обработке запроса")
        return

    await callback.answer()
    await callback.message.answer("🔄 Создаём платёжную ссылку...")

    invoice = await create_cryptocloud_invoice(callback.from_user.id, SUBSCRIPTION_PRICE_3)

    if "error" in invoice:
        await callback.message.answer(f"⚠ Ошибка при создании платежа: {invoice['error']}")
        return

    if not invoice.get("result"):
        await callback.message.answer("⚠ Не получилось создать платёж. Попробуйте позже.")
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💳 Перейти к оплате", 
            url=invoice["result"]["link"]
        ),
        InlineKeyboardButton(
            text="🔄 Проверить оплату", 
            callback_data=f"check_payment_{invoice['result']['uuid']}"
        )
    )

    await callback.message.answer(
        f"💸 Для оплаты подписки нажмите кнопку ниже:\n"
        f"Сумма: {SUBSCRIPTION_PRICE_3} USD\n"
        f"Счёт действителен в течение 24 часов",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: types.CallbackQuery):
    """
    Проверяет статус оплаты подписки.

    Args:
        callback (CallbackQuery): Колбэк от нажатия кнопки проверки оплаты
    """
    if callback.data is None or callback.message is None:
        await callback.answer("⚠ Ошибка при обработке запроса")
        return

    await callback.answer()
    invoice_id = callback.data.split('_')[2]
    status = await check_invoice_status(invoice_id)

    if callback.message is None:
        return

    if status == "paid":
        if callback.from_user is None:
            await callback.message.answer("⚠ Ошибка: пользователь не найден")
            return
        await update_subscription(callback.from_user.id)
        await callback.message.answer("✅ Подписка активирована! Теперь у вас полный доступ.")
    else:
        await callback.message.answer("⚠ Оплата не найдена. Если вы оплатили, попробуйте позже.")


@dp.message(F.text)
async def handle_message(message: Message):
    """
    Обрабатывает текстовые сообщения от пользователей.

    Проверяет доступ пользователя, отправляет запрос к Mistral AI и возвращает ответ.
    При исчерпании лимита запросов уведомляет пользователя.

    Args:
        message (Message): Входящее сообщение от пользователя
    """
    if message.from_user is None:
        await message.answer("⚠ Не удалось идентифицировать пользователя")
        return

    # Проверяем что message.text не None
    if message.text is None:
        await message.answer("⚠ Получено пустое сообщение")
        return

    if not await check_access(message.from_user.id):
        remaining = await get_remaining_requests(message.from_user.id)
        time_until_midnight = get_time_until_midnight()
        await message.answer(
            f"🚫 Лимит бесплатных запросов исчерпан (10 в день).\n"
            f"Оформите подписку для неограниченного доступа.\n"
            f"Новые запросы будут доступны через {time_until_midnight}."
        )
        return

    try:
        await bot.send_chat_action(message.chat.id, "typing")
        response = await get_mistral_response(message.text)
        await message.answer(response)

        # Обновляем информацию о оставшихся запросах
        remaining = await get_remaining_requests(message.from_user.id)
        if remaining <= 3:
            await message.answer(f"ℹ У вас осталось {remaining} бесплатных запросов сегодня.")
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠ Произошла ошибка при обработке запроса")


def get_time_until_midnight():
    """Возвращает строку с временем до полуночи."""
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = midnight - now
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    return f"{hours} ч. {minutes} мин."


async def scheduled_reset():
    """Ежедневный сброс счетчиков запросов."""
    while True:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_midnight - now).total_seconds())
        await reset_daily_limits()


async def main():
    """Основная функция для запуска бота.

    Инициализирует базу данных, удаляет вебхук (если был), запускает фоновую задачу
    для ежедневного сброса счетчиков запросов и начинает поллинг обновлений.
    """
    await init_db()
    await bot(DeleteWebhook(drop_pending_updates=True))

    # Запускаем фоновую задачу для сброса счетчиков
    asyncio.create_task(scheduled_reset())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
