import os
import discord
import requests
import qrcode
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from flask import Flask, render_template_string
import json  # Importa json

# Configuración desde variables de entorno
TOKEN = os.getenv('DISCORD_TOKEN')
LNBITS_URL = os.getenv('LNBITS_URL', 'https://demo.lnbits.com').rstrip('/')
INVOICE_KEY = os.getenv('INVOICE_KEY')
ADMIN_KEY = os.getenv('ADMIN_KEY')
FOOTER_TEXT = os.getenv('FOOTER_TEXT', 'Sistema de Créditos Discord')

# AÑADIDO SOLO ESTO (tu ID)
YOUR_DISCORD_ID = 865597179145486366

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- CONFIGURACIÓN DEL ARCHIVO JSON ---
DATABASE_PATH = 'data/cuentas.json'

def cargar_cuentas():
    """Carga los datos de las cuentas desde el archivo JSON."""
    try:
        with open(DATABASE_PATH, 'r') as f:
            cuentas = json.load(f)
    except FileNotFoundError:
        cuentas = {}
    except json.JSONDecodeError:
        print("Error al decodificar el archivo JSON. Usando datos vacíos.")
        cuentas = {}
    return cuentas

def guardar_cuentas(cuentas):
    """Guarda los datos de las cuentas en el archivo JSON."""
    with open(DATABASE_PATH, 'w') as f:
        json.dump(cuentas, f, indent=4)

# --- RESTO DEL CÓDIGO ORIGINAL SIN CAMBIOS ---
def generate_lightning_qr(lightning_invoice):
    """Genera un código QR para una factura Lightning"""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(lightning_invoice)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"Error generando QR: {e}")
        return None

