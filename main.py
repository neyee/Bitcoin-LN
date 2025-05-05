import os
import discord
import requests
import qrcode
import asyncio
import aiohttp
import time
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from flask import Flask

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("DISCORD_TOKEN")
LNBITS_URL = os.getenv("LNBITS_URL", "https://legend.lnbits.com").rstrip('/')
INVOICE_KEY = os.getenv("INVOICE_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
FOOTER_TEXT = os.getenv("FOOTER_TEXT", "⚡ Lightning Wallet Bot")
YOUR_DISCORD_ID = int(os.getenv("YOUR_DISCORD_ID", "1234567890"))

# --- INICIALIZACION DE BOT Y FLASK ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
app = Flask(__name__)
payment_history = []

@app.route("/")
def index():
    return "Lightning Wallet Bot corriendo."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- FUNCIONES AUXILIARES ---
def generate_lightning_qr(lightning_invoice):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=4
    )
    qr.add_data(lightning_invoice)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def get_btc_price():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data["bitcoin"]["usd"]
    except:
        return None

async def send_deposit_notification(payment):
    user_memo = payment.get("memo", "Sin descripción")
    sats = payment["amount"] / 1000
    usd = 0
    btc_price = await get_btc_price()
    if btc_price:
        usd = (sats / 100_000_000) * btc_price

    embed = discord.Embed(
        title="✅ Nuevo Depósito Recibido",
        description=f"**{sats:,.0f} sats** (~${usd:,.2f} USD)",
        color=0x1abc9c,
        timestamp=datetime.now()
    )
    embed.add_field(name="Descripción", value=f"```{user_memo}```", inline=False)
    embed.set_footer(text=FOOTER_TEXT)

    admin = await bot.fetch_user(YOUR_DISCORD_ID)
    if admin:
        await admin.send(embed=embed)

    payment_history.append({
        "memo": user_memo,
        "sats": sats,
        "usd": usd
    })

# --- COMANDO /retirar ORIGINAL ---
@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)")
@app_commands.describe(factura="Factura Lightning en formato BOLT11")
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos"""
    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message(
                "La factura no parece ser válida (debe comenzar con 'lnbc')",
                ephemeral=True
            )
            return

        class ConfirmView(discord.ui.View):
            def __init__(self, original_interaction):
                super().__init__()
                self.original_interaction = original_interaction

            @discord.ui.button(label='Confirmar Pago', style=discord.ButtonStyle.green)
            async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                if button_interaction.user != self.original_interaction.user:
                    await button_interaction.response.send_message("No puedes confirmar este pago", ephemeral=True)
                    return

                await button_interaction.response.defer()

                headers = {
                    'X-Api-Key': ADMIN_KEY,
                    'Content-type': 'application/json'
                }
                payload = {
                    "out": True,
                    "bolt11": factura
                }

                response = requests.post(
                    f"{LNBITS_URL}/api/v1/payments",
                    json=payload,
                    headers=headers,
                    timeout=10
                )

                payment_data = response.json()

                if 'error' in payment_data or 'payment_hash' not in payment_data:
                    error = payment_data.get('detail', payment_data.get('error', 'Error desconocido'))
                    await button_interaction.followup.send(
                        f"Error al procesar el pago: {error}",
                        ephemeral=True
                    )
                    return

                embed = discord.Embed(
                    title="Pago Realizado",
                    description="Se ha procesado el pago correctamente.",
                    color=0x28a745,
                    timestamp=datetime.now()
                )

                embed.add_field(
                    name="Hash del Pago",
                    value=f"```{payment_data['payment_hash']}```",
                    inline=False
                )

                if 'amount' in payment_data:
                    amount_sats = payment_data['amount'] / 1000
                    embed.add_field(
                        name="Monto",
                        value=f"{amount_sats:,.0f} sats",
                        inline=True
                    )

                    btc_price = await get_btc_price()
                    if btc_price:
                        usd_value = (amount_sats / 100_000_000) * btc_price
                        embed.add_field(
                            name="USD",
                            value=f"${usd_value:,.2f} USD",
                            inline=True
                        )

                embed.set_footer(text=FOOTER_TEXT)
                await button_interaction.followup.send(embed=embed)

        view = ConfirmView(interaction)
        await interaction.response.send_message(
            "¿Confirmas que deseas pagar esta factura Lightning?",
            view=view,
            ephemeral=True
        )

    except Exception as e:
        print(f"Error en retirar_fondos: {e}")
        await interaction.response.send_message(
            "Error al procesar el pago",
            ephemeral=True
        )

# --- COMANDO /estado ---
@bot.tree.command(name="estado", description="Muestra el estado del bot")
async def estado(interaction: discord.Interaction):
    btc_price = await get_btc_price()
    embed = discord.Embed(
        title="📡 Estado del Bot",
        description="El bot está funcionando correctamente.",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.add_field(name="Precio BTC actual", value=f"${btc_price:,.2f} USD" if btc_price else "No disponible", inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

# --- COMANDO /historial_pagos ---
@bot.tree.command(name="historial_pagos", description="Ver historial de pagos recibidos")
async def historial(interaction: discord.Interaction):
    if not payment_history:
        await interaction.response.send_message("Aún no se han recibido pagos.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📜 Historial de Pagos Recibidos",
        color=discord.Color.purple(),
        timestamp=datetime.now()
    )

    for p in payment_history[-10:]:  # Máximo 10 últimos pagos
        embed.add_field(
            name=f"🧾 {p['memo']}",
            value=f"**{p['sats']:,.0f} sats** (~ ${p['usd']:,.2f} USD)",
            inline=False
        )

    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

# --- BACKGROUND TASK PARA VERIFICAR PAGOS ---
async def check_payments():
    await bot.wait_until_ready()
    last_check = None
    while not bot.is_closed():
        try:
            headers = {'X-Api-Key': INVOICE_KEY}
            r = requests.get(f"{LNBITS_URL}/api/v1/payments", headers=headers)
            pagos = r.json()
            for p in pagos:
                if p["pending"] is False and p["payment_hash"] != last_check and p["incoming"]:
                    await send_deposit_notification(p)
                    last_check = p["payment_hash"]
        except Exception as e:
            print(f"Error verificando pagos: {e}")
        await asyncio.sleep(25)

# --- EVENTOS ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot conectado como: {bot.user}")
    bot.loop.create_task(check_payments())

# --- MAIN ---
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    bot.run(TOKEN)
