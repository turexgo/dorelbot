import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import google.generativeai as genai
from pymongo import MongoClient

# --- PARTEA 1: Serverul Web pentru UptimeRobot ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Botul Dorel este activ și rulează!"

def run_web_server():
    # Render alocă automat un port prin variabila de mediu "PORT"
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- PARTEA 2: Logica Botului de Telegram ---

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

if not TELEGRAM_TOKEN or not GOOGLE_API_KEY or not MONGO_URI:
    print("Eroare: Lipsesc variabilele de mediu!")

genai.configure(api_key=GOOGLE_API_KEY)

# Configurare MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["dorel_bot_db"]
users_collection = db["users_memory"]

SYSTEM_INSTRUCTION = (
    "Ești Dorel, un asistent virtual prietenos, inteligent și util pe Telegram. "
    "Răspunzi concis, la obiect și într-un ton cald. "
    "Folosești informațiile cunoscute despre utilizator pentru a personaliza discuția."
)

generation_config = {"temperature": 0.7}
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    generation_config=generation_config,
    system_instruction=SYSTEM_INSTRUCTION
)

user_chats = {}
active_chats = set()
STOP_WORDS = ["pa dorel", "gata dorel", "ajunge dorel", "stai dorel", "pa", "la revedere", "gata"]
BOT_NAMES = ["dorel"]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def get_user_profile(user_id):
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        user_data = {"user_id": user_id, "memory": ""}
        users_collection.insert_one(user_data)
    return user_data.get("memory", "")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_message = update.message.text
    chat_id = update.message.chat_id
    message_lower = user_message.lower()
    
    user = update.message.from_user
    user_id = user.id if user else 0
    user_name = user.first_name if user and user.first_name else "Utilizator"

    is_group = update.message.chat.type in ['group', 'supergroup']
    
    if is_group and chat_id in active_chats:
        if any(stop_word in message_lower for stop_word in STOP_WORDS):
            active_chats.remove(chat_id)
            await update.message.reply_text("Am înțeles, mă retrag. Pa-pa! 🤖")
            return

    is_called = any(name in message_lower for name in BOT_NAMES)

    if is_group:
        if is_called:
            active_chats.add(chat_id)
        elif chat_id not in active_chats:
            return
    
    print(f"Mesaj de la {user_name} (ID: {user_id}): {user_message}")

    try:
        user_memory = get_user_profile(user_id)

        if chat_id not in user_chats:
            user_chats[chat_id] = model.start_chat(history=[])
        
        chat_session = user_chats[chat_id]
        context_prompt = f"[Utilizator: {user_name} (ID: {user_id})]. Ce știi deja despre el: '{user_memory}'. Mesaj nou: {user_message}"

        response = chat_session.send_message(context_prompt)
        bot_reply = response.text

    except Exception as e:
        bot_reply = f"EROARE DETALIATĂ: {str(e)}"
        print(f"Eroare AI/DB: {e}")


    await update.message.reply_text(bot_reply)

def main():
    # Pornim serverul Flask într-un fir separat (thread) pentru a nu bloca botul de Telegram
    server_thread = threading.Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()
    print("Serverul Web Flask a pornit pe fundal...")

    # Pornirea aplicației de Telegram
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    print("Botul Dorel cu Telegram + MongoDB + Web a pornit...")
    application.run_polling()

if __name__ == '__main__':
    main()