async def get_or_create_lnbits_wallet(user_id: str):
    """Obtiene la billetera LNbits de un usuario. Si no existe, la crea."""
    # (Esta función no cambia, sigue interactuando con la API de LNbits)
    lnbits_wallet_id = obtener_lnbits_wallet_id(user_id)
    if lnbits_wallet_id:
        return lnbits_wallet_id  # Ya existe la billetera

    headers = {
        'X-Api-Key': ADMIN_KEY,
        'Content-type': 'application/json'
    }
    try:
        payload = {
            "wallet_name": str(user_id)  # Usar el ID de Discord como nombre de la billetera
        }
        response = requests.post(
            f"{LNBITS_URL}/api/v1/wallets",
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        new_wallet = response.json()
        print(f"Billetera LNbits creada para el usuario {user_id}: {new_wallet}")
        lnbits_wallet_id = new_wallet['id']
        actualizar_lnbits_wallet_id(user_id, lnbits_wallet_id) #Guarda el wallet id en la base de datos
        return lnbits_wallet_id

    except requests.exceptions.RequestException as e:
        print(f"Error al crear la billetera LNbits: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error al analizar la respuesta de la API: {e}")
        return None
    except Exception as e:
        print(f"Error inesperado: {e}")
        return None

async def add_funds_to_lnbits_wallet(wallet_id: str, amount: int):
    """Añade fondos a una billetera LNbits."""
    headers = {
        'X-Api-Key': ADMIN_KEY,
        'Content-type': 'application/json'
    }
    payload = {
        "out": False,
        "amount": amount,
        "memo": f"Transferencia desde la cuenta virtual",
        "unit": "sat",
    }
    try:
        response = requests.post(
            f"{LNBITS_URL}/api/v1/payments",
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        payment_data = response.json()
        if 'payment_hash' in payment_data:
          return True
        else:
          print(f"Error al agregar fondos a la billetera LNbits: {payment_data}")
          return False

    except requests.exceptions.RequestException as e:
        print(f"Error al agregar fondos a la billetera LNbits: {e}")
        return False

# --- COMANDOS NUEVOS AÑADIDOS ---

@bot.tree.command(name="crear_cuenta", description="Crea una cuenta en nuestro sistema.")
async def crear_cuenta(interaction: discord.Interaction):
    """Crea una cuenta en el sistema interno."""
    user_id = str(interaction.user.id)
    cuentas = cargar_cuentas()

    if user_id in cuentas:
        await interaction.response.send_message("Ya tienes una cuenta creada en nuestro sistema.", ephemeral=True)
    else:
        # Crear la cuenta en el diccionario (balance inicial = 0)
        cuentas[user_id] = {"balance": 0, "lnbits_wallet_id": None}
        guardar_cuentas(cuentas)
        await interaction.response.send_message("Cuenta creada exitosamente en nuestro sistema.", ephemeral=True)

@bot.tree.command(name="addcash", description="Añade créditos a la cuenta de un usuario (solo admin)")
@app_commands.describe(usuario="Usuario al que añadir créditos", monto="Cantidad de créditos")
async def addcash(interaction: discord.Interaction, usuario: discord.Member, monto: int):
    """Añade créditos a la cuenta de un usuario (solo admin)."""
    if interaction.user.id != YOUR_DISCORD_ID:
        await interaction.response.send_message("Solo el administrador puede usar este comando.", ephemeral=True)
        return

    user_id = str(usuario.id)
    cuentas = cargar_cuentas()

    if user_id not in cuentas:
        await interaction.response.send_message(f"El usuario {usuario.mention} no tiene una cuenta creada. Usa /crear_cuenta.", ephemeral=True)
        return

    # Actualizar el balance en el diccionario
    cuentas[user_id]["balance"] += monto
    guardar_cuentas(cuentas)
    await interaction.response.send_message(f"Se han añadido {monto} créditos a la cuenta de {usuario.mention}.", ephemeral=False)


@bot.tree.command(name="tip", description="Da propina a otro usuario")
@app_commands.describe(usuario="Usuario al que dar créditos", monto="Cantidad de créditos")
async def tip(interaction: discord.Interaction, usuario: discord.Member, monto: int):
    """Da propina a otro usuario."""
    sender_id = str(interaction.user.id)
    receiver_id = str(usuario.id)

    if sender_id == receiver_id:
        await interaction.response.send_message("¡No puedes darte propina a ti mismo!", ephemeral=True)
        return

    if monto <= 0:
        await interaction.response.send_message("El monto debe ser mayor que cero.", ephemeral=True)
        return

    cuentas = cargar_cuentas()

    if sender_id not in cuentas or receiver_id not in cuentas:
        await interaction.response.send_message("Uno de los usuarios no tiene una cuenta creada. Usa /crear_cuenta.", ephemeral=True)
        return

    if cuentas[sender_id]["balance"] < monto:
        await interaction.response.send_message("No tienes suficientes créditos para dar propina.", ephemeral=True)
        return

    # Actualizar los balances en el diccionario
    cuentas[sender_id]["balance"] -= monto
    cuentas[receiver_id]["balance"] += monto
    guardar_cuentas(cuentas)
    await interaction.response.send_message(f"{interaction.user.mention} ha dado {monto} créditos a {usuario.mention}.", ephemeral=False)


# --- RESTO DE COMANDOS ORIGINALES SIN MODIFICAR ---
@bot.tree.command(name="factura", description="Genera una factura Lightning con QR")
@app_commands.describe(
    monto="Cantidad en satoshis (mínimo 10)",  # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
    descripcion="Concepto del pago (opcional)"
)
async def generar_factura(interaction: discord.Interaction, monto: int, descripcion: str = "Factura generada desde Discord"):
    """Genera una factura Lightning con QR"""
    try:
        if monto < 10:
            await interaction.response.send_message("🔶 El monto mínimo es 10 satoshis", ephemeral=True)  # OJO: ESTO NO SE CAMBIA
            return

        headers = {
            'X-Api-Key': INVOICE_KEY,
            'Content-type': 'application/json'
        }
        payload = {
            "out": False,
            "amount": monto,
            "memo": descripcion[:200],
            "unit": "sat"  # OJO: ESTO NO SE CAMBIA
        }

        response = requests.post(
            f"{LNBITS_URL}/api/v1/payments",
            headers=headers,
            timeout=10
        )

        if response.status_code != 201:
            error = response.json().get('detail', 'Error desconocido')
            await interaction.response.send_message(f"🔴 Error al crear factura: {error}", ephemeral=True)
            return

        invoice_data = response.json()
        if 'bolt11' not in invoice_data:
            await interaction.response.send_message("🔴 La factura generada no es válida", ephemeral=True)
            return

        invoice = invoice_data['bolt11']
        qr_buffer = generate_lightning_qr(f"lightning:{invoice}")

        if not qr_buffer:
            await interaction.response.send_message(
                "⚠️ Factura generada pero no se pudo crear el QR\n"
                f"Puedes pagar con: ```{invoice}```",
                ephemeral=False
            )
            return

        embed = discord.Embed(
            title="📄 Factura Lightning",
            description=f"**{monto:,} satoshis**\n💡 {descripcion}",  # OJO: ESTO NO SE CAMBIA
            color=0x9932CC,
            timestamp=datetime.now()
        )

        embed.add_field(
            name="🔍 Código BOLT11",
            value=f"```{invoice[:100]}...```",
            inline=False
        )
        embed.set_footer(text=FOOTER_TEXT)

        qr_file = discord.File(qr_buffer, filename=f"factura_{monto}sats.png")  # OJO: ESTO NO SE CAMBIA
        embed.set_image(url=f"attachment://factura_{monto}sats.png")  # OJO: ESTO NO SE CAMBIA

        await interaction.response.send_message(embed=embed, file=qr_file)

    except Exception as e:
        print(f"Error en generar_factura: {e}")
        await interaction.response.send_message("⚠️ Error interno del sistema", ephemeral=True)

@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)")
@app_commands.describe(factura="Factura Lightning en formato BOLT11")
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos"""
    user_id = str(interaction.user.id)
    cuentas = cargar_cuentas()

    if user_id not in cuentas:
        await interaction.response.send_message("⚠️ No tienes una cuenta creada. Usa /crear_cuenta para crear una.", ephemeral=True)
        return

    balance = cuentas[user_id]["balance"]

    if balance < 4:
        await interaction.response.send_message("🔶 Necesitas al menos 4 créditos para cubrir la comisión de retiro.", ephemeral=True)
        return

    #Obtener o crear la billetera LNbits del usuario
    lnbits_wallet_id = await get_or_create_lnbits_wallet(user_id)

    if not lnbits_wallet_id:
        await interaction.response.send_message("⚠️ No se pudo obtener o crear tu billetera de retiro. Intenta de nuevo más tarde.", ephemeral=True)
        return

    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message(
                "🔶 La factura no parece ser válida (debe comenzar con 'lnbc')",
                ephemeral=True
            )
            return

        #Transferir los creditos virtuales a la billetera LNbits (MENOS LA COMISION)
        success = await add_funds_to_lnbits_wallet(lnbits_wallet_id, balance - 4)
        if not success:
            await interaction.response.send_message("⚠️ No se pudieron transferir tus créditos a la billetera de retiro. Intenta de nuevo más tarde.", ephemeral=True)
            return

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
            headers=headers,
            timeout=10
        )

        payment_data = response.json()

        if 'error' in payment_data or 'payment_hash' not in payment_data:
            error = payment_data.get('detail', payment_data.get('error', 'Error desconocido'))
            await interaction.response.send_message(
                f"🔴 Error al procesar el pago: {error}",
                ephemeral=True
            )
            return

        #Restablecer el balance virtual a cero (ya que se transfirieron los creditos a LNbits)
        cuentas[user_id]["balance"] = 0
        guardar_cuentas(cuentas)

        embed = discord.Embed(
            title="✅ Pago Realizado",
            description=f"Se ha procesado el pago correctamente. (Comisión: 4 créditos)",
            color=0x28a745,
            timestamp=datetime.now()
        )

        embed.add_field(
            name="Hash del Pago",
            value=f"```{payment_data['payment_hash']}```",
            inline=False
        )

        if 'amount' in payment_data:
            embed.add_field(
                name="Monto",
                value=f"**{payment_data['amount'] / 1000:,} sats**", #ESTO NO SE CAMBIA
                inline=True
            )

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"Error en retirar_fondos: {e}")
        await interaction.response.send_message(
            "⚠️ Error al procesar el pago",
            ephemeral=True
        )

@bot.tree.command(name="balance", description="Muestra el balance actual de la cuenta")
async def ver_balance(interaction: discord.Interaction):
    """Muestra el balance de la cuenta"""
    user_id = str(interaction.user.id)
    cuentas = cargar_cuentas()

    if user_id not in cuentas:
        await interaction.response.send_message(
            "⚠️ No tienes una cuenta creada. Usa /crear_cuenta para crear una.",
            ephemeral=True
        )
        return

    balance = cuentas[user_id]["balance"]

    embed = discord.Embed(
        title="💰 Balance de la Cuenta",
        color=0xF7931A,
        timestamp=datetime.now()
    )

    embed.add_field(
        name="Saldo Disponible",
        value=f"**{balance / 1000:,} créditos**",
        inline=False
    )

    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

# --- FLASK WEB APP (AÑADIDO) ---
app = Flask(__name__)

@app.route('/balance/<user_id>')
async def show_balance(user_id):
    cuentas = cargar_cuentas()
    if user_id not in cuentas:
        return "⚠️ Cuenta no encontrada"

    balance = cuentas[user_id]["balance"]

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Balance de la Cuenta</title>
    </head>
    <body>
        <h1>Balance de la Cuenta</h1>
        <p>Usuario ID: {user_id}</p>
        <p>Saldo: {balance / 1000:.3f} créditos</p>
    </body>
    </html>
    """
    return html_content


@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print(f"\n✅ Bot conectado como: {bot.user}")
        print(f"🌐 URL LNBits: {LNBITS_URL}")
        #Crear el archivo si no existe
        if not os.path.exists(DATABASE_PATH):
          with open(DATABASE_PATH, 'w') as f:
            json.dump({}, f)

    except Exception as e:
        print(f"Error al iniciar: {e}")

if __name__ == "__main__":
    try:
        from PIL import Image
        print("✅ Dependencias de imagen verificadas")
    except ImportError:
        print("\n❌ Falta la dependencia Pillow (PIL)")
        print("Ejecuta en la consola de Replit:")
        print("pip install pillow qrcode[pil]\n")

    required_vars = ['DISCORD_TOKEN', 'LNBITS_URL', 'INVOICE_KEY', 'ADMIN_KEY']
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"\n❌ Faltan variables de entorno: {', '.join(missing)}")
        print("Configúralas en Replit -> Secrets (Variables de entorno)")
    else:
      # Ejecutar el bot de Discord en un hilo separado
      import threading
      discord_thread = threading.Thread(target=bot.run, args=(TOKEN,))
      discord_thread.start()

      # Ejecutar la aplicación Flask en el hilo principal
      app.run(host='0.0.0.0', port=5000)
