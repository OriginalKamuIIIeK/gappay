import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import sqlite3
import os
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ваши данные (замените на свои)
BOT_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"  # Замените!
ADMIN_IDS = [123456789]  # Замените на свой Telegram ID
GROUP_CHAT_ID = -1001234567890  # ID группы куда добавлять (пока оставьте)

# Создаем папку для скриншотов
os.makedirs("screenshots", exist_ok=True)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния для FSM
class PaymentState(StatesGroup):
    waiting_screenshot = State()
    waiting_ticket_selection = State()

# База данных SQLite
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id INTEGER UNIQUE,
                  username TEXT,
                  full_name TEXT,
                  balance REAL DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Таблица билетов
    c.execute('''CREATE TABLE IF NOT EXISTS tickets
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  price REAL,
                  description TEXT,
                  payment_details TEXT,
                  is_active BOOLEAN DEFAULT 1)''')
    
    # Таблица транзакций
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  ticket_id INTEGER,
                  amount REAL,
                  status TEXT DEFAULT 'pending',  # pending, approved, rejected
                  screenshot_path TEXT,
                  admin_id INTEGER,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(id),
                  FOREIGN KEY(ticket_id) REFERENCES tickets(id))''')
    
    conn.commit()
    conn.close()
    
    # Добавляем билеты если их нет
    add_default_tickets()

def add_default_tickets():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Проверяем есть ли уже билеты
    c.execute("SELECT COUNT(*) FROM tickets")
    if c.fetchone()[0] == 0:
        # Добавляем 4 билета
        tickets = [
            ("Билет Стартовый", 500, "Участие в 1 игре", "Карта Сбербанк: 2202 2022 2022 2022\nПолучатель: Иван Иванов"),
            ("Билет Стандарт", 1000, "Участие в 2 играх", "Карта Тинькофф: 5536 9137 1234 5678\nПолучатель: Петр Петров"),
            ("Билет Премиум", 2000, "Участие в 5 играх + бонусы", "ЮMoney: 4100 1234 5678 9012\nПолучатель: Сергей Сергеев"),
            ("Билет VIP", 5000, "Неограниченно игр на месяц", "СБП: +7 (999) 123-45-67\nБанк: Тинькофф\nПолучатель: Александр Александров")
        ]
        
        for ticket in tickets:
            c.execute("INSERT INTO tickets (name, price, description, payment_details) VALUES (?, ?, ?, ?)", ticket)
    
    conn.commit()
    conn.close()

# Получить пользователя
def get_user(telegram_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = c.fetchone()
    conn.close()
    return user

# Добавить пользователя
def add_user(telegram_id, username, full_name):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO users (telegram_id, username, full_name) VALUES (?, ?, ?)",
                  (telegram_id, username, full_name))
        conn.commit()
    finally:
        conn.close()

# Обработчик команды /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.first_name
    
    if message.from_user.last_name:
        full_name += " " + message.from_user.last_name
    
    # Добавляем пользователя в БД
    add_user(user_id, username, full_name)
    
    # Приветственное сообщение
    await message.answer(
        "🎮 Добро пожаловать в GapPlay Tickets Bot!\n\n"
        "Здесь вы можете купить билеты на участие в играх.\n\n"
        "Доступные команды:\n"
        "/tickets - Посмотреть билеты и купить\n"
        "/my_tickets - Мои купленные билеты\n"
        "/support - Связь с поддержкой\n\n"
        "Администраторы: @username1, @username2"
    )

# Обработчик команды /tickets
@dp.message(Command("tickets"))
async def cmd_tickets(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE is_active = 1")
    tickets = c.fetchall()
    conn.close()
    
    if not tickets:
        await message.answer("Билеты временно недоступны")
        return
    
    # Создаем клавиатуру с билетами
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for ticket in tickets:
        ticket_id, name, price, description, payment_details, is_active = ticket
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{name} - {price}₽",
                callback_data=f"buy_ticket_{ticket_id}"
            )
        ])
    
    await message.answer(
        "🎫 Выберите билет для покупки:",
        reply_markup=keyboard
    )
    
    await state.set_state(PaymentState.waiting_ticket_selection)

# Обработчик выбора билета
@dp.callback_query(F.data.startswith("buy_ticket_"))
async def process_ticket_selection(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[2])
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    ticket = c.fetchone()
    conn.close()
    
    if not ticket:
        await callback.answer("Билет не найден")
        return
    
    ticket_id, name, price, description, payment_details, is_active = ticket
    
    # Сохраняем данные в состоянии
    await state.update_data(ticket_id=ticket_id, ticket_price=price)
    
    # Отправляем реквизиты
    await callback.message.answer(
        f"💳 **Реквизиты для оплаты:**\n\n"
        f"🎫 Билет: {name}\n"
        f"💰 Сумма: {price}₽\n\n"
        f"📋 Оплатите на:\n{payment_details}\n\n"
        f"⚠️ **ВАЖНО:**\n"
        f"1. Оплатите ТОЧНУЮ сумму\n"
        f"2. Сохраните чек/скриншот\n"
        f"3. После оплаты нажмите кнопку ниже",
        parse_mode="Markdown"
    )
    
    # Кнопка "Я оплатил"
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Я оплатил")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await callback.message.answer(
        "Нажмите кнопку ниже после оплаты:",
        reply_markup=keyboard
    )
    
    await state.set_state(PaymentState.waiting_screenshot)
    await callback.answer()

# Обработчик кнопки "Я оплатил"
@dp.message(PaymentState.waiting_screenshot, F.text == "✅ Я оплатил")
async def process_payment_confirmation(message: types.Message, state: FSMContext):
    await message.answer(
        "📎 Теперь отправьте скриншот чека об оплате.\n"
        "Формат: JPG или PNG\n"
        "Важно: чтобы были видны реквизиты и сумма",
        reply_markup=types.ReplyKeyboardRemove()
    )

# Обработчик получения скриншота
@dp.message(PaymentState.waiting_screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    ticket_id = user_data.get('ticket_id')
    ticket_price = user_data.get('ticket_price')
    
    # Скачиваем фото
    photo = message.photo[-1]
    file_id = photo.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    
    # Сохраняем скриншот
    timestamp = int(datetime.now().timestamp())
    screenshot_filename = f"screenshots/{message.from_user.id}_{timestamp}.jpg"
    await bot.download_file(file_path, screenshot_filename)
    
    # Добавляем транзакцию в БД
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Получаем user_id из БД
    c.execute("SELECT id FROM users WHERE telegram_id = ?", (message.from_user.id,))
    user_db = c.fetchone()
    
    if user_db:
        user_db_id = user_db[0]
        
        # Создаем транзакцию
        c.execute("""
            INSERT INTO transactions (user_id, ticket_id, amount, screenshot_path, status)
            VALUES (?, ?, ?, ?, ?)
        """, (user_db_id, ticket_id, ticket_price, screenshot_filename, 'pending'))
        
        transaction_id = c.lastrowid
        conn.commit()
        
        # Уведомляем администраторов
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🔄 Новая оплата на проверку!\n"
                    f"ID: {transaction_id}\n"
                    f"Пользователь: @{message.from_user.username}\n"
                    f"Билет: {ticket_id}\n"
                    f"Сумма: {ticket_price}₽"
                )
                
                # Отправляем скриншот админу
                with open(screenshot_filename, 'rb') as photo_file:
                    await bot.send_photo(
                        admin_id,
                        photo_file,
                        caption=f"Скриншот чека #{transaction_id}\n"
                                f"Для подтверждения: /confirm_{transaction_id}\n"
                                f"Для отказа: /reject_{transaction_id}"
                    )
            except Exception as e:
                logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
    
    conn.close()
    
    await message.answer(
        "✅ Скриншот получен!\n"
        "Ожидайте проверки администратора.\n"
        "Обычно проверка занимает 5-15 минут.\n\n"
        "Как только оплата будет подтверждена, вы получите уведомление."
    )
    
    await state.clear()

# АДМИН КОМАНДЫ

# Показать все транзакции
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет прав администратора")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute("""
        SELECT t.id, u.telegram_id, u.username, tk.name, t.amount, t.status, t.created_at
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN tickets tk ON t.ticket_id = tk.id
        ORDER BY t.created_at DESC
        LIMIT 10
    """)
    
    transactions = c.fetchall()
    conn.close()
    
    if not transactions:
        await message.answer("Нет транзакций")
        return
    
    text = "📊 Последние транзакции:\n\n"
    for trans in transactions:
        trans_id, tg_id, username, ticket_name, amount, status, created_at = trans
        text += f"#{trans_id} | {ticket_name} | {amount}₽\n"
        text += f"👤 @{username} | Статус: {status}\n"
        text += f"Время: {created_at}\n"
        text += f"Подтвердить: /confirm_{trans_id}\n"
        text += f"Отклонить: /reject_{trans_id}\n"
        text += "─" * 30 + "\n"
    
    await message.answer(text)

# Подтвердить платеж
@dp.message(F.text.startswith("/confirm_"))
async def confirm_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        transaction_id = int(message.text.split("_")[1])
    except:
        await message.answer("Неверный формат команды")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Обновляем статус транзакции
    c.execute("""
        UPDATE transactions 
        SET status = 'approved', admin_id = ?
        WHERE id = ?
    """, (message.from_user.id, transaction_id))
    
    # Получаем данные транзакции
    c.execute("""
        SELECT u.telegram_id, t.ticket_id, tk.name
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN tickets tk ON t.ticket_id = tk.id
        WHERE t.id = ?
    """, (transaction_id,))
    
    transaction = c.fetchone()
    conn.commit()
    conn.close()
    
    if transaction:
        user_telegram_id, ticket_id, ticket_name = transaction
        
        # Уведомляем пользователя
        await bot.send_message(
            user_telegram_id,
            f"✅ Ваш платеж подтвержден!\n\n"
            f"🎫 Билет: {ticket_name}\n"
            f"💰 Сумма: подтверждена\n"
            f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Спасибо за покупку! Доступ выдан."
        )
        
        # ЗДЕСЬ БУДЕТ ДОБАВЛЕНИЕ В ГРУППУ
        # await add_user_to_group(user_telegram_id)
        
        await message.answer(f"✅ Платеж #{transaction_id} подтвержден")
    else:
        await message.answer("Транзакция не найдена")

# Отклонить платеж
@dp.message(F.text.startswith("/reject_"))
async def reject_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        transaction_id = int(message.text.split("_")[1])
    except:
        await message.answer("Неверный формат команды")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute("""
        UPDATE transactions 
        SET status = 'rejected', admin_id = ?
        WHERE id = ?
    """, (message.from_user.id, transaction_id))
    
    c.execute("""
        SELECT u.telegram_id, t.ticket_id, tk.name
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN tickets tk ON t.ticket_id = tk.id
        WHERE t.id = ?
    """, (transaction_id,))
    
    transaction = c.fetchone()
    conn.commit()
    conn.close()
    
    if transaction:
        user_telegram_id, ticket_id, ticket_name = transaction
        
        await bot.send_message(
            user_telegram_id,
            f"❌ Ваш платеж отклонен!\n\n"
            f"Причина: скриншот нечеткий/неполный/сумма не совпадает\n\n"
            f"Пожалуйста, оплатите снова и отправьте четкий скриншот."
        )
        
        await message.answer(f"❌ Платеж #{transaction_id} отклонен")
    else:
        await message.answer("Транзакция не найдена")

# Запуск бота
async def main():
    # Инициализируем БД
    init_db()
    
    print("Бот запускается...")
    print("Администраторы:", ADMIN_IDS)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())