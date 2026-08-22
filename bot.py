import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import google.generativeai as genai

# 1. Preluarea cheilor din variabilele de mediu (Render / Sistem)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not TELEGRAM_TOKEN or not GOOGLE_API_KEY:
    print("Eroare: TELEGRAM_TOKEN sau GOOGLE_API_KEY nu sunt setate!")

genai.configure(api_key=GOOGLE_API_KEY)

# 2. Setarea caracterului botului
SYSTEM_INSTRUCTION = (
    "Ești Dorel, un asistent virtual prietenos, inteligent și util pe Telegram. "
    "Răspunzi concis, la obiect și într-un ton cald. "
    "Când vorbești cu cineva în grup, folosește numele persoanei."
)

generation_config = {
    "temperature": 0.7,
}
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    generation_config=generation_config,
    system_instruction=SYSTEM_INSTRUCTION
)

# Dicționare pentru a ține minte starea și memoria per chat
user_chats = {}     # Istoricul conversației pentru fiecare chat_id
active_chats = set() # Set cu chat_id-urile în care Dorel este activ

# Cuvintele care fac botul să se oprească din conversație
STOP_WORDS = ["pa dorel", "gata dorel", "ajunge dorel", "stai dorel", "pa", "la revedere", "gata"]

# Numele botului
BOT_NAMES = ["dorel"]

# Activează logurile
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_message = update.message.text
    chat_id = update.message.chat_id
    message_lower = user_message.lower()
    
    user = update.message.from_user
    user_name = user.first_name if user and user.first_name else "Utilizator"

    is_group = update.message.chat.type in ['group', 'supergroup']
    
    # 1. Verificăm dacă suntem într-un grup și dacă s-a dat un cuvânt de stop
    if is_group and chat_id in active_chats:
        if any(stop_word in message_lower for stop_word in STOP_WORDS):
            active_chats.remove(chat_id)
            await update.message.reply_text("Am înțeles, mă retrag. Pa-pa! 🤖")
            return

    # 2. Verificăm dacă cineva l-a strigat pe nume
    is_called = any(name in message_lower for name in BOT_NAMES)

    if is_group:
        if is_called:
            active_chats.add(chat_id)
        elif chat_id not in active_chats:
            return
    
    print(f"Mesaj de la {user_name} în chat {chat_id}: {user_message}")

    try:
        if chat_id not in user_chats:
            user_chats[chat_id] = model.start_chat(history=[])
        
        chat_session = user_chats[chat_id]
        final_prompt = f"[Utilizatorul {user_name}]: {user_message}"

        response = chat_session.send_message(final_prompt)
        bot_reply = response.text

    except Exception as e:
        bot_reply = "Ne pare rău, a apărut o eroare la procesarea solicitării."
        print(f"Eroare AI: {e}")

    await update.message.reply_text(bot_reply)

if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    application.add_handler(message_handler)

    print("Botul Dorel a pornit...")
    application.run_polling()
