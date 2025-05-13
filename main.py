import os
import discord
import requests
import qrcode
import asyncio
import aiohttp
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord.ext.commands import has_permissions, MissingPermissions  # Para permisos
from flask import Flask
import threading
import json
import traceback  # Para obtener información detallada de los errores
import random  # Para la ruleta

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("DISCORD_TOKEN")
LNBITS_URL = os.getenv("LNBITS_URL", "https://legend.lnbits.com").rstrip('/')
INVOICE_KEY = os.getenv("INVOICE_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
FOOTER_TEXT = os.getenv("FOOTER_TEXT", "⚡ Lightning Wallet Bot")
YOUR_DISCORD_ID = int(os.getenv("YOUR_DISCORD_ID", "0")) # ID del Administrador
DATA_FILE = "data.json"  # Nombre del archivo para guardar los datos
ROULETTE_MIN_BET = 10  # Apuesta mínima para la ruleta
ROULETTE_MAX_BET = 100 # Apuesta máxima

# --- INICIALIZACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Necesario para obtener información de los miembros
bot = commands.Bot(command_prefix="!", intents=intents)
user_balances = {}  # Diccionario para almacenar los saldos de los usuarios
payment_history = []

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
            async with session.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd") as resp:
                data = await resp.json()
                return data["bitcoin"]["usd"]
    except Exception as e:
        print(f"Error al obtener el precio de BTC: {e}")
        return None


async def check_payment_status(payment_hash):
    """Verifica el estado del pago usando la API de LNbits."""
    headers = {'X-Api-Key': INVOICE_KEY}  # Usar Invoice Key para consultar el estado
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{LNBITS_URL}/api/v1/payments/{payment_hash}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return not data["pending"]  # Devuelve True si el pago NO está pendiente (completado)
                else:
                    print(f"Error al obtener el estado del pago: {resp.status}")
                    return False
    except Exception as e:
        print(f"Error al conectar con LNbits: {e}")
        return False


async def get_invoice_details(invoice):
    """Obtiene los detalles de la factura (incluyendo el monto) desde LNbits."""
    headers = {'X-Api-Key': ADMIN_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{LNBITS_URL}/api/v1/payments/{invoice}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"amount": data["details"]["amount"]}  # Devuelvo solo el monto
                else:
                    print(f"Error al obtener detalles de la factura: {resp.status}")
                    return None
    except Exception as e:
        print(f"Error al conectar con LNbits: {e}")
        return None


def load_data():
    """Carga los datos desde el archivo JSON."""
    global user_balances
    try:
        with open(DATA_FILE, "r") as f:
            user_balances = json.load(f)
        print("Datos cargados desde data.json")
    except FileNotFoundError:
        print("Archivo data.json no encontrado. Se creará uno nuevo.")
        user_balances = {}
    except Exception as e:
        print(f"Error al cargar los datos: {e}\n{traceback.format_exc()}\nSe inicializarán los saldos.")
        user_balances = {}


def save_data():
    """Guarda los datos en el archivo JSON."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(user_balances, f)
        print("Datos guardados en data.json")
    except Exception as e:
        print(f"Error al guardar los datos: {e}\n{traceback.format_exc()}")


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
        color=0x4CAF50,  # Verde
        timestamp=datetime.now()
    )
    embed.add_field(name="Descripción", value=f"```{user_memo}```", inline=False)
    embed.set_footer(text=FOOTER_TEXT)

    admin = await bot.fetch_user(YOUR_DISCORD_ID)
    if admin:
        await admin.send(embed=embed)

    payment_history.append({"memo": user_memo, "sats": sats, "usd": usd})


# --- PRESENCIA DEL BOT ---
async def update_bot_presence():
    """Actualiza la presencia del bot con un mensaje de ayuda."""
    await bot.change_presence(activity=discord.Game(name="!help"))


# --- COMANDOS ---
@bot.command(name="tip")
async def dar_propina(ctx, usuario: discord.Member, monto: int, *, mensaje: str = "¡Aquí tienes tu propina!"):
    """Da una propina a otro usuario."""
    pagador_id = ctx.author.id
    receptor_id = usuario.id

    if pagador_id == receptor_id:
        embed = discord.Embed(
            title="❌ Error",
            description="¡No puedes darte propina a ti mismo!",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto de la propina debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if pagador_id not in user_balances or user_balances.get(pagador_id, 0) < monto:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes suficientes fondos para dar esta propina.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # Transferir los fondos
    user_balances[pagador_id] -= monto
    if receptor_id not in user_balances:
        user_balances[receptor_id] = 0
    user_balances[receptor_id] += monto
    save_data()  # Guardar los datos después de la transacción

    embed = discord.Embed(
        title="🎁 ¡Propina Enviada!",
        description=f"**{ctx.author.mention}** ha dado una propina de **{monto} sats** a **{usuario.mention}**.",
        color=discord.Color.green()
    )
    embed.add_field(name="Mensaje", value=mensaje, inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    await ctx.send(embed=embed)

    print(f"Propina: {ctx.author.name} dio {monto} sats a {usuario.name}.")

@bot.command(name="bal")
async def ver_mi_balance(ctx):
    """Muestra el balance del usuario."""
    user_id = ctx.author.id
    balance = user_balances.get(user_id, 0)
    embed = discord.Embed(
        title="💰 Tu Balance",
        description=f"Tu balance actual es de **{balance} sats**.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=FOOTER_TEXT)
    await ctx.send(embed=embed)

@bot.command(name="send")
async def enviar_fondos(ctx, usuario: discord.Member, monto: int):
    """Envía fondos a otro usuario."""
    pagador_id = ctx.author.id
    receptor_id = usuario.id

    if pagador_id == receptor_id:
        embed = discord.Embed(
            title="❌ Error",
            description="No puedes enviarte fondos a ti mismo.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto debe ser mayor a cero.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if pagador_id not in user_balances or user_balances.get(pagador_id, 0) < monto:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes fondos suficientes.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # Transferir los fondos
    user_balances[pagador_id] -= monto
    if receptor_id not in user_balances:
        user_balances[receptor_id] = 0
    user_balances[receptor_id] += monto
    save_data()  # Guardar los datos después de la transacción

    embed = discord.Embed(
        title="💸 Transferencia Exitosa",
        description=f"Has enviado **{monto} sats** a **{usuario.mention}**.",
        color=discord.Color.green()
    )
    embed.set_footer(text=FOOTER_TEXT)
    await ctx.send(embed=embed)

    print(f"Transferencia: {ctx.author.name} envió {monto} sats a {usuario.name}.")

@bot.command(name="depositar")
async def depositar(ctx, monto: int):
    """Genera una factura Lightning para depositar fondos."""
    user_id = ctx.author.id
    user_name = ctx.author.name  # Obtener el nombre de usuario

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto del depósito debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        memo = f"Depósito de {user_name}"  # Incluir el nombre de usuario
        payload = {"out": False, "amount": monto, "memo": memo, "unit": "sat"}
        headers = {'X-Api-Key': INVOICE_KEY}
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers)
        data = response.json()
        invoice = data.get("bolt11")
        payment_hash = data.get("payment_hash")

        if not invoice:
             embed = discord.Embed(
                title="❌ Error",
                description="Error al generar la factura. Inténtalo de nuevo.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        qr_code = generate_lightning_qr(invoice)
        file = discord.File(qr_code, filename="qr_invoice.png")

        embed = discord.Embed(
            title="⚡ Factura Lightning para Depósito",
            description=f"Escanea el código QR o copia la factura para depositar **{monto} sats**.",
            color=discord.Color.orange()  # Color naranja para la factura
        )
        embed.set_image(url="attachment://qr_invoice.png")  # Añadir imagen
        embed.set_footer(text=FOOTER_TEXT)  # Añadir Footer

        await ctx.send(embed=embed, file=file)

        await ctx.send(f"```{invoice}```")  # Enviar la factura sin formato

        # Verificar estado del pago
        pago_status = await check_payment_status(payment_hash)

        if pago_status:
            # Acreditar el saldo
            if user_id not in user_balances:
                user_balances[user_id] = 0
            user_balances[user_id] += monto
            save_data()  # Guardar los datos después del depósito
            embed = discord.Embed(
                title="✅ Depósito Exitoso",
                description=f"¡Depósito de **{monto} sats** realizado correctamente!",
                color=discord.Color.green()
            )
            embed.set_footer(text=FOOTER_TEXT)
            await ctx.send(embed=embed)

        else:
             embed = discord.Embed(
                title="❌ Error",
                description="El pago no se ha recibido. Inténtalo de nuevo.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)

    except Exception as e:
        print(f"Error en el comando depositar: {e}\n{traceback.format_exc()}")
        await ctx.send("Error interno al generar la factura.")

@bot.command(name="retirar")
async def retirar(ctx, factura: str):
    """Retira fondos a una factura Lightning."""
    user_id = ctx.author.id

    if user_id not in user_balances:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes fondos disponibles para retirar.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        invoice_details = await get_invoice_details(factura)
        monto = invoice_details["amount"] / 1000

        if user_balances.get(user_id, 0) < monto:  # Usar get() con valor por defecto
            embed = discord.Embed(
                title="❌ Error",
                description="No tienes suficientes fondos para retirar este monto.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        headers = {'X-Api-Key': ADMIN_KEY}
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json={"out": True, "bolt11": factura},
                                 headers=headers)
        data = response.json()

        if "payment_hash" not in data:
            await ctx.send(f"Error al procesar el retiro: {data.get('detail', 'Desconocido')}")
            return

        # Restar saldo al usuario
        user_balances[user_id] -= monto
        save_data()  # Guardar los datos después del retiro

        embed = discord.Embed(
            title="💨 Retiro Exitoso",
            description=f"Retiro de **{monto} sats** procesado correctamente.",
            color=discord.Color.green()
        )
        embed.add_field(name="Hash del Pago", value=f"```{data['payment_hash']}```", inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        await ctx.send(embed=embed)

        print(f"Retiro: {ctx.author.name} retiró {monto} sats.")

    except Exception as e:
        print(f"Error en el comando retirar: {e}\n{traceback.format_exc()}")
        await ctx.send("Error interno al procesar el retiro.")

@bot.command(name="airdrop")
@has_permissions(administrator=True)  # Restringir el comando a administradores
async def airdrop(ctx, monto: int, *usuarios: discord.Member):
    """Envía un airdrop de sats a varios usuarios."""
    if ctx.author.id != YOUR_DISCORD_ID: #Proteccion extra
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes permiso para usar este comando.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto del airdrop debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if not usuarios:
        embed = discord.Embed(
            title="❌ Error",
            description="Debes mencionar al menos un usuario para el airdrop.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        for usuario in usuarios:
            receptor_id = usuario.id
            if receptor_id not in user_balances:
                user_balances[receptor_id] = 0
            user_balances[receptor_id] += monto
            print(f"Airdrop: Se enviaron {monto} sats a {usuario.name}.")
            embed = discord.Embed(
                title="✨ Airdrop Recibido",
                description=f"Has recibido **{monto} sats** de airdrop.",
                color=discord.Color.purple()
            )
            embed.set_footer(text=FOOTER_TEXT)
            await usuario.send(embed=embed)

        save_data()  # Guardar los datos después del airdrop
        embed = discord.Embed(
            title="✅ Airdrop Exitoso",
            description=f"Airdrop de **{monto} sats** enviado a **{len(usuarios)}** usuarios.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    except Exception as e:
        print(f"Error en el comando airdrop: {e}\n{traceback.format_exc()}")
        await ctx.send("Error interno al procesar el airdrop.")

@bot.command(name="addcash")
@has_permissions(administrator=True)  # Restringir el comando a administradores
async def agregar_fondos(ctx, usuario: discord.Member, monto: int):
    """Agrega fondos a un usuario (solo para administradores)."""
    if ctx.author.id != YOUR_DISCORD_ID: #Proteccion extra
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes permiso para usar este comando.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto a agregar debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    try:
        receptor_id = usuario.id
        if receptor_id not in user_balances:
            user_balances[receptor_id] = 0
        user_balances[receptor_id] += monto
        save_data()  # Guardar los datos después de agregar los fondos

        embed = discord.Embed(
            title="💰 Fondos Agregados",
            description=f"Se han agregado **{monto} sats** a **{usuario.mention}**.",
            color=discord.Color.green()
        )
        embed.set_footer(text=FOOTER_TEXT)
        await ctx.send(embed=embed)

        print(f"Admin: Se agregaron {monto} sats a {usuario.name}.")

    except Exception as e:
        print(f"Error en el comando agregar_fondos: {e}\n{traceback.format_exc()}")
        await ctx.send("Error interno al agregar los fondos.")

@bot.command(name="help")
async def ayuda(ctx):
    """Muestra la lista de comandos disponibles."""
    embed = discord.Embed(
        title="Comandos Disponibles",
        description="Aquí tienes una lista de los comandos que puedes usar:",
        color=discord.Color.blue()
    )
    embed.add_field(name="!bal", value="Muestra tu balance actual.", inline=True)
    embed.add_field(name="!send @usuario monto", value="Envía fondos a otro usuario.", inline=True)
    embed.add_field(name="!tip @usuario monto [mensaje]", value="Da una propina a otro usuario.", inline=True)
    embed.add_field(name="!depositar monto", value="Genera una factura para depositar fondos.", inline=False)
    embed.add_field(name="!retirar factura", value="Retira fondos a una factura Lightning.", inline=False)
    if ctx.author.id == YOUR_DISCORD_ID:
        embed.add_field(name="!addcash @usuario monto", value="[Admin] Agrega fondos a un usuario.", inline=False)
        embed.add_field(name="!airdrop monto @usuario1 @usuario2 ...", value="[Admin] Envía un airdrop a varios usuarios.", inline=False)

    embed.set_footer(text=FOOTER_TEXT)
    await ctx.send(embed=embed)

# --- TAREAS EN SEGUNDO PLANO ---
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
                        user_memo = payment.get("memo", "Sin descripción")
                        monto = payment["amount"] / 1000
    
