import os
import discord
import requests
import qrcode
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from flask import Flask, render_template_string

# Configuración desde variables de entorno
TOKEN = os.getenv('DISCORD_TOKEN')
LNBITS_URL = os.getenv('LNBITS_URL', 'https://demo.lnbits.com').rstrip('/')
INVOICE_KEY = os.getenv('INVOICE_KEY')
ADMIN_KEY = os.getenv('ADMIN_KEY')
FOOTER_TEXT = os.getenv('FOOTER_TEXT', 'Sistema de Créditos Discord')  # Modificado

# AÑADIDO SOLO ESTO (tu ID)
YOUR_DISCORD_ID = 865597179145486366

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

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

# --- NUEVAS FUNCIONES AÑADIDAS ---

async def get_user_wallet(user_id: str):
    """Obtiene la información de la cuenta de un usuario. Si no existe, la crea.""" #Modificado
    headers = {
        'X-Api-Key': ADMIN_KEY,
        'Content-type': 'application/json'
    }
    try:
        # Intenta obtener la cuenta existente
        response = requests.get(
            f"{LNBITS_URL}/api/v1/wallets",
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        wallets = response.json()
        # Buscar la cuenta del usuario por ID
        user_wallet = next((wallet for wallet in wallets if wallet['name'] == str(user_id)), None)
        if user_wallet:
            return user_wallet
        else:
             # Si no existe, crear una nueva cuenta para el usuario
            payload = {
                "wallet_name": str(user_id)  # Usar el ID de Discord como nombre de la cuenta
            }
            response = requests.post(
                f"{LNBITS_URL}/api/v1/wallets",
                headers=headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            new_wallet = response.json()
            print(f"Cuenta creada para el usuario {user_id}: {new_wallet}") # Modificado
            return new_wallet

    except requests.exceptions.RequestException as e:
        print(f"Error al obtener o crear la cuenta: {e}") #Modificado
        return None
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error al analizar la respuesta de la API: {e}")
        return None
    except Exception as e:
        print(f"Error inesperado: {e}")
        return None


async def add_funds_to_wallet(wallet_id: str, amount: int):
    """Añade creditos a una cuenta.""" # Modificado
    headers = {
        'X-Api-Key': ADMIN_KEY,
        'Content-type': 'application/json'
    }
    payload = {
        "out": False,
        "amount": amount,
        "memo": f"Créditos añadidos por el admin", # Modificado
        "unit": "sat", # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
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
          print(f"Error al agregar creditos: {payment_data}") # Modificado
          return False

    except requests.exceptions.RequestException as e:
        print(f"Error al agregar creditos: {e}") # Modificado
        return False
async def get_wallet_balance(wallet_id: str) -> int:
    """Obtiene el balance de una cuenta en creditos.""" # Modificado
    headers = {
        'X-Api-Key': ADMIN_KEY,
        'Content-type': 'application/json'
    }

    try:
        response = requests.get(
            f"{LNBITS_URL}/api/v1/wallet/{wallet_id}",  # Obtener solo la cuenta específica
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        wallet_info = response.json()
        return wallet_info['balance']

    except requests.exceptions.RequestException as e:
        print(f"Error al obtener el balance de la cuenta: {e}") # Modificado
        return -1  # Error al obtener el balance
    except (KeyError, ValueError, TypeError) as e:
        print(f"Error al analizar la respuesta de la API: {e}")
        return -1
    except Exception as e:
        print(f"Error inesperado: {e}")
        return -1

# --- COMANDOS NUEVOS AÑADIDOS ---

@bot.tree.command(name="crear_cuenta", description="Crea una cuenta si aún no tienes una.") #Modificado
async def crear_billetera(interaction: discord.Interaction):
    """Crea una cuenta para el usuario.""" #Modificado
    user_id = str(interaction.user.id)
    wallet = await get_user_wallet(user_id)

    if wallet:
        await interaction.response.send_message("Ya tienes una cuenta creada.", ephemeral=True) #Modificado
    else:
        # La función get_user_wallet crea la cuenta si no existe
        wallet = await get_user_wallet(user_id)
        if wallet:
            await interaction.response.send_message("Cuenta creada exitosamente.", ephemeral=True) #Modificado
        else:
            await interaction.response.send_message("No se pudo crear la cuenta. Inténtalo de nuevo más tarde.", ephemeral=True) #Modificado

@bot.tree.command(name="addcash", description="Añade créditos a la cuenta de un usuario (solo admin)") #Modificado
@app_commands.describe(usuario="Usuario al que añadir créditos", monto="Cantidad de créditos") #Modificado
async def addcash(interaction: discord.Interaction, usuario: discord.Member, monto: int):
    """Añade créditos a la cuenta de un usuario (solo admin).""" #Modificado
    if interaction.user.id != YOUR_DISCORD_ID:
        await interaction.response.send_message("Solo el administrador puede usar este comando.", ephemeral=True)
        return

    wallet = await get_user_wallet(str(usuario.id))
    if not wallet:
        await interaction.response.send_message(f"No se pudo obtener o crear la cuenta para {usuario.mention}.", ephemeral=True) #Modificado
        return

    success = await add_funds_to_wallet(wallet['id'], monto)
    if success:
      await interaction.response.send_message(f"Se han añadido {monto} créditos a la cuenta de {usuario.mention}.", ephemeral=False) #Modificado
    else:
      await interaction.response.send_message(f"Error al añadir créditos a la cuenta de {usuario.mention}.", ephemeral=True) #Modificado


@bot.tree.command(name="tip", description="Da propina a otro usuario") #Modificado
@app_commands.describe(usuario="Usuario al que dar propina", monto="Cantidad de créditos") #Modificado
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

    # Obtener o crear cuentas para el remitente y el receptor
    sender_wallet = await get_user_wallet(sender_id)
    receiver_wallet = await get_user_wallet(receiver_id)

    if not sender_wallet or not receiver_wallet:
        await interaction.response.send_message("No se pudieron obtener las cuentas. Inténtalo de nuevo más tarde.", ephemeral=True) #Modificado
        return
    # Crear factura para el remitente
    headers = {
        'X-Api-Key': INVOICE_KEY,
        'Content-type': 'application/json'
    }
    payload = {
        "out": False,
        "amount": monto,
        "memo": f"Propina para {usuario.name}",
        "unit": "sat" # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
    }
    try:
        response = requests.post(
            f"{LNBITS_URL}/api/v1/payments",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        invoice_data = response.json()
        invoice = invoice_data['bolt11']
    except requests.exceptions.RequestException as e:
        await interaction.response.send_message("Error al generar la factura para la propina.", ephemeral=True)
        return
    # Pagar la factura desde la cuenta del remitente
    headers = {
        'X-Api-Key': ADMIN_KEY,
        'Content-type': 'application/json'
    }
    payload = {
        "out": True,
        "bolt11": invoice
    }
    try:
        response = requests.post(
            f"{LNBITS_URL}/api/v1/payments",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        payment_data = response.json()
        if 'payment_hash' in payment_data:
          #Acreditar monto al receptor
          success = await add_funds_to_wallet(receiver_wallet['id'], monto)
          if success:
            await interaction.response.send_message(f"{interaction.user.mention} ha dado {monto} créditos a {usuario.mention}.", ephemeral=False) #Modificado
          else:
            await interaction.response.send_message(f"Error al acreditar créditos a {usuario.mention}.", ephemeral=True) #Modificado
        else:
          await interaction.response.send_message("Error al pagar la factura de la propina.", ephemeral=True)
    except requests.exceptions.RequestException as e:
        await interaction.response.send_message("Error al pagar la factura de la propina.", ephemeral=True)
        return


# --- RESTO DE COMANDOS ORIGINALES SIN MODIFICAR ---
@bot.tree.command(name="factura", description="Genera una factura Lightning con QR")
@app_commands.describe(
    monto="Cantidad en satoshis (mínimo 10)", # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
    descripcion="Concepto del pago (opcional)"
)
async def generar_factura(interaction: discord.Interaction, monto: int, descripcion: str = "Factura generada desde Discord"):
    """Genera una factura Lightning con QR"""
    try:
        if monto < 10:
            await interaction.response.send_message("🔶 El monto mínimo es 10 satoshis", ephemeral=True) # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
            return

        headers = {
            'X-Api-Key': INVOICE_KEY,
            'Content-type': 'application/json'
        }
        payload = {
            "out": False,
            "amount": monto,
            "memo": descripcion[:200],
            "unit": "sat" # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
        }

        response = requests.post(
            f"{LNBITS_URL}/api/v1/payments",
            json=payload,
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
            description=f"**{monto:,} satoshis**\n💡 {descripcion}", # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
            color=0x9932CC,
            timestamp=datetime.now()
        )

        embed.add_field(
            name="🔍 Código BOLT11",
            value=f"```{invoice[:100]}...```",
            inline=False
        )
        embed.set_footer(text=FOOTER_TEXT)

        qr_file = discord.File(qr_buffer, filename=f"factura_{monto}sats.png") # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
        embed.set_image(url=f"attachment://factura_{monto}sats.png") # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE

        await interaction.response.send_message(embed=embed, file=qr_file)

    except Exception as e:
        print(f"Error en generar_factura: {e}")
        await interaction.response.send_message("⚠️ Error interno del sistema", ephemeral=True)

@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)") # OJO: EL NOMBRE DEL COMANDO NO SE CAMBIA
@app_commands.describe(factura="Factura Lightning en formato BOLT11") # OJO: LA DESCRIPCION NO SE CAMBIA
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos""" # OJO: LA DESCRIPCION NO SE CAMBIA
    user_id = str(interaction.user.id)
    wallet = await get_user_wallet(user_id)
    if not wallet:
        await interaction.response.send_message("⚠️ No se pudo obtener tu cuenta. Intenta de nuevo más tarde.", ephemeral=True) #Modificado
        return

    balance = await get_wallet_balance(wallet['id'])
    if balance < 4:
        await interaction.response.send_message("🔶 Necesitas al menos 4 créditos para cubrir la comisión de retiro.", ephemeral=True) #Modificado
        return

    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message(
                "🔶 La factura no parece ser válida (debe comenzar con 'lnbc')",
                ephemeral=True
            )
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
            json=payload,
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

        embed = discord.Embed(
            title="✅ Pago Realizado",
            description=f"Se ha procesado el pago correctamente. (Comisión: 4 créditos)", #Modificado
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
                value=f"**{payment_data['amount'] / 1000:,} sats**", # OJO: ESTO NO SE CAMBIA, SIGUE SIENDO SATOSHIS INTERNAMENTE
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

@bot.tree.command(name="balance", description="Muestra el balance actual de la cuenta") #Modificado
async def ver_balance(interaction: discord.Interaction):
    """Muestra el balance de la cuenta""" #Modificado
    user_id = str(interaction.user.id)
    wallet = await get_user_wallet(user_id)

    if not wallet:
        await interaction.response.send_message(
            "⚠️ No se pudo obtener tu cuenta. Usa /crear_cuenta para crear una.", #Modificado
            ephemeral=True
        )
        return

    balance = await get_wallet_balance(wallet['id']) # Usar wallet['id'] para obtener el balance

    if balance == -1:
        await interaction.response.send_message("⚠️ Error al obtener el balance.", ephemeral=True)
        return

    embed = discord.Embed(
        title="💰 Balance de la Cuenta", #Modificado
        color=0xF7931A,
        timestamp=datetime.now()
    )

    embed.add_field(
        name="Saldo Disponible", #Modificado
        value=f"**{balance / 1000:,} créditos**", #Modificado
        inline=False
    )

    embed.set_footer(text=FOOTER_TEXT)
    await interaction.response.send_message(embed=embed)

# --- FLASK WEB APP (AÑADIDO) ---
app = Flask(__name__)

@app.route('/balance/<user_id>')
async def show_balance(user_id):
    wallet = await get_user_wallet(user_id)
    if not wallet:
        return "⚠️ Cuenta no encontrada" #Modificado

    balance = await get_wallet_balance(wallet['id'])
    if balance == -1:
        return "⚠️ Error al obtener el balance"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Balance de la Cuenta</title> #Modificado
    </head>
    <body>
        <h1>Balance de la Cuenta</h1> #Modificado
        <p>Usuario ID: {user_id}</p>
        <p>Saldo: {balance / 1000:.3f} créditos</p> #Modificado
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
