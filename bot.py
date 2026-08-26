import os
import telebot

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "🤖 ربات فعاله!")

@bot.message_handler(commands=["status"])
def status(message):
    bot.reply_to(message, "🟢 ربات آنلاین است.")

print("🤖 Bot is running...")

bot.infinity_polling()
