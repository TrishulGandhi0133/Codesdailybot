import json
import os
import time
import requests
import schedule
from datetime import datetime, timedelta
import asyncio
from dotenv import load_dotenv
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
import logging
from functools import partial
import threading
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)

# Constants
DATA_FILE = "db.json"
NAME, AGE, GRADE, DIFFICULTY, TIME, CHAT = range(6)
DIFFICULTY_LEVELS = ["Beginner", "Intermediate", "Advanced"]

class LLMGenerator:
    def __init__(self, client):
        self.client = client

    def get_completion(self, prompt):
        response = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        return response.choices[0].message.content

    def generate_question(self, user_id, grade, difficulty):
        prompt = f"""Generate a unique Python coding question for user {user_id} on {datetime.now().strftime('%Y-%m-%d')} based on :
                    Grade Level: {grade}
                    Difficulty: {difficulty}
                    
                    Include:
                    1. Brief problem statement (2-3 sentences)
                    2. Example input/output
                    3. Hint (hidden)
                    4. Test cases
                    5. Solution template
                    
                    Format as JSON:
                    {{
                        "question": "problem statement",
                        "example": "input/output example",
                        "hint": "helpful hint",
                        "test_cases": ["test1", "test2"],
                        "template": "code template"
                    }}

                    IMPORTANT: Return ONLY valid JSON. Do not include any additional text or explanations.
                    """
        response = self.get_completion(prompt)
        return response

    def generate_daily_tip(self):
        prompt = """Generate a short, interesting Python programming tip or fact.
                   Make it educational and engaging.
                   Include a small code example if relevant."""
        return self.get_completion(prompt)

    def generate_weekly_challenge(self):
        prompt = """Generate an engaging Python coding challenge:
                   1. Unique problem statement
                   2. Clear objectives
                   3. Scoring criteria
                   4. Example approach
                   Format as a complete challenge announcement."""
        return self.get_completion(prompt)

    def evaluate_submission(self, code, question, grade, difficulty):
        prompt = f"""Evaluate this Python code submission:
                    Question: {question}
                    Code: {code}
                    Grade: {grade}
                    Difficulty: {difficulty}
                    
                    Evaluate the code in a lenient way and provide feedback to the user.

                    Provide a correct JSON response in the following format:
                    {{
                        "score": 0-10,
                        "feedback": "positive feedback",
                        "improvements": "areas to improve",
                        "tip": "specific improvement tip",
                        "corrected_code": "improved version if needed"
                    }}

                    Example of a correct JSON response:
                    {{
                        "score": 8,
                        "feedback": "The submission is well-structured, readable, and follows good practices.",
                        "improvements": "Error handling could be improved.",
                        "tip": "Add input validation to handle edge cases.",
                        "corrected_code": "def example_function():\\n    pass"
                    }}

                    IMPORTANT: Return ONLY valid JSON. Do not include any additional text or explanations.
                    """
        response = self.get_completion(prompt)
        return response

    def generate_progress_insights(self, user_history):
        prompt = f"""Analyze this user's coding progress:
                    History: {json.dumps(user_history)}
                    
                    Provide JSON response:
                    {{
                        "strong_areas": ["area1", "area2"],
                        "improvement_areas": ["area1", "area2"],
                        "personalized_advice": "specific advice",
                        "next_steps": ["step1", "step2"]
                    }}"""
        return self.get_completion(prompt)

    def generate_hint(self, question, attempt_count):
        prompt = f"""Generate a helpful hint for this question:
                    Question: {question}
                    Previous Hints: {attempt_count}
                    
                    Provide a hint that:
                    1. Doesn't give away the solution
                    2. Gets more specific with each attempt
                    3. Guides rather than tells"""
        return self.get_completion(prompt)

    def chat_response(self, user_message, context):
        prompt = f"""Respond to this question:
                    User Message: {user_message}
                    Context: {context}
                    
                    talk it the user like a normal chatbot with precise answers to the user. elaborate only if they ask to."""
        return self.get_completion(prompt)

class UserDatabase:
    def __init__(self, filename=DATA_FILE):
        self.filename = filename
        self.ensure_file_exists()

    def ensure_file_exists(self):
        if not os.path.exists(self.filename):
            with open(self.filename, "w") as f:
                json.dump({}, f)

    def load(self):
        try:
            with open(self.filename, "r") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Error loading JSON from {self.filename}: {e}")
            return {}

    def save(self, data):
        with open(self.filename, "w") as f:
            json.dump(data, f, indent=4)

    def update_user(self, user_id, data):
        users = self.load()
        if user_id not in users:
            users[user_id] = {}
        users[user_id].update(data)
        self.save(users)

    def get_leaderboard(self):
        users = self.load()
        return sorted(
            users.items(),
            key=lambda x: (x[1].get('streak', 0), x[1].get('total_score', 0)),
            reverse=True
        )[:10]

