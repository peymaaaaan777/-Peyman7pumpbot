import telebot
import os

TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "🤖 ربات میم‌کوین سولانا فعاله!\n\n"
        "🔎 حالت فعلی: Paper Trading\n"
        "💰 معامله واقعی: خاموش\n\n"
        "برای بررسی بازار /scan را بفرست."
    )

@bot.message_handler(commands=["scan"])
def scan(message):
    bot.reply_to(
        message,
        "🔎 در حال بررسی بازار سولانا...\n"
        "⏳ نسخه آزمایشی هنوز معامله واقعی انجام نمی‌دهد."
    )

@bot.message_handler(func=lambda message: True)
def echo(message):
    bot.reply_to(message, "پیامت دریافت شد ✅")

print("Bot is running...")
bot.infinity_polling()
