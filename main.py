import os
import discord
import requests
import qrcode
import asyncio
import aiohttp
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from flask_app import run_flask_app

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("DISCORD_TOKEN")
LNBITS_URL = os.getenv("LNBITS_URL", "https://legend.lnbits.com").rstrip('/')
INVOICE_KEY = os.getenv("INVOICE_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
FOOTER_TEXT = os.getenv("FOOTER_TEXT", "⚡ Lightning Wallet Bot")
YOUR_DISCORD_ID = int(os.getenv("YOUR_DISCORD_ID", "1234567890"))

# --- INICIALIZACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
payment_history = []

# --- FUNCIONES AUXILIARES ---
def generate_lightning_qr(lightning_invoice):
    """Genera un QR para una factura Lightning."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=4)
    qr.add_data(lightning_invoice)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

async def get_btc_price():
    """Obtiene el precio actual de BTC en USD."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data["bitcoin"]["usd"]
    except:
        return None

async def send_deposit_notification(payment):
    """Envía notificación al admin sobre un depósito."""
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

    admin = await bot.fetch_user(865597179145486366)
    if admin:
        await admin.send(embed=embed)

    payment_history.append({"memo": user_memo, "sats": sats, "usd": usd})

# --- PRESENCIA DEL BOT ---
async def update_bot_presence():
    """Actualiza la presencia del bot con el precio de BTC."""
    while True:
        btc_price = await get_btc_price()
        if btc_price:
            await bot.change_presence(activity=discord.Game(name=f"BTC: ${btc_price:,.2f}"))
        await asyncio.sleep(60)

# --- COMANDOS ---
@bot.tree.command(name="balance", description="Muestra el saldo actual de la billetera")
async def ver_balance(interaction: discord.Interaction):
    """Muestra el saldo de la billetera."""
    try:
        headers = {'X-Api-Key': ADMIN_KEY}
        response = requests.get(f"{LNBITS_URL}/api/v1/wallet", headers=headers, timeout=10)
        wallet_info = response.json()

        if 'error' in wallet_info:
            await interaction.response.send_message(f"Error al obtener balance: {wallet_info['error']}", ephemeral=True)
            return

        embed = discord.Embed(
            title="💰 Balance de la Billetera",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )

        balance_sats = wallet_info['balance'] / 1000
        embed.add_field(name="Saldo Disponible", value=f"**{balance_sats:,.0f} sats**", inline=False)

        btc_price = await get_btc_price()
        if btc_price:
            usd_value = (balance_sats / 100_000_000) * btc_price
            embed.add_field(name="USD Aproximado", value=f"${usd_value:,.2f} USD", inline=True)

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"Error en ver_balance: {e}")
        await interaction.response.send_message("Error al obtener el balance", ephemeral=True)