class PythonLearningBot:
    def __init__(self):
        self.db = UserDatabase()
        self.llm = LLMGenerator(client)

    async def start(self, update: Update, context: CallbackContext) -> int:
        await update.message.reply_text("Hello! Let's get you registered. What's your name?")
        return NAME

    async def get_name(self, update: Update, context: CallbackContext) -> int:
        context.user_data["name"] = update.message.text
        await update.message.reply_text("Great! How old are you?")
        return AGE

    async def get_age(self, update: Update, context: CallbackContext) -> int:
        context.user_data["age"] = update.message.text
        await update.message.reply_text("What is your class grade? (e.g., 10th, 12th)")
        return GRADE

    async def get_grade(self, update: Update, context: CallbackContext) -> int:
        context.user_data["grade"] = update.message.text
        keyboard = [[InlineKeyboardButton(level, callback_data=level)] for level in DIFFICULTY_LEVELS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Choose your difficulty level:", reply_markup=reply_markup)
        return DIFFICULTY

    async def get_difficulty(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        context.user_data["difficulty"] = query.data
        await query.message.reply_text("At what time would you like to receive daily questions? (HH:MM, 24-hour format)")
        return TIME
    
    async def get_time(self, update: Update, context: CallbackContext) -> int:
        user_id = str(update.message.chat_id)
        preferred_time = update.message.text

        # Save user data
        user_data = {
            "name": context.user_data["name"],
            "age": context.user_data["age"],
            "grade": context.user_data["grade"],
            "difficulty": context.user_data["difficulty"],
            "preferred_time": preferred_time,
            "streak": 0,
            "total_score": 0,
            "last_submission": None,
            "submissions_history": []
        }

        self.db.update_user(user_id, user_data)

        # Generate first question
        question_json = self.llm.generate_question(user_id, user_data["grade"], user_data["difficulty"])
        
        # Log the raw LLM response
        logger.info(f"Raw LLM Response: {question_json}")

        try:
            question_data = json.loads(question_json)
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error: {e}")
            await update.message.reply_text("There was an issue generating your first question. Please try again later.")
            return ConversationHandler.END

        # Save the hint in the user's context
        context.user_data["hint"] = question_data["hint"]

        # Format the question neatly
        formatted_question = f"""
        🎉 You're all set, {user_data['name']}!

        ⏰ You'll get daily questions at: {preferred_time}
        📚 Grade Level: {user_data['grade']}
        💪 Difficulty: {user_data['difficulty']}

        Here's your first question:

        **Problem Statement:**
        {question_data['question']}

        **Example Input/Output:**
        {question_data['example']}

        **Test Cases:**
        {', '.join(question_data['test_cases'])}

        **Solution Template:**
        ```python
        {question_data['template']}
        ```
        """

        await update.message.reply_text(formatted_question)

        return ConversationHandler.END

    async def handle_hint(self, update: Update, context: CallbackContext):
        user_id = str(update.message.chat_id)
        hint = context.user_data.get("hint", "No hint available.")
        await update.message.reply_text(f"💡 Hint: {hint}")

    async def handle_chat(self, update: Update, context: CallbackContext) -> int:
        user_id = str(update.message.chat_id)
        message = update.message.text
        user_data = self.db.load().get(user_id, {})
        
        response = self.llm.chat_response(message, user_data)
        await update.message.reply_text(response)
        return CHAT

    async def start_chat(self, update: Update, context: CallbackContext) -> int:
        await update.message.reply_text("You can now chat with the AI. Type 'end_chat' to exit.")
        return CHAT

    async def end_chat(self, update: Update, context: CallbackContext) -> int:
        await update.message.reply_text("Chat ended. If you need further assistance, feel free to start a new chat.")
        return ConversationHandler.END

    async def handle_help(self, update: Update, context: CallbackContext):
        help_text = """
        🤖 Python Learning Bot Commands:
        /start - Register and begin learning
        /chat - Get help from AI assistant
        /hint - Get a hint for current question
        /explain - Get detailed explanation
        /streak - Check your streak
        /leaderboard - See top performers
        /progress - View your progress
        /settings - Change your preferences
        /help - Show this help message
        """
        await update.message.reply_text(help_text)

    async def handle_submission(self, update: Update, context: CallbackContext):
        user_id = str(update.message.chat_id)
        user_data = self.db.load().get(user_id, {})

        # Check if the message contains a document
        if not update.message.document:
            await update.message.reply_text("Please upload a .txt or .py file.")
            return

        file = update.message.document
        # Check if the file is a text or Python file
        if file.mime_type not in ["text/plain", "text/x-python"]:
            await update.message.reply_text("Only .txt or .py files are allowed!")
            return

        # Download and decode the file content
        new_file = await file.get_file()
        file_content = await new_file.download_as_bytearray()
        code = file_content.decode('utf-8')

        # Send the file to the admin chat ID
        await self.send_document(ADMIN_CHAT_ID, new_file.file_id)

        # Get evaluation from LLM
        evaluation = self.llm.evaluate_submission(
            code,
            user_data.get('current_question', ''),
            user_data.get('grade', ''),
            user_data.get('difficulty', '')
        )

        # Log the raw LLM response
        logger.info(f"Raw LLM Evaluation Response: {evaluation}")

        try:
            # Clean up the response by removing potential markdown formatting
            cleaned_evaluation = evaluation.replace('```json\n', '').replace('```', '')
            eval_data = json.loads(cleaned_evaluation)

            # Update user stats
            user_data['streak'] = user_data.get('streak', 0) + 1
            user_data['total_score'] = user_data.get('total_score', 0) + eval_data['score']
            user_data['submissions_history'] = user_data.get('submissions_history', [])
            user_data['submissions_history'].append({
                'date': datetime.now().isoformat(),
                'score': eval_data['score'],
                'feedback': eval_data['feedback']
            })

            # Save updated user data
            self.db.update_user(user_id, user_data)

            # Notify user of streak milestone
            if user_data['streak'] % 5 == 0:
                await update.message.reply_text(f"🎉 Congratulations! You've reached a {user_data['streak']} day streak!")

            # Send feedback to user
            feedback_message = f"""
            📝 Submission Evaluation:

            Score: {eval_data['score']}/10

            🌟 Positive Feedback:
            {eval_data['feedback']}

            💡 Areas for Improvement:
            {eval_data['improvements']}

            📌 Specific Tip:
            {eval_data['tip']}

            💻 Improved Code:
            ```python
            {eval_data['corrected_code']}
            ```
            """

            await update.message.reply_text(feedback_message)

        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error: {e}")
            logger.error(f"Failed JSON content: {evaluation}")
            # Provide a fallback evaluation
            fallback_message = """
            ⚠️ There was an issue processing the evaluation.

            📝 Basic Evaluation:
            - Your code was received and processed
            - Please check the syntax and formatting
            - Try submitting again if needed

            If the issue persists, please contact support.
            """
            await update.message.reply_text(fallback_message)

    async def send_daily_questions(self):
        users = self.db.load()
        for user_id, user_data in users.items():
            if datetime.now().strftime("%H:%M") == user_data.get('preferred_time'):
                question = self.llm.generate_question(
                    user_id,
                    user_data['grade'],
                    user_data['difficulty']
                )
                tip = self.llm.generate_daily_tip()
                
                message = f"""
                📚 Daily Python Question:
                
                {question}
                
                💡 Today's Coding Tip:
                {tip}
                
                You have 9 hours to submit your solution!
                """
                
                await self.send_message(user_id, message)

    async def send_weekly_challenge(self):
        users = self.db.load()
        challenge = self.llm.generate_weekly_challenge()
        
        announcement = f"""
        🏆 Weekly Coding Challenge! 🏆
        
        {challenge}
        
        Submit your solutions with /contest_submit
        Winners will be announced next Sunday!
        Good luck! 💪
        """
        
        # Send to all users
        for user_id in users:
            try:
                await self.send_message(user_id, announcement)
            except Exception as e:
                print(f"Failed to send challenge to {user_id}: {e}")

    async def check_submissions(self):
        # Placeholder for checking submissions
        print("Checking submissions...")
        # Implement your logic here

    async def send_message(self, chat_id, text):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        return response.json()

    async def send_document(self, chat_id, file_id):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        payload = {
            "chat_id": chat_id,
            "document": file_id
        }
        response = requests.post(url, json=payload)
        return response.json()

    async def handle_streak(self, update: Update, context: CallbackContext):
        user_id = str(update.message.chat_id)
        user_data = self.db.load().get(user_id, {})
        streak = user_data.get('streak', 0)
        await update.message.reply_text(f"🔥 Your current streak is {streak} days!")

    async def handle_leaderboard(self, update: Update, context: CallbackContext):
        leaderboard = self.db.get_leaderboard()
        leaderboard_text = "🏆 Leaderboard:\n\n"
        for rank, (user_id, user_data) in enumerate(leaderboard, start=1):
            leaderboard_text += f"{rank}. {user_data['name']} - Streak: {user_data.get('streak', 0)} days, Score: {user_data.get('total_score', 0)}\n"
        await update.message.reply_text(leaderboard_text)

    async def handle_settings(self, update: Update, context: CallbackContext):
        await update.message.reply_text("⚙️ Settings:\n\n1. Change notification time\n2. Change difficulty level\n\nUse /change_time or /change_difficulty to update your preferences.")

    async def handle_explain(self, update: Update, context: CallbackContext):
        await update.message.reply_text("📝 Explain feature coming soon!")

    async def handle_db_download(self, update: Update, context: CallbackContext):
        user_id = str(update.message.chat_id)
        
        # Check if the user is admin
        if user_id != ADMIN_CHAT_ID:
            await update.message.reply_text("⚠️ You are not authorized to use this command.")
            return
        
        try:
            with open(DATA_FILE, 'rb') as db_file:
                await update.message.reply_document(
                    document=db_file,
                    filename='db.json',
                    caption='📊 Current database snapshot'
                )
        except Exception as e:
            logger.error(f"Error sending database file: {e}")
            await update.message.reply_text("❌ Error retrieving database file.")

    async def check_and_send_questions(self):
        users = self.db.load()
        # Get the current time in IST
        ist = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(ist).strftime("%H:%M")
        logger.info(f"Checking questions at {current_time} IST")
        
        for user_id, user_data in users.items():
            logger.info(f"User {user_id} preferred time: {user_data.get('preferred_time')}")
            if user_data.get('preferred_time') == current_time:
                logger.info(f"Sending question to user {user_id}")
                try:
                    question_json = self.llm.generate_question(
                        user_id,
                        user_data['grade'],
                        user_data['difficulty']
                    )
                    
                    question_data = json.loads(question_json)
                    
                    message = f"""
                    📚 Daily Python Question:

                    **Problem Statement:**
                    {question_data['question']}

                    **Example Input/Output:**
                    {question_data['example']}

                    **Test Cases:**
                    {', '.join(question_data['test_cases'])}

                    **Solution Template:**
                    ```python
                    {question_data['template']}
                    ```

                    You have 9 hours to submit your solution!
                    """
                    
                    await self.send_message(user_id, message)
                    logger.info(f"Sent daily question to user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to send question to user {user_id}: {e}")

    def schedule_daily_tasks(self):
        # Check every minute instead of specific times
        schedule.every(1).minutes.do(
            lambda: asyncio.run(self.check_and_send_questions())
        )
        logger.info("Scheduled tasks set up")
        schedule.every().sunday.at("09:00").do(
            lambda: asyncio.run(self.send_weekly_challenge())
        )

    async def set_commands(self, app):
        commands = [
            ("start", "Register and begin learning"),
            ("chat", "Get help from AI assistant"),
            ("hint", "Get a hint for current question"),
            ("explain", "Get detailed explanation"),
            ("streak", "Check your streak"),
            ("leaderboard", "See top performers"),
            ("progress", "View your progress"),
            ("settings", "Change your preferences"),
            ("help", "Show this help message"),
        ]
        await app.bot.set_my_commands(commands)

    def run(self):
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).connect_timeout(20).read_timeout(20).build()

        # Register commands with Telegram
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.set_commands(app))

        # Conversation handler and other handlers
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_age)],
                GRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_grade)],
                DIFFICULTY: [CallbackQueryHandler(self.get_difficulty, pattern='^(Beginner|Intermediate|Advanced)$')],
                TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_time)],
            },
            fallbacks=[],
        )

        chat_handler = ConversationHandler(
            entry_points=[CommandHandler("chat", self.start_chat)],
            states={
                CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_chat)],
            },
            fallbacks=[CommandHandler("end_chat", self.end_chat)],
        )

        app.add_handler(conv_handler)
        app.add_handler(chat_handler)
        app.add_handler(CommandHandler("help", self.handle_help))
        app.add_handler(CommandHandler("streak", self.handle_streak))
        app.add_handler(CommandHandler("leaderboard", self.handle_leaderboard))
        app.add_handler(CommandHandler("settings", self.handle_settings))
        app.add_handler(CommandHandler("explain", self.handle_explain))
        app.add_handler(MessageHandler(filters.Document.ALL, self.handle_submission))
        app.add_handler(CommandHandler("db_download", self.handle_db_download))

        # Create and run the scheduler in a separate thread
        def run_scheduler():
            self.schedule_daily_tasks()
            while True:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds

        # Start scheduler in a separate thread
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        # Add logging for bot startup
        logger.info("Bot and scheduler are running...")
        app.run_polling()

if __name__ == "__main__":
    bot = PythonLearningBot()
    bot.run()

