import asyncio
import logging
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
# Замените эти значения на свои!
BOT_TOKEN = "8513635055:AAFdJiqUUQ0W0vLhy1vMuJKqdqLSrmtouPc"  # ⚠️ ЗАМЕНИТЕ ЭТО
ADMIN_IDS = [7656583864]  # ⚠️ Ваш Telegram ID (узнать через @userinfobot)
GROUP_CHAT_ID = -1001234567890  # ID группы (если есть)

# Создаем папки
os.makedirs("screenshots", exist_ok=True)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# === СОСТОЯНИЯ ===
class PaymentState(StatesGroup):
    waiting_screenshot = State()
    ticket_selected = State()

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id INTEGER UNIQUE,
                  username TEXT,
                  full_name TEXT,
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
                  status TEXT DEFAULT 'pending',
                  screenshot_path TEXT,
                  admin_id INTEGER,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    
    # Добавляем тестовые билеты
    c.execute("SELECT COUNT(*) FROM tickets")
    if c.fetchone()[0] == 0:
        tickets = [
            ("🎫 Базовый", 500, "Доступ к 1 игре", "Карта Сбербанк: 2202 **** **** 1234\nИван Иванов"),
            ("🎫 Стандарт", 1000, "Доступ к 3 играм", "Карта Тинькофф: 5536 **** **** 5678\nПетр Петров"),
            ("🎫 Премиум", 2000, "Доступ к 10 играм", "ЮMoney: 4100 **** **** 9012\nСергей Сергеев"),
            ("🎫 VIP", 5000, "Неограниченный доступ", "СБП: +79991234567\nТинькофф Банк")
        ]
        
        for ticket in tickets:
            c.execute(
                "INSERT INTO tickets (name, price, description, payment_details) VALUES (?, ?, ?, ?)",
                ticket
            )
    
    conn.commit()
    conn.close()

def add_user(telegram_id, username, full_name):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    try:
        c.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, full_name) VALUES (?, ?, ?)",
            (telegram_id, username, full_name)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя: {e}")
    finally:
        conn.close()

# === КОМАНДЫ ===
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    add_user(user.id, user.username, f"{user.first_name} {user.last_name or ''}")
    
    await message.answer(
        "🎮 *Добро пожаловать в GapPlay Bot!*\n\n"
        "✨ *Возможности:*\n"
        "• Покупка билетов для участия в играх\n"
        "• Быстрая проверка оплаты\n"
        "• Автоматическое подтверждение\n\n"
        "📋 *Команды:*\n"
        "/tickets - Посмотреть билеты\n"
        "/my_tickets - Мои покупки\n"
        "/support - Поддержка\n\n"
        "⚡️ Выбирайте билет и присоединяйтесь к игре!",
        parse_mode="Markdown"
    )

