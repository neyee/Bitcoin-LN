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
YOUR_DISCORD_ID = int(os.getenv("YOUR_DISCORD_ID", "0"))
DATA_FILE = "data.json"

# --- INICIALIZACIÓN DEL BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
user_balances = {}
payment_history = []

# --- INICIALIZACIÓN DE FLASK ---
app = Flask(__name__)

# --- FUNCIONES AUXILIARES ---
def generate_lightning_qr(lightning_invoice):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=8, border=4)
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
    except Exception as e:
        print(f"Error al obtener el precio de BTC: {e}")
        return None

async def check_payment_status(payment_hash):
    headers = {'X-Api-Key': INVOICE_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{LNBITS_URL}/api/v1/payments/{payment_hash}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return not data["pending"]
                else:
                    print(f"Error al obtener el estado del pago: {resp.status}")
                    return False
    except Exception as e:
        print(f"Error al conectar con LNbits: {e}")
        return False

async def get_invoice_details(invoice):
    headers = {'X-Api-Key': ADMIN_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{LNBITS_URL}/api/v1/payments/{invoice}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"amount": data["details"]["amount"]}
                else:
                    print(f"Error al obtener detalles de la factura: {resp.status}")
                    return None
    except Exception as e:
        print(f"Error al conectar con LNbits: {e}")
        return None

def load_data():
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
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(user_balances, f)
        print("Datos guardados en data.json")
    except Exception as e:
        print(f"Error al guardar los datos: {e}\n{traceback.format_exc()}")

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
    await bot.change_presence(activity=discord.Game(name="/help"))

# --- COMANDOS ---
@tree.command(name="tip", description="Da una propina a otro usuario")
@app_commands.describe(usuario="Usuario a quien dar propina", monto="Monto en sats", mensaje="Mensaje opcional")
async def dar_propina(interaction: discord.Interaction, usuario: discord.Member, monto: int, *, mensaje: str = "¡Aquí tienes tu propina!"):
    """Da una propina a otro usuario."""
    pagador_id = interaction.user.id
    receptor_id = usuario.id

    if pagador_id == receptor_id:
        embed = discord.Embed(
            title="❌ Error",
            description="¡No puedes darte propina a ti mismo!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto de la propina debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    if pagador_id not in user_balances or user_balances.get(pagador_id, 0) < monto:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes suficientes fondos para dar esta propina.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    # Transferir los fondos
    user_balances[pagador_id] -= monto
    if receptor_id not in user_balances:
        user_balances[receptor_id] = 0
    user_balances[receptor_id] += monto
    save_data()  # Guardar los datos después de la transacción

    embed = discord.Embed(
        title="🎁 ¡Propina Enviada!",
        description=f"**{interaction.user.mention}** ha dado una propina de **{monto} sats** a **{usuario.mention}**.",
        color=discord.Color.green()
    )
    embed.add_field(name="Mensaje", value=f"{mensaje}", inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

    print(f"Propina: {interaction.user.name} dio {monto} sats a {usuario.name}.")

@tree.command(name="bal", description="Muestra tu balance actual")
async def ver_mi_balance(interaction: discord.Interaction):
    """Muestra el balance del usuario."""
    user_id = interaction.user.id
    balance = user_balances.get(user_id, 0)
    embed = discord.Embed(
        title="💰 Tu Balance",
        description=f"Tu balance actual es de **{balance} sats**.",
        color=discord.Color.blue()
    )
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

@tree.command(name="send", description="Envia sats a algun usuario")
@app_commands.describe(usuario="Usuario a enviar sats", monto="Monto en sats")
async def send(interaction: discord.Interaction, usuario: discord.Member, monto: int):
    """Envia sats a algun usuario"""
    user_id = interaction.user.id
    receptor_id = usuario.id

    if user_id == receptor_id:
        embed = discord.Embed(
            title="❌ Error",
            description="¡No puedes enviarte cash a ti mismo!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto a enviar debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    if user_id not in user_balances or user_balances.get(user_id, 0) < monto:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes suficientes fondos para enviar cash.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    # Transferir los fondos
    user_balances[user_id] -= monto
    if receptor_id not in user_balances:
        user_balances[receptor_id] = 0
    user_balances[receptor_id] += monto
    save_data()  # Guardar los datos después de la transacción

    embed = discord.Embed(
        title="💸 Envío Exitoso",
        description=f"Enviaste **{monto} sats** a **{usuario.mention}**.",
        color=discord.Color.green()
    )
    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

    print(f"Envio: {interaction.user.name} dio {monto} sats a {usuario.name}.")

@tree.command(name="depositar", description = "Genera una factura lightning para depositar")
@app_commands.describe(monto = "Ingresa el monto en Sats")
async def depositar(interaction: discord.Interaction, monto: int):
    """Genera una factura Lightning para depositar fondos."""
    user_id = interaction.user.id
    user_name = interaction.user.name

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto del depósito debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    try:
        memo = f"Depósito de {user_name}"
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
            await interaction.response.send_message(embed=embed)
            return

        qr_code = generate_lightning_qr(invoice)
        file = discord.File(qr_code, filename="qr_invoice.png")

        embed = discord.Embed(
            title="⚡ Factura Lightning para Depósito",
            description=f"Escanea el código QR o copia la factura para depositar **{monto} sats**.",
            color=discord.Color.orange()
        )
        embed.set_image(url="attachment://qr_invoice.png")
        embed.set_footer(text=FOOTER_TEXT)

        await interaction.response.send_message(embed=embed, file=file)

        await interaction.channel.send(f"```{invoice}```")

        pago_status = await check_payment_status(payment_hash)

        if pago_status:
            if user_id not in user_balances:
                user_balances[user_id] = 0
            user_balances[user_id] += monto
            save_data()

            embed = discord.Embed(
                title="✅ Depósito Exitoso",
                description=f"¡Depósito de **{monto} sats** realizado correctamente!",
                color=discord.Color.green()
            )
            embed.set_footer(text=FOOTER_TEXT)
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Error",
                description="El pago no se ha recibido. Inténtalo de nuevo.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"Error en el comando depositar: {e}\n{traceback.format_exc()}")
        await interaction.response.send_message("Error interno al generar la factura.")

@tree.command(name="retirar", description="Retira fondos a una factura Lightning")
@app_commands.describe(factura="Factura Lightning a la que retirar")
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos (solo admin)."""
    if interaction.user.id != YOUR_DISCORD_ID:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes permiso para usar este comando.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        # Obtener el monto de la factura
        invoice_details = await get_invoice_details(factura)
        if invoice_details is None:
            embed = discord.Embed(
                title="❌ Error",
                description="No se pudieron obtener los detalles de la factura. Verifica que sea válida.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        monto = invoice_details["amount"] / 1000
        user_id = interaction.user.id
        balance = user_balances.get(user_id, 0)

        if monto > balance:
            embed = discord.Embed(
                title="❌ Error",
                description=f"No tienes suficientes fondos para retirar. Tu balance es de {balance} sats.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        headers = {'X-Api-Key': ADMIN_KEY}
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json={"out": True, "bolt11": factura}, headers=headers)
        data = response.json()

        if "payment_hash" not in data:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Error al procesar el pago: {data.get('detail', 'Desconocido')}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Restar saldo al usuario
        user_balances[user_id] -= monto
        save_data()

        embed = discord.Embed(
            title="✅ Retiro Exitoso",
            description=f"Retiro de **{monto} sats** procesado correctamente.",
            color=0x4CAF50,  # Verde
            timestamp=datetime.now()
        )
        embed.add_field(name="Hash del Pago", value=f"```{data['payment_hash']}```", inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"Error en retirar_fondos: {e}")
        embed = discord.Embed(
            title="❌ Error",
            description="Error interno al procesar el retiro. Consulta los logs para más detalles.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="addcash", description = "[Admin] agrega saldo a un usuario")
@app_commands.describe(usuario = "A que usuario se va añadir el cash",monto = "Ingresa el monto en sats")
async def agregar_fondos(interaction: discord.Interaction, usuario: discord.Member, monto: int):
    """Agrega fondos a un usuario (solo para administradores)."""
    if interaction.user.id != YOUR_DISCORD_ID:
        embed = discord.Embed(
            title="❌ Error",
            description="No tienes permiso para usar este comando.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral = True)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto a agregar debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral = True)
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
        await interaction.response.send_message(embed=embed, ephemeral = True)

        print(f"Admin: Se agregaron {monto} sats a {usuario.name}.")

    except Exception as e:
        print(f"Error en el comando agregar_fondos: {e}\n{traceback.format_exc()}")
        await interaction.response.send_message("Error interno al agregar los fondos.")

@tree.command(name="tip", description="Da propina lightning con sats")
@app_commands.describe(usuario="A quien le vas a dar la propina",monto = "Cuanto en sast le vas a dar de popina")
async def tip(interaction: discord.Interaction, usuario: discord.Member, monto: int):
    """Da propina a algun usuario con sats"""
    user_id = interaction.user.id
    receptor_id = usuario.id

    if user_id == receptor_id:
        embed = discord.Embed(
            title="❌ Error",
            description="¡No puedes dar propina a ti mismo!",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral = True)
        return

    if monto <= 0:
        embed = discord.Embed(
            title="❌ Error",
            description="El monto a agregar debe ser mayor que cero.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral = True)
        return

    try:
        receptor_id = usuario.id
        if receptor_id not in user_balances:
            user_balances[receptor_id] = 0
        user_balances[receptor_id] += monto
        save_data()  # Guardar los datos después de agregar los fondos

        embed = discord.Embed(
            title="💸💸 has dado una propina",
            description=f"Has dado **{monto} sats** a  **{usuario.mention}**.",
            color=discord.Color.Green()
        )
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

        print(f"Admin: Se agregaron {monto} sats a {usuario.name}.")

    except Exception as e:
        print(f"Error en el comando agregar_fondos: {e}\n{traceback.format_exc()}")
        await interaction.response.send_message("Error interno al agregar los fondos.")

@tree.command(name = "help", description = "Mostrando todos los comandos")
async def ayuda(interaction: discord.Interaction):
    """Muestra la lista de comandos disponibles."""
    embed = discord.Embed(
        title="Comandos Disponibles",
        description="Aquí tienes una lista de los comandos que puedes usar:",
        color=discord.Color.blue()
    )
    embed.add_field(name="/bal", value="Muestra tu balance actual.", inline=False)
    embed.add_field(name="/tip @usuario monto [mensaje]", value="Da una propina a otro usuario.", inline=False)
    embed.add_field(name="/depositar monto", value="Genera una factura para depositar fondos.", inline=False)
    embed.add_field(name="/retirar factura", value="Retira fondos a una factura Lightning.", inline=False)
    if interaction.user.id == YOUR_DISCORD_ID:
        embed.add_field(name="/addcash @usuario monto", value="[Admin] Agrega fondos a un usuario.", inline=False)

    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed, ephemeral = True)

# --- COMANDOS DEL ADMINISTRADOR ---
@bot.command()
async def sync(ctx):
    """Sincroniza los comandos slash (solo admin)."""
    if ctx.author.id == YOUR_DISCORD_ID:
        await bot.tree.sync()
        await ctx.send("Comandos sincronizados correctamente.")
    else:
        await ctx.send("No tienes permiso para usar este comando.")

# --- DETECCIÓN DE FACTURAS LIGHTNING ---
@bot.event
async def on_message(message):
    """Detecta facturas Lightning en los mensajes."""
    if message.author == bot.user:
        return

    if message.content.startswith("lnbc"):
        embed = discord.Embed(
            title="Confirmar Pago",
            description=f"¿Deseas confirmar el pago de esta factura:\n```{message.content}```?",
            color=0x4CAF50,  # Verde
            timestamp=datetime.now()
        )
        embed.set_footer(text=FOOTER_TEXT)

        # Añadir botones de confirmación
        view = ConfirmPayment(message.content, message.author.id)
        await message.channel.send(embed=embed, view=view)

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
                response = await bot.loop.run_in_executor(None, lambda: requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers, json=payload, timeout=10))
                response.raise_for_status()  # Lanza una excepción para errores HTTP
                data = response.json()
                if "payment_hash" in data:
                    embed = discord.Embed(
                        title="Pago Confirmado",
                        description=f"El pago de la factura ha sido confirmado correctamente.",
                        color=0x4CAF50,  # Verde
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="Hash del Pago", value=f"```{data['payment_hash']}```", inline=False)
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(f"Error al confirmar el pago: {data.get('detail', 'Error Desconocido')}", ephemeral=True)
            except requests.exceptions.RequestException as e:
                print(f"Error al confirmar el pago: {e}")
                await interaction.response.send_message(f"Error al confirmar el pago: {e}", ephemeral=True)
        else:
            await interaction.response.send_message("Solo el administrador puede confirmar este pago.", ephemeral=True)

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
 Ahora si necesito que implementes estos dos comando y dime si no hay problemas.

 * Lo mensajes del bot los necesito en embet
 * Que el comamdo help de una buena ayuda no se entiende 
 * El flask sigue sin iniciar
 * Son comados con slash , todo bien hecho con descripción en español bien elaborado bonito y agradable.
 * No se actualizan los comandos
