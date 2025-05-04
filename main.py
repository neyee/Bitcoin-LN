import os
import discord
import requests
import qrcode
import asyncio
import aiohttp
import hmac
import hashlib
import time
import base64
from io import BytesIO
from datetime import datetime
from discord.ext import commands
from discord import app_commands

import threading
from flask import Flask
from werkzeug.serving import make_server

# Configuración desde variables de entorno
TOKEN = os.getenv('DISCORD_TOKEN')
LNBITS_URL = os.getenv('LNBITS_URL', 'https://demo.lnbits.com').rstrip('/')
INVOICE_KEY = os.getenv('INVOICE_KEY')
ADMIN_KEY = os.getenv('ADMIN_KEY')
FOOTER_TEXT = os.getenv('FOOTER_TEXT', '⚡ Lightning Wallet Bot')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_SECRET_KEY = os.getenv('OKX_SECRET_KEY')

# ID del administrador (REEMPLAZA CON TU ID REAL)
YOUR_DISCORD_ID = 865597179145486366

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

 --- Keep-alive usando Flask ---
app = Flask('')

@app.route('/')
def home():
    return "Bot activo."

class ServerThread(threading.Thread):
    def run(self):
        make_server('0.0.0.0', 8080, app).serve_forever()

ServerThread().start()


# --- FUNCIONES ORIGINALES (SIN MODIFICAR) ---
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

