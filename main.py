import os
import discord
import requests
import qrcode
import asyncio
import aiohttp
from io import BytesIO
from datetime import datetime
from discord.ext import commands, tasks
from discord import app_commands
from flask import Flask
import threading
from collections import defaultdict

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("DISCORD_TOKEN")
LNBITS_URL = os.getenv("LNBITS_URL", "https://legend.lnbits.com").rstrip('/')
INVOICE_KEY = os.getenv("INVOICE_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
FOOTER_TEXT = os.getenv("FOOTER_TEXT", "⚡ Lightning Wallet Bot")
YOUR_DISCORD_ID = int(os.getenv("YOUR_DISCORD_ID", 0))
OKX_API_URL = os.getenv("OKX_API_URL", "https://www.okx.com/api/v5/market/ticker?instId=")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", 60 * 60))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", 0))  # Canal para mensajes de bienvenida
DEFAULT_COLOR = int(os.getenv("DEFAULT_COLOR", "0xFFA500"), 16)  # Color por defecto para embeds (naranja)

# --- INICIALIZACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necesario para on_member_join
bot = commands.Bot(command_prefix="!", intents=intents)
payment_history = []
user_balances = defaultdict(int) # Para el sistema de economía

# --- INICIALIZACIÓN DE FLASK ---
app = Flask(__name__)

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
        color=0x4CAF50,
        timestamp=datetime.now()
    )
    embed.add_field(name="Descripción", value=f"```{user_memo}```", inline=False)
    embed.set_footer(text=FOOTER_TEXT)

    admin = await bot.fetch_user(YOUR_DISCORD_ID)
    if admin:
        await admin.send(embed=embed)

    payment_history.append({"memo": user_memo, "sats": sats, "usd": usd})

