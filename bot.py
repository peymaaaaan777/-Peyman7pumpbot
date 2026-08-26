import telebot
import os

TOKEN = os.getenv("BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "سلام 👋 ربات با موفقیت فعاله!")

@bot.message_handler(func=lambda message: True)
def echo(message):
    bot.reply_to(message, "پیامت دریافت شد ✅")

print("Bot is running...")
bot.infinity_polling()
