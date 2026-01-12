import os
import logging
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, PreCheckoutQueryHandler, CallbackContext
from dotenv import load_dotenv
import openai
import requests  # Не нужен, если используете только OpenAI

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID'))  # Ваш Telegram ID
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
STRIPE_TOKEN = os.getenv('STRIPE_TOKEN')  # Для Telegram Payments

openai.api_key = OPENAI_API_KEY

# Простое хранилище (в production используйте БД)
users = {}  # user_id: {'subscribed': True/False, 'session_start': datetime, 'pending_message': str, 'timer': time}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    await update.message.reply_text(f"Привет! Я бот-психолог. Оплатите подписку /subscribe. Ваш ID: {user_id} (для владельца).")

async def subscribe(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    keyboard = [[InlineKeyboardButton("Оплатить 10€", callback_data='pay')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Оплатите 10€ за 30-минутную консультацию.", reply_markup=reply_markup)

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    if query.data == 'pay':
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title="Консультация психолога",
            description="30 минут консультации 24/7",
            payload="consultation",
            provider_token=STRIPE_TOKEN,
            currency="EUR",
            prices=[{"label": "Консультация", "amount": 1000}]  # 10.00 EUR
        )

async def precheckout(update: Update, context: CallbackContext):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id] = {'subscribed': True, 'session_start': datetime.now(), 'pending_message': None, 'timer': None}
    await update.message.reply_text("Оплата прошла! Начните консультацию /consult.")

async def consult(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id not in users or not users[user_id]['subscribed']:
        await update.message.reply_text("Сначала оплатите /subscribe.")
        return
    await update.message.reply_text("Напишите ваш вопрос. Я перешлю психологу.")

async def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id not in users or not users[user_id]['subscribed']:
        return
    # Проверяем время сессии
    session_start = users[user_id]['session_start']
    if datetime.now() > session_start + timedelta(minutes=30):
        users[user_id]['subscribed'] = False
        await update.message.reply_text("Сессия закончилась. Оплатите заново /subscribe.")
        return
    # Пересылаем владельцу
    message = update.message.text
    await context.bot.send_message(OWNER_ID, f"Запрос от {user_id}: {message}")
    # Устанавливаем таймер 5 мин
    users[user_id]['pending_message'] = message
    context.job_queue.run_once(ai_reply, 300, data={'user_id': user_id}, name=str(user_id))

async def ai_reply(context: CallbackContext):
    data = context.job.data
    user_id = data['user_id']
    if users[user_id]['pending_message'] is None:
        return  # Уже ответил владелец
    message = users[user_id]['pending_message']
    # Генерируем ответ ИИ
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": "Ты психолог. Отвечай empathetic и профессионально."},
                  {"role": "user", "content": message}]
    )
    ai_text = response.choices[0].message['content']
    await context.bot.send_message(user_id, ai_text)
    users[user_id]['pending_message'] = None

# Если владелец отвечает в пересланном чате, бот поймёт (но для простоты: отвечайте напрямую в чат с пользователем или настройте forwarding)
# Для полного: Добавьте handler для сообщений от OWNER_ID, но это усложнит. Пока предполагаем, что вы отвечаете в боте вручную.

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("consult", consult))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(PreCheckoutQueryHandler(precheckout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == '__main__':
    main()