async def get_okx_price(instrument_id: str):
    """Obtiene el precio de un instrumento de OKX."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OKX_API_URL}{instrument_id}") as resp:
                data = await resp.json()
                if data["code"] == "0":
                    return data["data"][0]["last"]
                else:
                    return None
    except:
        return None

# --- PRESENCIA DEL BOT ---
async def update_bot_presence():
    """Actualiza la presencia del bot con el precio de BTC."""
    while True:
        btc_price = await get_btc_price()
        if btc_price:
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"BTC: ${btc_price:,.2f}"))
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
            color=DEFAULT_COLOR,
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
            color=DEFAULT_COLOR,
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
            color=DEFAULT_COLOR,
            timestamp=datetime.now()
        )
        embed.add_field(name="BOLT11", value=f"```{bolt11}```", inline=False)
        embed.set_image(url="attachment://invoice_qr.png")
        await interaction.response.send_message(embed=embed, file=file)
    except Exception as e:
        print(f"Error en generar_factura: {e}")
        await interaction.response.send_message("Error interno al generar la factura.", ephemeral=True)

@bot.tree.command(name="precios", description="Muestra los precios de diferentes tokens desde OKX")
async def precios(interaction: discord.Interaction, *tokens: str):
    """Muestra los precios de diferentes tokens desde OKX.

    Args:
        tokens: Lista de tokens a buscar (ej: BTC-USDT ETH-USDT).
    """
    if not tokens:
        await interaction.response.send_message("Por favor, especifica al menos un token (ej: BTC-USDT).", ephemeral=True)
        return

    prices = {}
    for token in tokens:
        price = await get_okx_price(token)
        if price:
            prices[token] = price

    if not prices:
        await interaction.response.send_message("No se pudieron obtener los precios de los tokens especificados.", ephemeral=True)
        return

    embed = discord.Embed(
        title="💰 Precios de Tokens (OKX)",
        color=DEFAULT_COLOR,
        timestamp=datetime.now()
    )

    for token, price in prices.items():
        embed.add_field(name=token, value=f"${price}", inline=True)

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

    sats = int((dolares / btc_price) * 100_000_000)
    embed = discord.Embed(
        title="💰 Conversión USD a Satoshis",
        description=f"**${dolares:,.2f} USD** equivale aproximadamente a **{sats:,.0f} sats**.",
        color=DEFAULT_COLOR,
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
        color=DEFAULT_COLOR,
        timestamp=datetime.now()
    )
    embed.add_field(name="/precios <token1> <token2> ...", value="Muestra el precio de tokens en Okx (ej: BTC-USDT ETH-USDT).", inline=False)
    embed.add_field(name="/calcular_sats", value="Calcula cuántos satoshis corresponden a un monto en USD.", inline=False)
    embed.add_field(name="/help", value="Muestra esta ayuda.", inline=False)
    embed.add_field(name="/factura", value = "Permite generar una nueva factura", inline = False)
    embed.add_field(name = "/retirar", value = "Comando exclusivo para administradores", inline = False)
    embed.add_field(name = "/balance", value = "Muestra el balance actual de la wallet", inline = False)
    embed.add_field(name = "/historial_pagos", value = "Muestra el historial de pago de la wallet", inline = False)
    embed.add_field(name="/enviar_embed", value="Envia un embed personalizado a un canal (solo admin).", inline=False)
    embed.add_field(name="/economy_balance", value="Muestra tu saldo en el sistema de economía.", inline=False)
    embed.add_field(name="/transfer <usuario> <monto>", value="Transfiere saldo a otro usuario en el sistema de economía.", inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="historial_pagos", description="Ver historial de pagos recibidos")
async def historial(interaction: discord.Interaction):
    if not payment_history:
        await interaction.response.send_message("Aún no se han recibido pagos.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📜 Historial de Pagos Recibidos",
        color=DEFAULT_COLOR,
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

@bot.tree.command(name="enviar_embed", description="Envia un embed personalizado a un canal (solo admin)")
@app_commands.describe(canal="Canal al que enviar el embed",
                     titulo="Título del embed",
                     descripcion="Descripción del embed",
                     color="Color del embed (hexadecimal, ej: FFA500)",
                     imagen="URL de la imagen del embed",
                     thumbnail="URL del thumbnail del embed")
async def enviar_embed(interaction: discord.Interaction,
                        canal: discord.TextChannel,
                        titulo: str,
                        descripcion: str,
                        color: str = None,
                        imagen: str = None,
                        thumbnail: str = None):
    """Envia un embed personalizado a un canal."""
    if interaction.user.id != YOUR_DISCORD_ID:
        await interaction.response.send_message("❌ No tienes permiso para usar este comando.", ephemeral=True)
        return

    embed_color = DEFAULT_COLOR
    if color:
        try:
            embed_color = int(color, 16)
        except ValueError:
            await interaction.response.send_message("❌ El color hexadecimal no es válido.", ephemeral=True)
            return

    embed = discord.Embed(
        title=titulo,
        description=descripcion,
        color=embed_color,
        timestamp=datetime.now()
    )
    embed.set_footer(text=FOOTER_TEXT)

    if imagen:
        embed.set_image(url=imagen)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    try:
        await canal.send(embed=embed)
        await interaction.response.send_message(f"✅ Embed enviado a {canal.mention} correctamente.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ No tengo permiso para enviar mensajes en ese canal.", ephemeral=True)
    except Exception as e:
        print(f"Error al enviar embed: {e}")
        await interaction.response.send_message(f"❌ Error al enviar el embed: {e}", ephemeral=True)

@bot.tree.command(name="economy_balance", description="Muestra tu saldo en el sistema de economía")
async def economy_balance(interaction: discord.Interaction):
  """Muestra el saldo del usuario en el sistema de economía."""
  user_id = interaction.user.id
  await interaction.response.send_message(f"Tu saldo es: {user_balances[user_id]}")

@bot.tree.command(name="transfer", description="Transfiere saldo a otro usuario")
@app_commands.describe(usuario="Usuario a transferir", monto="Monto a transferir")
async def transfer(interaction: discord.Interaction, usuario: discord.Member, monto: int):
  """Transfiere saldo a otro usuario."""
  sender_id = interaction.user.id
  receiver_id = usuario.id

  if monto <= 0:
    await interaction.response.send_message("El monto debe ser mayor a 0.")
    return

  if user_balances[sender_id] < monto:
    await interaction.response.send_message("No tienes suficiente saldo.")
    return

  user_balances[sender_id] -= monto
  user_balances[receiver_id] += monto
  await interaction.response.send_message(f"Transferiste {monto} a {usuario.name}.")

# --- COMANDOS DEL ADMINISTRADOR ---
@bot.command()
async def sync_commands(ctx):
    """Sincroniza los comandos slash (solo admin)."""
    if ctx.author.id == YOUR_DISCORD_ID:
        try:
            await bot.tree.sync()
            await ctx.send("Comandos sincronizados correctamente.")
        except Exception as e:
            await ctx.send(f"Error al sincronizar comandos: {e}")
    else:
        await ctx.send("No tienes permiso para usar este comando.")

@bot.command()
async def add_balance(ctx, member: discord.Member, amount: int):
    """Añade saldo a un usuario (solo admin)."""
    if ctx.author.id != YOUR_DISCORD_ID:
        await ctx.send("No tienes permiso para usar este comando.")
        return

    user_balances[member.id] += amount
    await ctx.send(f"Añadidos {amount} a {member.name}. Nuevo saldo: {user_balances[member.id]}")

@bot.command()
async def remove_balance(ctx, member: discord.Member, amount: int):
    """Quita saldo a un usuario (solo admin)."""
    if ctx.author.id != YOUR_DISCORD_ID:
        await ctx.send("No tienes permiso para usar este comando.")
        return

    if user_balances[member.id] < amount:
        await ctx.send("El usuario no tiene suficiente saldo.")
        return

    user_balances[member.id] -= amount
    await ctx.send(f"Quitados {amount} a {member.name}. Nuevo saldo: {user_balances[member.id]}")

# --- TAREA EN SEGUNDO PLANO PARA SINCRONIZAR COMANDOS ---
@tasks.loop(seconds=SYNC_INTERVAL)
async def auto_sync():
    """Sincroniza los comandos slash automáticamente."""
    try:
        await bot.tree.sync()
        print("Comandos sincronizados automáticamente.")
    except Exception as e:
        print(f"Error al sincronizar comandos automáticamente: {e}")

# --- EVENTOS ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot conectado como: {bot.user}")
    bot.loop.create_task(check_payments())
    bot.loop.create_task(update_bot_presence())
    auto_sync.start()

@bot.event
async def on_member_join(member):
    """Envia un mensaje de bienvenida a los nuevos miembros."""
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        print(f"Canal de bienvenida no encontrado: {WELCOME_CHANNEL_ID}")
        return

    embed = discord.Embed(
        title=f"¡Bienvenido a {member.guild.name}!",
        description=f"¡Hola {member.mention}! Esperamos que disfrutes tu tiempo aquí.",
        color=DEFAULT_COLOR,
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url=member.avatar)  # Muestra el avatar del usuario
    embed.set_image(url="https://i.imgur.com/YxDPyAH.gif") # Imagen de fondo

    embed.set_footer(text=FOOTER_TEXT)

    await channel.send(embed=embed)

# --- DETECCIÓN DE FACTURAS LIGHTNING ---
@bot.event
async def on_message(message):
    """Detecta facturas Lightning en los mensajes."""
    if message.author == bot.user:
        return

    if message.content.startswith("lnbc"):
        print("Factura Lightning detectada. La confirmación automática está deshabilitada.")
        await message.channel.send("Factura Lightning detectada. La confirmación automática está deshabilitada.")

    await bot.process_commands(message)

class ConfirmPayment(discord.ui.View):
    def __init__(self, invoice, user_id):
        super().__init__(timeout=60)
        self.invoice = invoice
        self.user_id = user_id

    @discord.ui.button(label="Confirmar Pago", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirma el pago de la factura (solo admin)."""
        if interaction.user.id == YOUR_DISCORD_ID:
            headers = {'X-Api-Key': ADMIN_KEY}
            payload = {"out": True, "bolt11": self.invoice}
            try:
                response = await bot.loop.run_in_executor(None, lambda: requests.post(f"{LNBITS_URL}/api/v1/payments", headers=headers, json=payload, timeout=10))
                response.raise_for_status()
                data = response.json()
                if "payment_hash" in data:
                    embed = discord.Embed(
                        title="Pago Confirmado",
                        description=f"El pago de la factura ha sido confirmado correctamente.",
                        color=0x4CAF50,
                        timestamp
