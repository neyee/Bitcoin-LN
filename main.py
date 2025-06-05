import os
import discord
import requests
import qrcode
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from flask import Flask, render_template_string

# --- CONFIGURACIÓN ---
TOKEN = os.getenv('DISCORD_TOKEN')
LNBITS_URL = os.getenv('LNBITS_URL', 'https://demo.lnbits.com').rstrip('/')
INVOICE_KEY = os.getenv('INVOICE_KEY')
ADMIN_KEY = os.getenv('ADMIN_KEY')
FOOTER_TEXT = os.getenv('FOOTER_TEXT', '⚡ Lightning Wallet Bot')

# AÑADIDO SOLO ESTO (tu ID)
YOUR_DISCORD_ID = 865597179145486366

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# AÑADIDO SOLO ESTO (función de verificación)
def only_you():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == YOUR_DISCORD_ID
    return app_commands.check(predicate)

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

@bot.tree.command(name="factura", description="Genera una factura Lightning con QR")
@app_commands.describe(
    monto="Cantidad en satoshis (mínimo 10)",
    descripcion="Concepto del pago (opcional)"
)
async def generar_factura(interaction: discord.Interaction, monto: int, descripcion: str = "Factura generada desde Discord"):
    """Genera una factura Lightning con QR"""
    try:
        if monto < 10:
            await interaction.response.send_message("🔶 El monto mínimo es 10 satoshis", ephemeral=True)
            return

        headers = {
            'X-Api-Key': INVOICE_KEY,
            'Content-type': 'application/json'
        }
        payload = {
            "out": False,
            "amount": monto,
            "memo": descripcion[:200],
            "unit": "sat"
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
            description=f"**{monto:,} satoshis**\n💡 {descripcion}",
            color=0x9932CC,
            timestamp=datetime.now()
        )

        embed.add_field(
            name="🔍 Código BOLT11",
            value=f"```{invoice[:100]}...```",
            inline=False
        )
        embed.set_footer(text=FOOTER_TEXT)

        qr_file = discord.File(qr_buffer, filename=f"factura_{monto}sats.png")
        embed.set_image(url=f"attachment://factura_{monto}sats.png")

        await interaction.response.send_message(embed=embed, file=qr_file)

    except Exception as e:
        print(f"Error en generar_factura: {e}")
        await interaction.response.send_message("⚠️ Error interno del sistema", ephemeral=True)

# AÑADIDO SOLO EL DECORADOR @only_you() A ESTE COMANDO
@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)")
@app_commands.describe(factura="Factura Lightning en formato BOLT11")
@only_you()  # <--- ÚNICO CAMBIO EN ESTE COMANDO
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos"""
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
            description=f"Se ha procesado el pago correctamente.",
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
                value=f"**{payment_data['amount'] / 1000:,} sats**",
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

@bot.tree.command(name="balance", description="Muestra el saldo actual de la billetera")
async def ver_balance(interaction: discord.Interaction):
    """Muestra el saldo de la billetera"""
    try:
        headers = {
            'X-Api-Key': ADMIN_KEY,
            'Content-type': 'application/json'
        }

        response = requests.get(
            f"{LNBITS_URL}/api/v1/wallet",
            headers=headers,
            timeout=10
        )

        wallet_info = response.json()

        if 'error' in wallet_info:
            await interaction.response.send_message(
                f"🔴 Error al obtener balance: {wallet_info['error']}",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="💰 Balance de la Billetera",
            color=0xF7931A,
            timestamp=datetime.now()
        )

        embed.add_field(
            name="Saldo Disponible",
            value=f"**{wallet_info['balance'] / 1000:,} sats**",
            inline=False
        )

        if 'name' in wallet_info:
            embed.add_field(name="Nombre", value=wallet_info['name'], inline=True)
        if 'id' in wallet_info:
            embed.add_field(name="ID Billetera", value=wallet_info['id'][:12]+"...", inline=True)

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"Error en ver_balance: {e}")
        await interaction.response.send_message("⚠️ Error al obtener el balance", ephemeral=True)

# --- EVENTOS ---
@bot.event
async def on_connect():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error al sincronizar comandos: {e}")
@bot.event
async def on_ready():

    print(f"\n✅ Bot conectado como: {bot.user}")
    print(f"🌐 URL LNBits: {LNBITS_URL}")

# --- INICIO DE FLASK ---
app = Flask(__name__)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

# --- EJECUCIÓN (HILOS) ---
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
      # Lanzar el bot de Discord en un hilo separado
      import threading
      discord_thread = threading.Thread(target=bot.run, args=(TOKEN,))
      discord_thread.start()

      # Lanzar la aplicación Flask en el hilo principal
      app.run(host='0.0.0.0', port=5000)
