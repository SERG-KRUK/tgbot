# 🤖 Telegram Bot with Mistral AI and CryptoCloud Payments

Этот бот предоставляет доступ к модели Mistral AI с возможностью бесплатного использования (с ограничениями) и платной подписки для неограниченных запросов. Платежи обрабатываются через CryptoCloud.

## 🚀 Основные функции

- 💬 Бесплатные запросы к Mistral AI (до 10 в день)
- 💳 Платная подписка через CryptoCloud (3 USD/месяц)
- 🔄 Автоматическая проверка оплаты
- 📊 Учёт пользователей в SQLite базе данных
- ⏳ Ежедневный сброс счётчиков бесплатных запросов

## ⚙️ Установка и настройка

1. **Клонируйте репозиторий**
   ```bash
   git clone https://github.com/SERG-KRUK/TGBOTDEEPSEEK.git

2. **Установите зависимости**
bash
pip install -r requirements.txt

3. **Создайте файл .env и заполните его:**
TELEGRAM_TOKEN=ваш_токен_бота
MISTRAL_API_KEY=ваш_ключ_mistral
CRYPTOCLOUD_API_KEY=ваш_ключ_cryptocloud
CRYPTOCLOUD_SHOP_ID=ваш_shop_id

4. **Запустите бота**
python mistral_ai.py


🔧 Требования
Python 3.9+

Библиотеки из requirements.txt

Аккаунты в:

Mistral AI (для API ключа)

CryptoCloud (для платежей)


📌 Команды бота
/start - Начало работы, показывает остаток бесплатных запросов

Кнопка "💳 Купить подписку" - Покупка подписки за 3 USD


🛠 Технические детали
База данных: SQLite (users.db)

Платежи: CryptoCloud API v2

AI модель: Mistral Medium (по умолчанию)


📄 Лицензия
MIT License


⚠️ Важно: Перед запуском убедитесь, что все переменные окружения корректно заданы в .env файле!

text

Этот README.md содержит:
1. Краткое описание бота
2. Инструкции по установке
3. Требования к окружению
4. Основные команды
5. Технические детали реализации
6. Информацию о лицензии
