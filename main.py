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
from discord import app_commands, ui
from flask import Flask, jsonify
import threading

# Configuración desde variables de entorno
TOKEN = os.getenv('DISCORD_TOKEN')
LNBITS_URL = os.getenv('LNBITS_URL', 'https://demo.lnbits.com').rstrip('/')
INVOICE_KEY = os.getenv('INVOICE_KEY')
ADMIN_KEY = os.getenv('ADMIN_KEY')
FOOTER_TEXT = os.getenv('FOOTER_TEXT', '⚡ Lightning Wallet Bot')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_SECRET_KEY = os.getenv('OKX_SECRET_KEY')
YOUR_DISCORD_ID = 865597179145486366

# Configuración de Flask para Render
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "discord-bot",
        "documentation": "/status"
    })

@app.route('/status')
def status():
    return jsonify({
        "bot_online": bot.is_ready(),
        "bot_user": str(bot.user) if hasattr(bot, 'user') else None,
        "last_ping": f"{round(bot.latency * 1000)}ms" if bot.latency else None,
        "timestamp": datetime.now().isoformat()
    })

# Configuración del bot de Discord
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ========== FUNCIONES ORIGINALES (INALTERADAS) ==========
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

# ========== COMANDOS ORIGINALES CON BOTÓN DE CONFIRMACIÓN ==========
@bot.tree.command(name="retirar", description="Pagar una factura Lightning (retirar fondos)")
@app_commands.describe(factura="Factura Lightning en formato BOLT11")
async def retirar_fondos(interaction: discord.Interaction, factura: str):
    """Paga una factura Lightning para retirar fondos"""
    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message("La factura no parece ser válida (debe comenzar con 'lnbc')", ephemeral=True)
            return

        amount_msats = int(factura.split('lnbc')[1].split('p')[0])
        amount_sats = amount_msats // 1000 if amount_msats >= 1000 else 1
        btc_price = await get_btc_price()
        usd_value = (amount_sats / 100_000_000) * btc_price if btc_price else None

        class ConfirmView(discord.ui.View):
            def __init__(self, original_interaction):
                super().__init__(timeout=60)
                self.original_interaction = original_interaction

            @discord.ui.button(label='✅ Confirmar Pago', style=discord.ButtonStyle.green)
            async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                if button_interaction.user != self.original_interaction.user:
                    await button_interaction.response.send_message("❌ No tienes permiso para confirmar este pago", ephemeral=True)
                    return
                
                await button_interaction.response.defer(thinking=True)
                
                headers = {'X-Api-Key': ADMIN_KEY, 'Content-type': 'application/json'}
                payload = {"out": True, "bolt11": factura}
                
                try:
                    response = requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers, timeout=10)
                    payment_data = response.json()

                    if 'error' in payment_data or 'payment_hash' not in payment_data:
                        error = payment_data.get('detail', payment_data.get('error', 'Error desconocido'))
                        return await button_interaction.followup.send(f"❌ Error al procesar: {error}", ephemeral=True)

                    embed = discord.Embed(
                        title="✅ Pago Completado",
                        description=f"**{amount_sats:,.0f} sats**" + (f" (${usd_value:,.2f} USD)" if usd_value else ""),
                        color=0x28a745,
                        timestamp=datetime.now()
                    )
                    embed.add_field(name="🔗 Hash", value=f"```{payment_data['payment_hash']}```", inline=False)
                    embed.set_footer(text=FOOTER_TEXT)
                    
                    await button_interaction.followup.send(embed=embed)
                
                except Exception as e:
                    await button_interaction.followup.send(f"⚠️ Error crítico: {str(e)}", ephemeral=True)

        embed = discord.Embed(
            title="🔔 Confirmar Pago",
            description=f"Estás a punto de pagar:\n**{amount_sats:,.0f} sats**" + (f" (${usd_value:,.2f} USD)" if usd_value else ""),
            color=0xF7931A
        )
        embed.set_footer(text="Tienes 60 segundos para confirmar")
        
        await interaction.response.send_message(embed=embed, view=ConfirmView(interaction), ephemeral=True)

    except Exception as e:
        print(f"Error en retirar_fondos: {e}")
        await interaction.response.send_message("⚠️ Error al procesar la factura", ephemeral=True)

# ========== RESTO DE TUS COMANDOS ORIGINALES (INALTERADOS) ==========
@bot.tree.command(name="factura", description="Genera una factura Lightning con QR")
@app_commands.describe(monto="Cantidad en satoshis", descripcion="Concepto del pago (opcional)")
async def generar_factura(interaction: discord.Interaction, monto: int, descripcion: str = "Factura generada desde Discord"):
    """Tu implementación original sin cambios"""
    # ... (mantén todo tu código original aquí)

@bot.tree.command(name="balance", description="Muestra el saldo actual de la billetera")
async def ver_balance(interaction: discord.Interaction):
    """Tu implementación original sin cambios"""
    # ... (mantén todo tu código original aquí)

# ========== TAREAS EN SEGUNDO PLANO (ORIGINAL) ==========
async def check_payments_background():
    """Tu implementación original sin cambios"""
    # ... (mantén todo tu código original aquí)

# ========== INICIALIZACIÓN ADAPTADA PARA RENDER ==========
def run_flask():
    """Inicia Flask en un puerto compatible con Render"""
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

@bot.event
async def on_ready():
    """Tu implementación original con añadidos para Render"""
    try:
        bot.loop.create_task(check_payments_background())
        await bot.tree.sync()
        
        print(f"\n✅ Bot conectado como: {bot.user}")
        print(f"🌐 LNBits URL: {LNBITS_URL}")
        print(f"📊 Endpoint status: http://localhost:{os.getenv('PORT', 5001)}/status")
        
        btc_price = await get_btc_price()
        if btc_price:
            print(f"💰 Precio BTC: ${btc_price:,.2f} USD")
            
    except Exception as e:
        print(f"❌ Error en on_ready: {e}")

# ========== EJECUCIÓN PRINCIPAL ==========
if __name__ == "__main__":
    # Validación de dependencias
    try:
        from PIL import Image
        print("✅ Dependencias verificadas")
    except ImportError:
        print("\n❌ Ejecuta: pip install pillow qrcode[pil] requests aiohttp\n")

    # Validación de variables
    required_vars = ['DISCORD_TOKEN', 'LNBITS_URL', 'INVOICE_KEY', 'ADMIN_KEY']
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        print(f"\n❌ Faltan variables: {missing}")
    else:
        # Inicia Flask en segundo plano
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Inicia el bot
        try:
            bot.run(TOKEN)
        except discord.LoginFailure:
            print("\n❌ Token de Discord inválido")
        except Exception as e:
            print(f"\n❌ Error inesperado: {str(e)}")
