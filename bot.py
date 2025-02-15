import json
import os
import time
import requests
import schedule
from datetime import datetime, timedelta
from dotenv import load_dotenv
from groq import Groq
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)

# File to store user data
DATA_FILE = "db.json"
SUBMISSION_FOLDER = "submissions"
os.makedirs(SUBMISSION_FOLDER, exist_ok=True)

# Conversation states
NAME, AGE, GRADE, TIME = range(4)

# Load or create user database
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_users():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=4)

# Start command - asks for name
async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Hello! Let's get you registered. What's your name?")
    return NAME

async def get_name(update: Update, context: CallbackContext) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Great! How old are you?")
    return AGE

async def get_age(update: Update, context: CallbackContext) -> int:
    context.user_data["age"] = update.message.text
    await update.message.reply_text("What is your class grade? (e.g., 10th, 12th)")
    return GRADE

async def get_grade(update: Update, context: CallbackContext) -> int:
    context.user_data["grade"] = update.message.text
    await update.message.reply_text("At what time would you like to receive your daily Python question? (HH:MM, 24-hour format)")
    return TIME

async def get_time(update: Update, context: CallbackContext) -> int:
    user_id = str(update.message.chat_id)
    preferred_time = update.message.text
    
    users = load_users()
    users[user_id] = {
        "name": context.user_data["name"],
        "age": context.user_data["age"],
        "grade": context.user_data["grade"],
        "time": preferred_time,
        "streak": 0,
        "last_submission": None
    }
    save_users(users)
    
    await update.message.reply_text(f"You're registered, {context.user_data['name']}! \U0001F389\nYou'll get questions daily at {preferred_time}.")
    
    question = generate_question(context.user_data["grade"])
    await update.message.reply_text(f"\U0001F4D1 Here's your first Python practice question:\n\n{question}\n\nYou can submit your solution as a .txt or .py file within 9 hours.")
    return ConversationHandler.END

# Function to fetch Python question
def generate_question(grade):
    prompt = f"Generate a unique Python coding question suitable for a {grade}-grade student."
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile",
    )
    return chat_completion.choices[0].message.content if chat_completion.choices else "Error fetching question"

# Function to handle file submissions
async def handle_submission(update: Update, context: CallbackContext):
    user_id = str(update.message.chat_id)
    users = load_users()
    if user_id not in users:
        await update.message.reply_text("You're not registered! Use /start to register.")
        return
    
    if not update.message.document:
        await update.message.reply_text("Please upload a .txt or .py file.")
        return
    
    file = update.message.document
    if file.mime_type not in ["text/plain", "text/x-python"]:
        await update.message.reply_text("Only .txt or .py files are allowed!")
        return
    
    filename = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.file_name}"
    file_path = os.path.join(SUBMISSION_FOLDER, filename)
    new_file = await file.get_file()
    await new_file.download_to_drive(file_path)
    
    users[user_id]["last_submission"] = datetime.now().isoformat()
    users[user_id]["streak"] += 1
    save_users(users)
    
    await update.message.reply_text("Submission received! ✅")

# Function to check submission deadlines
def check_missed_submissions():
    users = load_users()
    now = datetime.now()
    for user_id, info in users.items():
        if info.get("last_submission"):
            last_submission_time = datetime.fromisoformat(info["last_submission"])
            if now - last_submission_time > timedelta(hours=9):
                users[user_id]["streak"] = 0
                users[user_id]["last_submission"] = None
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                payload = {"chat_id": user_id, "text": "⏳ Time's up! You lost your streak. Keep trying!"}
                requests.post(url, json=payload)
    save_users(users)

# Function to check streak
async def check_streak(update: Update, context: CallbackContext):
    user_id = str(update.message.chat_id)
    users = load_users()
    streak = users.get(user_id, {}).get("streak", 0)
    await update.message.reply_text(f"🔥 Your current streak: {streak} days")

# Schedule tasks
schedule.every().minute.do(check_missed_submissions)

# Main function
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
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
    app.add_handler(MessageHandler(filters.Document.ALL, handle_submission))
    app.add_handler(CommandHandler("streak", check_streak))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
