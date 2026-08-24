import os
import telebot

TOKEN = os.environ["BOT_TOKEN"]
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "سلام داداش 🤖🔥\nربات با موفقیت فعاله!\n\nفعلاً حالت آزمایشی است."
    )

@bot.message_handler(func=lambda message: True)
def reply(message):
    bot.reply_to(message, "پیامت دریافت شد ✅")

bot.infinity_polling()
