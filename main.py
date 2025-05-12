import os
import discord
import requests
import qrcode
import asyncio
import aiohttp
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from flask import Flask
import threading
import json

# --- CONFIGURACIÓN ---
TOKEN = os.getenv("DISCORD_TOKEN")
LNBITS_URL = os.getenv("LNBITS_URL", "https://legend.lnbits.com").rstrip('/')
INVOICE_KEY = os.getenv("INVOICE_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
FOOTER_TEXT = os.getenv("FOOTER_TEXT", "⚡ Lightning Wallet Bot")
YOUR_DISCORD_ID = 865597179145486366
DATA_FILE = "data.json"  # Nombre del archivo para guardar los datos

# --- INICIALIZACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
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
    except:
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
        print(f"Error al cargar los datos: {e}. Se inicializarán los saldos.")
        user_balances = {}


def save_data():
    """Guarda los datos en el archivo JSON."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(user_balances, f)
        print("Datos guardados en data.json")
    except Exception as e:
        print(f"Error al guardar los datos: {e}")


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
    """Actualiza la presencia del bot con el precio de BTC."""
    while True:
        btc_price = await get_btc_price()
        if btc_price:
            await bot.change_presence(activity=discord.Game(name=f"BTC: ${btc_price:,.2f}"))
        await asyncio.sleep(60)


# --- COMANDOS ---
@bot.command(name="tip")
async def dar_propina(ctx, usuario: discord.Member, monto: int, *, mensaje: str = "¡Aquí tienes tu propina!"):
    """Da una propina a otro usuario."""
    pagador_id = ctx.author.id
    receptor_id = usuario.id

    if pagador_id == receptor_id:
        await ctx.send("No puedes darte propina a ti mismo.")
        return

    if monto <= 0:
        await ctx.send("El monto de la propina debe ser mayor que cero.")
        return

    if pagador_id not in user_balances or user_balances.get(pagador_id, 0) < monto:
        await ctx.send("No tienes suficientes fondos para dar esta propina.")
        return

    # Transferir los fondos
    user_balances[pagador_id] -= monto
    if receptor_id not in user_balances:
        user_balances[receptor_id] = 0
    user_balances[receptor_id] += monto

    await ctx.send(f"{ctx.author.mention} ha dado una propina de {monto} sats a {usuario.mention}. {mensaje}")

    print(f"Propina: {ctx.author.name} dio {monto} sats a {usuario.name}.")
    save_data()  # Guardar los datos después de la transacción


@bot.command(name="mibalance")
async def ver_mi_balance(ctx):
    """Muestra el balance del usuario."""
    user_id = ctx.author.id
    balance = user_balances.get(user_id, 0)
    await ctx.send(f"Tu balance actual es de {balance} sats.")


@bot.command(name="depositar")
async def depositar(ctx, monto: int):
    """Genera una factura Lightning para depositar fondos."""
    user_id = ctx.author.id

    if monto <= 0:
        await ctx.send("El monto del depósito debe ser mayor que cero.")
        return

    try:
        payload = {"out": False, "amount": monto, "memo": f"Depósito de {ctx.author.name}", "unit": "sat"}
        headers = {'X-Api-Key': INVOICE_KEY}
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers)
        data = response.json()
        invoice = data.get("bolt11")
        payment_hash = data.get("payment_hash")

        if not invoice:
            await ctx.send("Error al generar la factura. Inténtalo de nuevo.")
            return

        qr = generate_lightning_qr(f"lightning:{invoice}")
        file = discord.File(qr, filename="invoice_qr.png")
        await ctx.send(f"Deposita {monto} sats a la siguiente factura:\n```{invoice}```", file=file) #Sin embed

        # Esperar el pago de la factura (REEMPLAZAR CON VERIFICACIÓN REAL)
        # await asyncio.sleep(60)
        pago_status = await check_payment_status(payment_hash)  # Verificar el estado del pago con la API de LNbits

        if pago_status:
            # Acreditar el saldo
            if user_id not in user_balances:
                user_balances[user_id] = 0
            user_balances[user_id] += monto
            await ctx.send(
                f"¡Depósito de {monto} sats realizado correctamente! Tu nuevo balance es de {user_balances[user_id]} sats.")
            save_data()  # Guardar los datos después del depósito
        else:
            await ctx.send("El pago no se ha recibido. Inténtalo de nuevo.")

    except Exception as e:
        print(f"Error en el comando depositar: {e}")
        await ctx.send("Error interno al generar la factura.")


@bot.command(name="retirar")
async def retirar(ctx, factura: str):
    """Retira fondos a una factura Lightning."""
    user_id = ctx.author.id

    if user_id not in user_balances:
        await ctx.send("No tienes fondos disponibles para retirar.")
        return

    try:
        invoice_details = await get_invoice_details(factura)
        monto = invoice_details["amount"] / 1000

        if user_balances.get(user_id, 0) < monto: #Usar get() con valor por defecto
            await ctx.send("No tienes suficientes fondos para retirar este monto.")
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
        await ctx.send(f"Retiro de {monto} sats procesado correctamente. Tu nuevo balance es de {user_balances[user_id]} sats.")  # Sin Embed
        print(f"Retiro: {ctx.author.name} retiró {monto} sats.")
        save_data()  # Guardar los datos después del retiro

    except Exception as e:
        print(f"Error en el comando retirar: {e}")
        await ctx.send("Error interno al procesar el retiro.")

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
                        # Extraer el nombre del usuario del memo
                        if "Depósito de" in user_memo:
                            user_name = user_memo.replace("Depósito de ", "")
                            user = discord.utils.get(bot.users, name=user_name)  # Obtener el objeto User
                            if user:
                                user_id = user.id
                                if user_id not in user_balances:
                                    user_balances[user_id] = 0
                                user_balances[user_id] += monto
                                print(f"Acreditados {monto} sats a {user_name} (ID: {user_id}).")
                                save_data() # Guardar tras acreditación automatica
                            else:
                                print(f"No se pudo encontrar el usuario {user_name}.")

        except Exception as e:
            print(f"Error verificando pagos: {e}")

        await asyncio.sleep(25)

# --- EVENTOS ---
@bot.event
async def on_ready():
    load_data() #Cargar datos al iniciar el bot
    await bot.tree.sync()
    print(f"✅ Bot conectado como: {bot.user}")
    bot.loop.create_task(check_payments())
    bot.loop.create_task(update_bot_presence())


# --- INICIAR FLASK ---
app = Flask(__name__)

@app.route("/")
def hello():
    return "Lightning Wallet Bot Backend is Running!"

def run_flask():
    app.run(host="0.0.0.0", port=5000)

# --- INICIAR EL BOT ---
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    bot.run(TOKEN)
