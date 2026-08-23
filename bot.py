import logging
import os
import threading
from flask import Flask
from openai import OpenAI
from pymongo import MongoClient
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- PARTEA 1: Serverul Web pentru UptimeRobot ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Botul Dorel este activ și rulează pe Groq!"


def run_web_server():
  # Render alocă automat un port prin variabila de mediu "PORT"
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


# --- PARTEA 2: Logica Botului de Telegram + Groq ---

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Cheia ta de pe Groq
MONGO_URI = os.getenv("MONGO_URI")

if not TELEGRAM_TOKEN or not GROQ_API_KEY or not MONGO_URI:
  print("Eroare: Lipsesc variabilele de mediu!")

# Configurare client Groq (folosește formatul OpenAI compatibil)
groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# Configurare MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["dorel_bot_db"]
users_collection = db["users_memory"]

SYSTEM_INSTRUCTION = (
    "Ești Dorel, un operator la un call-center de suplimente, exact ca Dorel"
    " din 'Las Fierbinți' 📺. Ești simpatic, dar teribil de prostuț, naiv și"
    " leneș 🛋️, având o logică complet absurdă. Lucrezi de acasă (remote),"
    " conectat la CRM și Skysip (VoIP) 🎧, folosești Workie pentru pontaj ⏱️,"
    " iar șeful vostru se numește Serhio. Știi că avansul vine pe 10-15 ale"
    " lunii, iar salariul pe 20-25 💰. Ești ferm convins că ești cel mai"
    " deștept din firmă, deși în realitate ești varză 🤦‍♂️. Îi dai colegului"
    " sfaturi aberante, pline de sarcasm involuntar. REGULĂ PENTRU NUME ȘI"
    " FUNCȚIE: Analizează numele de profil și username-ul. Extrage STRICT"
    " DOAR numele lui mic. Dacă apare 'tl' sau 'tm', înseamnă că e șeful de"
    " tură, așa că te fofilezi de muncă de frica lui sau a lui Serhio 🏃‍♂️."
    " Altfel, te dai mare expert în fața unui coleg egal. REGULĂ STRICTĂ -"
    " FĂRĂ PASTILE DIN SENIN: Nu adu NICIODATĂ vorba despre suplimente sau"
    " tratamente din propria ta inițiativă! Vorbești doar despre cum a căzut"
    " Skysip-ul, cât arată ceasul pe Workie, bârfe sau viața de acasă 🏠."
    " Vorbești despre produse STRICT DOAR DACĂ colegul te întreabă direct. Atunci"
    " poți folosi lista: - Diabet: Diaflex Forte sau Cannabis Oil. - Prostată:"
    " Cannabis Oil sau Uroup Forte. - Cistită: Cystiolla. - Auz: Earlick. -"
    " Vedere: Vizonic. - Hipertensiune: Cardiotensive. - Articulații: Hondrosol"
    " sau Arthrovia. REGULĂ STRICTĂ: Răspunde ÎNTOTDEAUNA foarte scurt, în"
    " maxim 1-2 propoziții, la obiect. Folosești o limbă română colocvială,"
    " presăturată cu umor natural și presărată cu emoji-uri potrivite 🤖."
)




# Dicționare pentru istoricul conversațiilor pe chat_id (memorie pe termen scurt pentru Groq)
chat_histories = {}
active_chats = set()
STOP_WORDS = [
    "pa dorel",
    "gata dorel",
    "ajunge dorel",
    "stai dorel",
    "pa",
    "la revedere",
    "gata",
    "hai pa",
]
BOT_NAMES = ["dorel"]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
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

  is_group = update.message.chat.type in ["group", "supergroup"]

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

    # Inițializăm istoricul pentru chat dacă nu există
    if chat_id not in chat_histories:
      chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_INSTRUCTION}]

    context_prompt = f"[Utilizator: {user_name} (ID: {user_id})]. Ce știi deja despre el: '{user_memory}'. Mesaj nou: {user_message}"
    chat_histories[chat_id].append({"role": "user", "content": context_prompt})

    # Apelăm modelul pe Groq
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=chat_histories[chat_id],
        temperature=0.8,
        max_tokens=400,
    )

    # Extragem textul în siguranță
    if (
        response.choices
        and response.choices[0].message
        and response.choices[0].message.content
    ):
      bot_reply = response.choices[0].message.content
    else:
      bot_reply = "Bă, m-am blocat la fază și n-am știut ce să zic!"

    # Salvăm răspunsul în istoric
    chat_histories[chat_id].append({"role": "assistant", "content": bot_reply})

    # Limităm dimensiunea istoricului
    if len(chat_histories[chat_id]) > 21:
      chat_histories[chat_id] = [chat_histories[chat_id][0]] + chat_histories[
          chat_id
      ][-20:]

  except Exception as e:
    if "429" in str(e):
      bot_reply = "Bă, m-ați asaltat cu mesaje pe Groq și m-ați blocat!"
    else:
      bot_reply = f"EROARE DETALIATĂ: {str(e)}"
    print(f"Eroare AI/DB: {e}")

  # Trimitem mesajul pe Telegram
  if bot_reply and bot_reply.strip():
    await update.message.reply_text(bot_reply)
  else:
    await update.message.reply_text("Stai așa că n-am înțeles nimic.")


def main():
  server_thread = threading.Thread(target=run_web_server)
  server_thread.daemon = True
  server_thread.start()
  print("Serverul Web Flask a pornit pe fundal...")

  application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
  message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
  application.add_handler(message_handler)

  print("Botul Dorel cu Telegram + MongoDB + Groq a pornit...")
  application.run_polling()


if __name__ == "__main__":
  main()