# --- FUNCIONES AÑADIDAS (SOLO ESTO ES NUEVO) ---
def sign_okx_request(method, path):
    """Firma peticiones a OKX"""
    timestamp = str(time.time())
    message = timestamp + method + path
    signature = base64.b64encode(
        hmac.new(
            OKX_SECRET_KEY.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
    ).decode()
    return {
        'OK-ACCESS-KEY': OKX_API_KEY,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'Content-Type': 'application/json'
    }

async def get_btc_price():
    """Obtiene precio BTC desde OKX"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = sign_okx_request('GET', '/api/v5/market/ticker?instId=BTC-USDT')
            async with session.get('https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT', headers=headers) as resp:
                data = await resp.json()
                return float(data['data'][0]['last'])
    except Exception as e:
        print(f"Error obteniendo precio BTC: {e}")
        return None

async def send_deposit_notification(payment_data):
    """Envía notificación de depósito al admin"""
    try:
        admin = await bot.fetch_user(YOUR_DISCORD_ID)
        if not admin:
            return

        btc_price = await get_btc_price()
        amount_sats = payment_data.get('amount', 0) / 1000
        usd_value = (amount_sats / 100_000_000) * btc_price if btc_price else None

        embed = discord.Embed(
            title="💰 ¡Nuevo Depósito Recibido!",
            description=f"**{amount_sats:,.0f} sats**" + (f" (${usd_value:,.2f} USD)" if usd_value else ""),
            color=0x28a745,
            timestamp=datetime.now()
        )
        embed.add_field(name="📝 Descripción", value=f"```{payment_data.get('memo', 'Sin descripción')[:100]}```", inline=False)
        embed.set_footer(text=FOOTER_TEXT)
        
        await admin.send(embed=embed)
    except Exception as e:
        print(f"Error enviando notificación: {e}")

# --- TUS COMANDOS ORIGINALES COMPLETOS (CON AÑADIDOS PARA USD) ---
@bot.tree.command(name="factura", description="Genera una factura Lightning con QR")
@app_commands.describe(
    monto="Cantidad en satoshis (mínimo 10)",
    descripcion="Concepto del pago (opcional)"
)
async def generar_factura(interaction: discord.Interaction, monto: int, descripcion: str = "Factura generada desde Discord"):
    """Genera una factura Lightning con QR"""
    try:
        if monto < 1:
            await interaction.response.send_message("🔶 El monto mínimo es 1 satoshis", ephemeral=True)
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

        # Crear embed (tu código original)
        embed = discord.Embed(
            title="📄 Factura Lightning",
            description=f"**{monto:,} satoshis**\n💡 {descripcion}",
            color=0x9932CC,
            timestamp=datetime.now()
        )
        
        # Añadir conversión a USD (nuevo)
        btc_price = await get_btc_price()
        if btc_price:
            usd_value = (monto / 100_000_000) * btc_price
            embed.add_field(
                name="USD",
                value=f"${usd_value:,.2f} USD",
                inline=True
            )

        embed.add_field(
            name=" BOLT11",
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

@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)")
@app_commands.describe(factura="Factura Lightning en formato BOLT11")
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
            amount_sats = payment_data['amount'] / 1000
            embed.add_field(
                name="Monto",
                value=f"**{amount_sats:,.0f} sats**",
                inline=True
            )
            
            # Añadir conversión a USD (nuevo)
            btc_price = await get_btc_price()
            if btc_price:
                usd_value = (amount_sats / 100_000_000) * btc_price
                embed.add_field(
                    name="USD",
                    value=f"${usd_value:,.2f} USD",
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
        
        balance_sats = wallet_info['balance'] / 1000
        embed.add_field(
            name="Saldo Disponible",
            value=f"**{balance_sats:,.0f} sats**",
            inline=False
        )
        
        # Añadir conversión a USD (nuevo)
        btc_price = await get_btc_price()
        if btc_price:
            usd_value = (balance_sats / 100_000_000) * btc_price
            embed.add_field(
                name="USD",
                value=f"${usd_value:,.2f} USD",
                inline=True
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

# --- TAREA EN SEGUNDO PLANO PARA NOTIFICACIONES ---
async def check_payments_background():
    """Verifica nuevos pagos cada 30 segundos"""
    global last_checked_payment
    await bot.wait_until_ready()
    last_payment = None
    
    while not bot.is_closed():
        try:
            headers = {'X-Api-Key': INVOICE_KEY}
            response = requests.get(
                f"{LNBITS_URL}/api/v1/payments",
                headers=headers,
                timeout=15
            )
            payments = response.json()

            if isinstance(payments, list):
                new_payments = [p for p in payments if p.get('incoming') and p.get('payment_hash') != last_payment]
                
                if new_payments:
                    last_payment = new_payments[0]['payment_hash']
                    await send_deposit_notification(new_payments[0])
        except Exception as e:
            print(f"Error verificando pagos: {e}")
        
        await asyncio.sleep(30)

# --- INICIALIZACIÓN --- 
@bot.event
async def on_ready():
    try:
        # Inicia la verificación de pagos en segundo plano
        bot.loop.create_task(check_payments_background())
        
        # Sincroniza los comandos slash
        await bot.tree.sync()
        
        print(f"\n✅ Bot conectado como: {bot.user}")
        print(f"🌐 URL LNBits: {LNBITS_URL}")
        print(f"🔔 Notificaciones activas para: {YOUR_DISCORD_ID}")
        
        # Verifica conexión con OKX
        btc_price = await get_btc_price()
        if btc_price:
            print(f"💰 Precio BTC actual: ${btc_price:,.2f} USD")
        else:
            print("⚠️ No se pudo obtener precio de OKX (las conversiones USD estarán desactivadas)")
            
    except Exception as e:
        print(f"⛔ Error crítico al iniciar: {e}")

if __name__ == "__main__":
    # Validación de dependencias (original)
    try:
        from PIL import Image
        print("✅ Dependencias de imagen verificadas (Pillow)")
    except ImportError:
        print("\n❌ Falta la dependencia Pillow (PIL)")
        print("Ejecuta en la consola: pip install pillow qrcode[pil]\n")

    # Validación de variables de entorno (original + OKX)
    required_vars = {
        'DISCORD_TOKEN': 'Token del bot de Discord',
        'LNBITS_URL': 'URL de LNBits', 
        'INVOICE_KEY': 'Clave de facturación LNBits',
        'ADMIN_KEY': 'Clave admin LNBits',
        'OKX_API_KEY': 'API Key de OKX (opcional)',
        'OKX_SECRET_KEY': 'Secret Key de OKX (opcional)'
    }
    
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        print("\n❌ Faltan variables de entorno:")
        for var in missing:
            print(f"- {var}: {required_vars[var]}")
        print("\nConfigúralas en Replit -> Secrets (⚙️)")
    else:
        # Inicia el bot (original)
        try:
            bot.run(TOKEN)
        except discord.LoginFailure:
            print("\n⛔ Error: Token de Discord inválido")
        except Exception as e:
            print(f"\n⛔ Error inesperado: {e}")