@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)")
@app_commands.describe(factura="Factura Lightning en formato BOLT11")
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos (solo admin)."""
    if interaction.user.id != YOUR_DISCORD_ID:
        await interaction.response.send_message("❌ No tienes permiso para usar este comando.", ephemeral=True)
        return

    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message("La factura no parece ser válida.", ephemeral=True)
            return

        headers = {'X-Api-Key': ADMIN_KEY}
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json={"out": True, "bolt11": factura}, headers=headers)
        data = response.json()

        if "payment_hash" not in data:
            await interaction.response.send_message(f"Error al procesar el pago: {data.get('detail', 'Desconocido')}", ephemeral=True)
            return

        embed = discord.Embed(
            title="Pago Realizado",
            description=f"Pago Lightning procesado correctamente.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Hash del Pago", value=f"```{data['payment_hash']}```", inline=False)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        print(f"Error en retirar_fondos: {e}")
        await interaction.response.send_message("Error interno al procesar el pago.", ephemeral=True)

@bot.tree.command(name="factura", description="Genera una factura Lightning con QR")
@app_commands.describe(monto="Cantidad en satoshis", descripcion="Descripción del pago")
async def generar_factura(interaction: discord.Interaction, monto: int, descripcion: str = "Pago desde Discord"):
    """Genera una factura Lightning con QR."""
    try:
        payload = {"out": False, "amount": monto, "memo": descripcion, "unit": "sat"}
        headers = {'X-Api-Key': INVOICE_KEY}
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers)
        data = response.json()

        bolt11 = data.get("bolt11")
        qr = generate_lightning_qr(f"lightning:{bolt11}")
        file = discord.File(qr, filename="invoice_qr.png")

        embed = discord.Embed(
            title="⚡ Factura Lightning Generada",
            description=f"**{monto:,.0f} sats** - `{descripcion}`",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="BOLT11", value=f"```{bolt11}```", inline=False)
        embed.set_image(url="attachment://invoice_qr.png")
        await interaction.response.send_message(embed=embed, file=file)
    except Exception as e:
        print(f"Error en generar_factura: {e}")
        await interaction.response.send_message("Error interno al generar la factura.", ephemeral=True)

@bot.tree.command(name="estado", description="Muestra el estado del bot")
async def estado(interaction: discord.Interaction):
    """Muestra el estado actual del bot."""
    btc_price = await get_btc_price()
    embed = discord.Embed(
        title="📡 Estado del Bot",
        description="El bot está activo y funcionando.",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.add_field(
        name="Precio BTC actual",
        value=f"${btc_price:,.2f} USD" if btc_price else "No disponible",
        inline=False
    )
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="calcular_sats", description="Calcula cuántos satoshis equivalen a un monto en USD")
@app_commands.describe(dolares="Cantidad en dólares para convertir a satoshis.")
async def calcular_sats(interaction: discord.Interaction, dolares: float):
    """Convierte dólares a satoshis basado en el precio actual de BTC."""
    btc_price = await get_btc_price()
    if not btc_price:
        await interaction.response.send_message("No se pudo obtener el precio actual de BTC.", ephemeral=True)
        return

    sats = (dolares / btc_price) * 100_000_000
    embed = discord.Embed(
        title="💰 Conversión USD a Satoshis",
        description=f"**${dolares:,.2f} USD** equivale aproximadamente a **{sats:,.0f} sats**.",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="Muestra todos los comandos del bot")
async def help_command(interaction: discord.Interaction):
    """Listar los comandos disponibles del bot."""
    embed = discord.Embed(
        title="📋 Comandos Disponibles",
        description="Lista de comandos que puedes usar con este bot:",
        color=discord.Color.purple(),
        timestamp=datetime.now()
    )
    embed.add_field(name="/estado", value="Muestra el estado del bot y el precio actual de BTC.", inline=False)
    embed.add_field(name="/calcular_sats", value="Calcula cuántos satoshis corresponden a un monto en USD.", inline=False)
    embed.add_field(name="/help", value="Muestra esta ayuda.", inline=False)
    embed.add_field(name="/factura", value = "Permite generar una nueva factura", inline = False)
    embed.add_field(name = "/retirar", value = "Comando exclusivo para administradores", inline = False)
    embed.add_field(name = "/balance", value = "Muestra el balance actual de la wallet", inline = False)
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

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

# --- MONITOREO DE PAGOS EN SEGUNDO PLANO ---
async def check_payments():
    """Verifica depósitos entrantes en segundo plano."""
    await bot.wait_until_ready()
    last_checked = None

    while not bot.is_closed():
        try:
            headers = {'X-Api-Key': INVOICE_KEY}
            response = requests.get(f"{LNBITS_URL}/api/v1/payments", headers=headers, timeout=10)
            pagos = response.json()

            for payment in pagos:
                if payment["pending"] is False and payment.get("incoming", False):
                    if payment["payment_hash"] != last_checked:  # Solo procesamos nuevos pagos
                        last_checked = payment["payment_hash"]
                        await send_deposit_notification(payment)
        except Exception as e:
            print(f"Error verificando pagos: {e}")

        await asyncio.sleep(25)

# --- EVENTOS ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot conectado como: {bot.user}")
    bot.loop.create_task(check_payments())
    bot.loop.create_task(update_bot_presence())

# --- INICIAR EL BOT ---
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    bot.run(TOKEN)