@dp.message(Command("tickets"))
async def cmd_tickets(message: types.Message):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE is_active = 1")
    tickets = c.fetchall()
    conn.close()
    
    if not tickets:
        await message.answer("Билеты временно недоступны")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for ticket in tickets:
        ticket_id, name, price, description, payment_details, is_active = ticket
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{name} - {price}₽",
                callback_data=f"ticket_{ticket_id}"
            )
        ])
    
    await message.answer(
        "🎟️ *Выберите билет:*\n\n"
        "1. 🎫 Базовый - 500₽ (1 игра)\n"
        "2. 🎫 Стандарт - 1000₽ (3 игры)\n"
        "3. 🎫 Премиум - 2000₽ (10 игр)\n"
        "4. 🎫 VIP - 5000₽ (безлимит)\n\n"
        "Нажмите на кнопку с нужным билетом:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("ticket_"))
async def process_ticket_selection(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    ticket = c.fetchone()
    conn.close()
    
    if not ticket:
        await callback.answer("Билет не найден")
        return
    
    ticket_id, name, price, description, payment_details, is_active = ticket
    
    await state.update_data(
        ticket_id=ticket_id,
        ticket_name=name,
        ticket_price=price,
        payment_details=payment_details
    )
    
    await callback.message.answer(
        f"💳 *Реквизиты для оплаты:*\n\n"
        f"🎫 *Билет:* {name}\n"
        f"💰 *Сумма:* {price}₽\n"
        f"📝 *Описание:* {description}\n\n"
        f"*Платежные реквизиты:*\n"
        f"```\n{payment_details}\n```\n\n"
        f"*Инструкция:*\n"
        f"1. Переведите {price}₽ на указанные реквизиты\n"
        f"2. Сделайте скриншот чека\n"
        f"3. Нажмите кнопку '✅ Я оплатил'\n"
        f"4. Отправьте скриншот чека",
        parse_mode="Markdown"
    )
    
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

@dp.message(PaymentState.waiting_screenshot, F.text == "✅ Я оплатил")
async def process_payment_button(message: types.Message, state: FSMContext):
    await message.answer(
        "📎 Отправьте скриншот чека об оплате.\n\n"
        "❗ *Важно:*\n"
        "• Фото должно быть четким\n"
        "• Должны быть видны сумма и реквизиты\n"
        "• Формат: JPG или PNG",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )

@dp.message(PaymentState.waiting_screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    
    # Скачиваем фото
    photo = message.photo[-1]
    file_id = photo.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    
    # Сохраняем скриншот
    timestamp = int(datetime.now().timestamp())
    screenshot_filename = f"screenshots/{message.from_user.id}_{timestamp}.jpg"
    await bot.download_file(file_path, screenshot_filename)
    
    # Сохраняем в базу данных
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    try:
        # Получаем user_id из БД
        c.execute("SELECT id FROM users WHERE telegram_id = ?", (message.from_user.id,))
        user_db = c.fetchone()
        
        if user_db:
            user_db_id = user_db[0]
            
            # Создаем транзакцию
            c.execute("""
                INSERT INTO transactions (user_id, ticket_id, amount, screenshot_path, status)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_db_id,
                user_data['ticket_id'],
                user_data['ticket_price'],
                screenshot_filename,
                'pending'
            ))
            
            transaction_id = c.lastrowid
            conn.commit()
            
            # Уведомляем администраторов
            admin_message = (
                f"🔄 *Новая оплата на проверку!*\n\n"
                f"📊 *Детали:*\n"
                f"• ID: #{transaction_id}\n"
                f"• Пользователь: @{message.from_user.username or 'Нет username'}\n"
                f"• Имя: {message.from_user.first_name}\n"
                f"• Билет: {user_data['ticket_name']}\n"
                f"• Сумма: {user_data['ticket_price']}₽\n\n"
                f"✅ *Подтвердить:* /confirm_{transaction_id}\n"
                f"❌ *Отклонить:* /reject_{transaction_id}"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    # Отправляем сообщение админу
                    await bot.send_message(
                        admin_id,
                        admin_message,
                        parse_mode="Markdown"
                    )
                    
                    # Отправляем скриншот
                    with open(screenshot_filename, 'rb') as photo_file:
                        await bot.send_photo(
                            admin_id,
                            photo_file,
                            caption=f"Скриншот чека #{transaction_id}"
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка сохранения транзакции: {e}")
    finally:
        conn.close()
    
    await message.answer(
        "✅ *Скриншот получен!*\n\n"
        "⏳ Ожидайте проверки администратора.\n"
        "Обычно проверка занимает 5-15 минут.\n\n"
        "📬 Вы получите уведомление как только оплата будет подтверждена.",
        parse_mode="Markdown"
    )
    
    await state.clear()

# === АДМИН КОМАНДЫ ===
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 У вас нет прав администратора")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute("""
        SELECT t.id, u.telegram_id, u.username, tk.name, t.amount, t.status, t.created_at
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN tickets tk ON t.ticket_id = tk.id
        WHERE t.status = 'pending'
        ORDER BY t.created_at DESC
    """)
    
    pending_transactions = c.fetchall()
    conn.close()
    
    if not pending_transactions:
        await message.answer("✅ Нет транзакций на проверку")
        return
    
    text = "📋 *Транзакции на проверку:*\n\n"
    for trans in pending_transactions:
        trans_id, tg_id, username, ticket_name, amount, status, created_at = trans
        text += f"*#{trans_id}* | {ticket_name} | *{amount}₽*\n"
        text += f"👤 @{username or 'нет username'} (ID: {tg_id})\n"
        text += f"⏰ {created_at}\n"
        text += f"✅ /confirm_{trans_id}  |  ❌ /reject_{trans_id}\n"
        text += "─" * 30 + "\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text.regexp(r'^/confirm_\d+$'))
async def confirm_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        transaction_id = int(message.text.split("_")[1])
    except:
        await message.answer("❌ Неверный формат команды")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    try:
        # Обновляем статус транзакции
        c.execute("""
            UPDATE transactions 
            SET status = 'approved', admin_id = ?
            WHERE id = ?
        """, (message.from_user.id, transaction_id))
        
        # Получаем данные для уведомления пользователя
        c.execute("""
            SELECT u.telegram_id, tk.name, t.amount
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            JOIN tickets tk ON t.ticket_id = tk.id
            WHERE t.id = ?
        """, (transaction_id,))
        
        result = c.fetchone()
        conn.commit()
        
        if result:
            user_telegram_id, ticket_name, amount = result
            
            # Уведомляем пользователя
            success_message = (
                f"🎉 *Оплата подтверждена!*\n\n"
                f"✅ Ваш билет активирован\n"
                f"🎫 *Билет:* {ticket_name}\n"
                f"💰 *Сумма:* {amount}₽\n"
                f"📅 *Дата:* {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"✨ Спасибо за покупку! Приятной игры!"
            )
            
            await bot.send_message(
                user_telegram_id,
                success_message,
                parse_mode="Markdown"
            )
            
            await message.answer(f"✅ Платеж #{transaction_id} подтвержден")
            
            # Здесь можно добавить пользователя в группу
            # if GROUP_CHAT_ID:
            #     try:
            #         await bot.approve_chat_join_request(
            #             chat_id=GROUP_CHAT_ID,
            #             user_id=user_telegram_id
            #         )
            #     except Exception as e:
            #         logger.error(f"Ошибка добавления в группу: {e}")
                    
        else:
            await message.answer("❌ Транзакция не найдена")
    except Exception as e:
        logger.error(f"Ошибка подтверждения платежа: {e}")
        await message.answer("❌ Ошибка подтверждения платежа")
    finally:
        conn.close()

@dp.message(F.text.regexp(r'^/reject_\d+$'))
async def reject_payment(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        transaction_id = int(message.text.split("_")[1])
    except:
        await message.answer("❌ Неверный формат команды")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    try:
        c.execute("""
            UPDATE transactions 
            SET status = 'rejected', admin_id = ?
            WHERE id = ?
        """, (message.from_user.id, transaction_id))
        
        c.execute("""
            SELECT u.telegram_id, tk.name, t.amount
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            JOIN tickets tk ON t.ticket_id = tk.id
            WHERE t.id = ?
        """, (transaction_id,))
        
        result = c.fetchone()
        conn.commit()
        
        if result:
            user_telegram_id, ticket_name, amount = result
            
            reject_message = (
                f"❌ *Оплата отклонена*\n\n"
                f"Платеж по билету '{ticket_name}' на сумму {amount}₽ отклонен.\n\n"
                f"*Возможные причины:*\n"
                f"• Нечеткий скриншот\n"
                f"• Неверная сумма\n"
                f"• Неполные данные\n\n"
                f"🔄 Пожалуйста, оплатите снова и отправьте четкий скриншот чека."
            )
            
            await bot.send_message(user_telegram_id, reject_message, parse_mode="Markdown")
            await message.answer(f"❌ Платеж #{transaction_id} отклонен")
        else:
            await message.answer("❌ Транзакция не найдена")
    except Exception as e:
        logger.error(f"Ошибка отклонения платежа: {e}")
        await message.answer("❌ Ошибка отклонения платежа")
    finally:
        conn.close()

@dp.message(Command("support"))
async def cmd_support(message: types.Message):
    support_text = (
        "📞 *Поддержка*\n\n"
        "Если у вас возникли проблемы:\n\n"
        "1. *Проблемы с оплатой* - проверьте реквизиты и сумму\n"
        "2. *Не приходит подтверждение* - ожидайте 15 минут\n"
        "3. *Другое* - напишите администраторам\n\n"
        "👥 *Администраторы:*\n"
    )
    
    for admin_id in ADMIN_IDS:
        support_text += f"• [Администратор](tg://user?id={admin_id})\n"
    
    await message.answer(support_text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("my_tickets"))
async def cmd_my_tickets(message: types.Message):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    c.execute("""
        SELECT id FROM users WHERE telegram_id = ?
    """, (message.from_user.id,))
    user_db = c.fetchone()
    
    if not user_db:
        await message.answer("Вы еще не покупали билеты")
        return
    
    user_db_id = user_db[0]
    
    c.execute("""
        SELECT t.id, tk.name, t.amount, t.status, t.created_at
        FROM transactions t
        JOIN tickets tk ON t.ticket_id = tk.id
        WHERE t.user_id = ?
        ORDER BY t.created_at DESC
    """, (user_db_id,))
    
    transactions = c.fetchall()
    conn.close()
    
    if not transactions:
        await message.answer("🎫 У вас пока нет купленных билетов")
        return
    
    text = "📋 *История ваших покупок:*\n\n"
    for trans in transactions:
        trans_id, ticket_name, amount, status, created_at = trans
        
        status_emoji = "✅" if status == 'approved' else "🔄" if status == 'pending' else "❌"
        text += f"{status_emoji} *Билет:* {ticket_name}\n"
        text += f"💰 *Сумма:* {amount}₽\n"
        text += f"📅 *Дата:* {created_at}\n"
        text += f"📊 *Статус:* {status}\n"
        text += "─" * 20 + "\n"
    
    await message.answer(text, parse_mode="Markdown")

# === ЗАПУСК БОТА ===
async def main():
    # Инициализируем базу данных
    init_db()
    
    logger.info("Бот запускается...")
    logger.info(f"Администраторы: {ADMIN_IDS}")
    
    # Удаляем вебхук и запускаем поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
