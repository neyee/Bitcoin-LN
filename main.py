import discord
from discord.ext import commands
import os
from datetime import datetime
from flask import Flask, render_template_string
import threading

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("DISCORD_TOKEN")  # Reemplaza con el token de tu bot
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))  # Reemplaza con el ID del rol de administrador
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))  # Reemplaza con el ID del canal donde se publicará la tasa
FOOTER_TEXT = "Tasa de Cambio - Bot Admin"

# --- VARIABLE GLOBAL PARA LA TASA DE CAMBIO ---
tasa_dolar = None

# --- CONFIGURACIÓN DEL BOT ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FUNCIONES AUXILIARES ---
async def enviar_mensaje_tasa(tasa, channel):
    """Envía un mensaje con la tasa de cambio en un embed."""
    embed = discord.Embed(
        title="💰 Tasa de Cambio del Dólar 💰",
        description=f"La tasa de cambio actual es: **1 USD = {tasa} Bs**",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=FOOTER_TEXT)
    await channel.send(embed=embed)

# --- COMANDOS ---
@bot.tree.command(name="settasa", description="Establece la tasa de cambio del dólar (solo admin)")
async def settasa(interaction: discord.Interaction, tasa: float):
    """Establece la tasa de cambio del dólar (solo para administradores)."""
    # Verificar si el usuario tiene el rol de administrador
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message("Solo los administradores pueden usar este comando.", ephemeral=True)
        return

    global tasa_dolar
    tasa_dolar = tasa
    await interaction.response.send_message(f"Tasa de cambio establecida en **{tasa} Bs por USD**.", ephemeral=True)

@bot.tree.command(name="publicartasa", description="Publica la tasa de cambio en el canal (solo admin)")
async def publicartasa(interaction: discord.Interaction):
    """Publica la tasa de cambio en el canal (solo para administradores)."""
    # Verificar si el usuario tiene el rol de administrador
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message("Solo los administradores pueden usar este comando.", ephemeral=True)
        return

    if tasa_dolar is None:
        await interaction.response.send_message("La tasa de cambio no ha sido establecida. Usa /settasa para establecerla.", ephemeral=True)
        return

    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            await enviar_mensaje_tasa(tasa_dolar, channel)
            await interaction.response.send_message("Tasa de cambio publicada en el canal.", ephemeral=True)
        else:
            await interaction.response.send_message("No se pudo encontrar el canal. Verifica el ID del canal.", ephemeral=True)
    except Exception as e:
        print(f"Error al publicar la tasa: {e}")
        await interaction.response.send_message("Ocurrió un error al publicar la tasa. Consulta los registros del bot.", ephemeral=True)

# --- EVENTOS ---
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

# --- FLASK WEB APP ---
app = Flask(__name__)

@app.route('/')
def show_tasa():
    """Muestra la tasa de cambio en una página web."""
    if tasa_dolar is not None:
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Tasa de Cambio</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #f0f0f0;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                }}
                .container {{
                    background-color: #fff;
                    border-radius: 10px;
                    box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                    padding: 20px;
                    text-align: center;
                }}
                h1 {{
                    color: #333;
                }}
                p {{
                    font-size: 1.2em;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Tasa de Cambio del Dólar</h1>
                <p>1 USD = {tasa_dolar} VES</p>
            </div>
        </body>
        </html>
        """
        return render_template_string(html_content)
    else:
        return "<h1>Tasa de Cambio No Disponible</h1><p>Por favor, establece la tasa de cambio a través del bot de Discord.</p>"

# --- INICIO DEL BOT Y FLASK ---
if __name__ == "__main__":
    # Iniciar el bot de Discord y Flask en hilos separados
    import threading

    def run_discord_bot():
        bot.run(TOKEN)

    def run_flask_app():
        port = int(os.environ.get('PORT', 5000))
        app.run(debug=True, host='0.0.0.0', port=port)

    discord_thread = threading.Thread(target=run_discord_bot)
    flask_thread = threading.Thread(target=run_flask_app)

    discord_thread.start()
    flask_thread.start()
