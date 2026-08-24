import os
import telebot

TOKEN = os.environ["8906090956:AAFPRk1NIZWhtTMmKo_bfUgzsiYuFEd5L7M"]

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "سلام 👋 ربات روشنه 🚀")

@bot.message_handler(func=lambda message: True)
def reply(message):
    bot.reply_to(message, "پیامت رو گرفتم ✅")

print("Bot is running...")
bot.infinity_polling()
