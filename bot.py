import json
import os
import time
import requests
import schedule
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)

# File to store user data
DATA_FILE = "db.json"

# Conversation states
NAME, AGE, GRADE, TIME = range(4)

# Load or create user database
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

# Function to read user data
def load_users():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

# Function to save user data
def save_users(users):
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=4)

# Start command - asks for name
async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Hello! Let's get you registered. What's your name?")
    return NAME

# Store name and ask for age
async def get_name(update: Update, context: CallbackContext) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Great! How old are you?")
    return AGE

# Store age and ask for class grade
async def get_age(update: Update, context: CallbackContext) -> int:
    context.user_data["age"] = update.message.text
    await update.message.reply_text("What is your class grade? (e.g., 10th, 12th)")
    return GRADE

# Store class grade and ask for preferred time
async def get_grade(update: Update, context: CallbackContext) -> int:
    context.user_data["grade"] = update.message.text
    await update.message.reply_text("At what time would you like to receive your daily Python question? (HH:MM, 24-hour format)")
    return TIME

# Store preferred time and complete registration
async def get_time(update: Update, context: CallbackContext) -> int:
    user_id = str(update.message.chat_id)
    preferred_time = update.message.text

    # Store user data
    users = load_users()
    users[user_id] = {
        "name": context.user_data["name"],
        "age": context.user_data["age"],
        "grade": context.user_data["grade"],
        "time": preferred_time
    }
    save_users(users)

    # Send confirmation message
    await update.message.reply_text(f"You're all set, {context.user_data['name']}! 🎉\n"
                                    f"You will receive a Python coding question daily at {preferred_time}.")
    
    # Generate and send the first question immediately
    question = generate_question(context.user_data["grade"])
    await update.message.reply_text(f"📌 Here's your first Python practice question:\n\n{question}")

    return ConversationHandler.END


# Function to fetch a Python question from Groq API
def generate_question(grade):
    prompt = f"Generate a unique Python coding question suitable for a {grade}-grade student."
    
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
    )

    return chat_completion.choices[0].message.content if chat_completion.choices else "Error fetching question"

# Function to send scheduled messages
def send_question():
    users = load_users()
    now = datetime.now().strftime("%H:%M")

    for user_id, info in users.items():
        if info["time"] == now:
            question = generate_question(info["grade"])
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": user_id, "text": f" Daily Python Practice Question:\n\n{question}"}
            requests.post(url, json=payload)

# Schedule messages to check every minute
schedule.every().minute.do(send_question)

# Main function
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            GRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_grade)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)

    print("Bot is running...")
    
    app.run_polling()

if __name__ == "__main__":
    main()
