import os
import time
import requests
import telebot

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "🦈 Meme Hunter فعال شد!\n\n"
        "🔎 آماده بررسی میم‌کوین‌های سولانا هستم.\n"
        "برای شروع /scan را بفرست."
    )

@bot.message_handler(commands=["scan"])
def scan(message):
    bot.reply_to(
        message,
        "🔎 در حال اسکن بازار سولانا...\n"
        "⏳ نسخه فعلی فقط تحلیل و شناسایی انجام می‌دهد."
    )

@bot.message_handler(commands=["status"])
def status(message):
    bot.reply_to(message, "🟢 Meme Hunter آنلاین است.")

print("🦈 Meme Hunter is running...")

bot.infinity_polling()
