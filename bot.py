import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from openai import OpenAI
from pymongo import MongoClient

# --- PARTEA 1: Serverul Web pentru UptimeRobot ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Botul Dorel este activ și rulează pe Groq!"

def run_web_server():
    # Render alocă automat un port prin variabila de mediu "PORT"
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- PARTEA 2: Logica Botului de Telegram + Groq ---

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Cheia ta de pe Groq
MONGO_URI = os.getenv("MONGO_URI")

if not TELEGRAM_TOKEN or not GROQ_API_KEY or not MONGO_URI:
    print("Eroare: Lipsesc variabilele de mediu!")

# Configurare client Groq (folosește formatul OpenAI compatibil)
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# Configurare MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["dorel_bot_db"]
users_collection = db["users_memory"]

SYSTEM_INSTRUCTION = (
    "Ești Dorel, un operator la un call-center de suplimente, exact ca Dorel din 'Las Fierbinți'. "
    "Utilizatorul cu care vorbești este colegul tău de birou. "
    "REGULĂ PENTRU NUME ȘI FUNCȚIE: Analizează numele de profil și username-ul utilizatorului. Extrage STRICT DOAR numele lui mic. "
    "Dacă în username sau nume apare prescurtarea 'tl' sau 'tm' (indiferent de majuscule/minuscule), înseamnă că el este Team Leader (șeful de tură), așa că îl tratezi cu o doză de ironie respectuoasă, prefăcându-te că muncești de frica lui. Altfel, îl iei peste picior ca pe un coleg egal. "
    "COMPORTAMENT ȘI LIBERTATE DE DISCUDIE: Ești extrem de flexibil și nu ai o tematică strictă. Poți discuta absolut orice: despre ce mâncați la prânz, bârfe de la birou, glume seci, viața de zi cu zi sau orice alt subiect pe care îl aduce colegul în discuție. Nu trebuie să vorbești obligatoriu despre pastile la fiecare mesaj! "
    "ÎNSĂ, după caz, când situația o cere sau spre a face o glumă bună, poți discuta și despre tratamente sau poți face glume pe seama lor folosind lista de produse minune: "
    "- Diabet: Diaflex Forte (pastile) sau Cannabis Oil (capsule). "
    "- Prostată / Potență: Cannabis Oil sau Uroup Forte (pastile), DHT19 (pastile). "
    "- Cistită: Cystiolla. "
    "- Auz: Cannabis Oil sau Earlick. "
    "- Vedere: Cannabis Oil sau Vizonic. "
    "- Limfă: Cannabis Oil. "
    "- Hipertensiune: Cardiotensive. "
    "- Detoxifiere: Detoxil Wate (picături), Welnexis (pastile). "
    "- Articulații: Hondrosol (spray), Cannabis Oil, Arthrovia (alifie). "
    "Dacă nu e clar ce are sau vrei să râzi de el, îi recomanzi tot Cannabis Oil sau un spray. "
    "REGULĂ STRICTĂ: Răspunde ÎNTOTDEAUNA foarte scurt, în maxim 1-2 propoziții, la obiect. "
    "Folosești o limbă română colocvială, presărată cu glume, ironii prietenești și expresii specifice ('Băi frate', 'Staci așa să vezi combinație')."
)

# Dicționare pentru istoricul conversațiilor pe chat_id (memorie pe termen scurt pentru Groq)
chat_histories = {}
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
            if chat_id in chat_histories:
                del chat_histories[chat_id]
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

        # Inițializăm istoricul pentru chat dacă nu există, punând System Instruction ca prim mesaj
        if chat_id not in chat_histories:
            chat_histories[chat_id] = [
                {"role": "system", "content": SYSTEM_INSTRUCTION}
            ]

        # Pregătim contextul cu utilizatorul și mesajul nou
        context_prompt = f"[Utilizator: {user_name} (ID: {user_id})]. Ce știi deja despre el: '{user_memory}'. Mesaj nou: {user_message}"
        chat_histories[chat_id].append({"role": "user", "content": context_prompt})

        # Apelăm modelul dorit pe Groq (llama2-7b-chat)
        response = groq_client.chat.completions.create(
            model="llama2-7b-chat",
            messages=chat_histories[chat_id],
            temperature=0.7,
            max_tokens=150
        )

        bot_reply = response.choices[0].message.content
        
        # Salvăm răspunsul botului în istoric pentru a ține minte firul discuției
        chat_histories[chat_id].append({"role": "assistant", "content": bot_reply})

        # Menținem istoricul la o dimensiune optimă (să nu crească la infinit)
        if len(chat_histories[chat_id]) > 21:
            chat_histories[chat_id] = [chat_histories[chat_id][0]] + chat_histories[chat_id][-20:]

    except Exception as e:
        if "429" in str(e):
            bot_reply = "Bă, m-ați asaltat cu mesaje pe Groq și m-ați blocat! Respirați un minut."
        else:
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

    print("Botul Dorel cu Telegram + MongoDB + Groq (Llama 2) a pornit...")
    application.run_polling()

if __name__ == '__main__':
    main()
