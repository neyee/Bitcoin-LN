import telebot
import os

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("TELEGRAM_TOKEN")  # Reemplaza con el token de tu bot de Telegram
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))  # Reemplaza con tu ID de usuario de Telegram (Administrador)
FOOTER_TEXT = "Bot de Tasa de Cambio"

# --- VARIABLE GLOBAL PARA LA TASA DE CAMBIO ---
tasa_cambio = None

# --- INICIALIZACIÓN DEL BOT ---
bot = telebot.TeleBot(TOKEN)

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Maneja los comandos /start y /help."""
    bot.reply_to(message, f"""
¡Hola! Soy un bot que te proporciona la tasa de cambio.
Soy manejado por un administrador.
- Usa /dolar para obtener la tasa actual.
- Solo el administrador puede usar /settasa <tasa> para establecer la tasa.
""")

@bot.message_handler(commands=['settasa'])
def set_tasa(message):
    """Maneja el comando /settasa (solo para el administrador)."""
    global tasa_cambio
    user_id = message.from_user.id

    if user_id == ADMIN_USER_ID:
        try:
            tasa = float(message.text.split()[1]) #Extrae la tasa del mensaje
            tasa_cambio = tasa
            bot.reply_to(message, f"✅ Tasa de cambio establecida en {tasa} VES por USD.")
        except (IndexError, ValueError):
            bot.reply_to(message, "❌ Uso incorrecto. Usa: /settasa <tasa>")
    else:
        bot.reply_to(message, "🚫 No tienes permiso para usar este comando.")

@bot.message_handler(commands=['dolar'])
def send_dolar_bcv(message):
    """Maneja el comando /dolar."""
    if tasa_cambio is not None:
        mensaje = f"""
🏦 **Tasa de Cambio** 🏦

Tasa de cambio establecida por el administrador:
**1 USD = {tasa_cambio} VES**
"""
        bot.reply_to(message, mensaje, parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ La tasa de cambio no ha sido establecida todavía. Contacta al administrador.")

# --- INICIO DEL BOT ---
if __name__ == "__main__":
    print("Iniciando el bot de Telegram...")
    bot.infinity_polling()
