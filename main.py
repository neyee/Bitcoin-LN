import os
import discord
import requests
import qrcode
import sqlite3
import asyncio
from io import BytesIO
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
from flask import Flask
import threading

# --- CONFIGURACIÓN ---
TOKEN = os.getenv('DISCORD_TOKEN')
LNBITS_URL = os.getenv('LNBITS_URL', 'https://demo.lnbits.com').rstrip('/')
INVOICE_KEY = os.getenv('INVOICE_KEY')
ADMIN_KEY = os.getenv('ADMIN_KEY')
FOOTER_TEXT = os.getenv('FOOTER_TEXT', '⚡ Lightning Wallet Bot')
YOUR_DISCORD_ID = int(os.getenv('ADMIN_DISCORD_ID', '865597179145486366'))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- FLASK PARA MANTENER EL BOT ACTIVO ---
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Lightning Bot está activo!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8080)))

# --- BASE DE DATOS SQLITE CORREGIDA ---
def init_database():
    conn = sqlite3.connect('virtual_wallet.db')
    cursor = conn.cursor()
    
    # Tabla de cuentas de usuario (SIN FOREIGN KEY por ahora)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            user_id TEXT PRIMARY KEY,
            balance_sats INTEGER DEFAULT 0,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de transacciones (SIN FOREIGN KEY para evitar errores)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id TEXT PRIMARY KEY,
            user_id TEXT,
            type TEXT,
            amount_sats INTEGER,
            invoice TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# --- CLASE WALLET CORREGIDA ---
class VirtualWallet:
    def __init__(self):
        self.db_path = 'virtual_wallet.db'
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def get_or_create_account(self, user_id: str, username: str = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM accounts WHERE user_id = ?', (str(user_id),))
        account = cursor.fetchone()
        
        if not account:
            cursor.execute(
                'INSERT INTO accounts (user_id, username) VALUES (?, ?)',
                (str(user_id), username or f"User_{user_id}")
            )
            conn.commit()
            cursor.execute('SELECT * FROM accounts WHERE user_id = ?', (str(user_id),))
            account = cursor.fetchone()
        
        conn.close()
        if account:
            return {
                'user_id': account[0],
                'balance_sats': account[1],
                'username': account[2],
                'created_at': account[3],
                'last_activity': account[4]
            }
        return None
    
    def update_balance(self, user_id: str, amount_sats: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE accounts 
            SET balance_sats = balance_sats + ?, 
                last_activity = CURRENT_TIMESTAMP 
            WHERE user_id = ?
        ''', (amount_sats, str(user_id)))
        
        conn.commit()
        conn.close()
    
    def add_transaction(self, tx_id: str, user_id: str, tx_type: str, 
                       amount: int, invoice: str, status: str = 'pending'):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO transactions 
            (tx_id, user_id, type, amount_sats, invoice, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (tx_id, str(user_id), tx_type, amount, invoice, status))
        
        conn.commit()
        conn.close()
    
    def complete_transaction(self, tx_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE transactions 
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE tx_id = ?
        ''', (tx_id,))
        
        conn.commit()
        conn.close()
    
    def get_pending_transactions(self, user_id: str = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if user_id:
            cursor.execute('''
                SELECT * FROM transactions 
                WHERE status = 'pending' AND user_id = ?
                ORDER BY created_at DESC
            ''', (str(user_id),))
        else:
            cursor.execute('''
                SELECT * FROM transactions 
                WHERE status = 'pending'
                ORDER BY created_at DESC
            ''')
        
        transactions = cursor.fetchall()
        conn.close()
        
        return [{
            'tx_id': tx[0],
            'user_id': tx[1],
            'type': tx[2],
            'amount_sats': tx[3],
            'invoice': tx[4],
            'status': tx[5],
            'created_at': tx[6]
        } for tx in transactions]
    
    def get_user_transactions(self, user_id: str, limit: int = 10):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM transactions 
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (str(user_id), limit))
        
        transactions = cursor.fetchall()
        conn.close()
        
        return [{
            'tx_id': tx[0],
            'user_id': tx[1],
            'type': tx[2],
            'amount_sats': tx[3],
            'invoice': tx[4],
            'status': tx[5],
            'created_at': tx[6],
            'completed_at': tx[7] if len(tx) > 7 else None
        } for tx in transactions]

wallet = VirtualWallet()

# --- FUNCIONES DE VERIFICACIÓN ---
def check_invoice_status(payment_hash: str) -> dict:
    try:
        headers = {'X-Api-Key': INVOICE_KEY, 'Content-type': 'application/json'}
        
        response = requests.get(
            f"{LNBITS_URL}/api/v1/payments/{payment_hash}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        
        return {'paid': False}
    
    except Exception as e:
        print(f"Error verificando factura: {e}")
        return {'paid': False}

def generate_lightning_qr(lightning_invoice: str):
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(f"lightning:{lightning_invoice}")
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"Error generando QR: {e}")
        return None

# --- TASK AUTOMÁTICA PARA VERIFICAR PAGOS (CORREGIDO) ---
@tasks.loop(minutes=2)
async def auto_verify_payments():
    """Verifica automáticamente pagos pendientes cada 2 minutos"""
    print("🔍 Verificando pagos pendientes...")
    
    pending_txs = wallet.get_pending_transactions()
    
    for tx in pending_txs:
        status = check_invoice_status(tx['tx_id'])
        
        if status.get('paid', False):
            # Actualizar balance
            wallet.update_balance(tx['user_id'], tx['amount_sats'])
            wallet.complete_transaction(tx['tx_id'])
            
            # Notificar al usuario (opcional)
            try:
                user = await bot.fetch_user(int(tx['user_id']))
                if user:
                    embed = discord.Embed(
                        title="✅ Depósito Confirmado",
                        description=f"Se han acreditado **{tx['amount_sats']:,} sats** a tu cuenta",
                        color=0x00ff00
                    )
                    await user.send(embed=embed)
            except:
                pass
            
            print(f"✅ Pago confirmado: {tx['tx_id'][:16]} - {tx['amount_sats']} sats")

@auto_verify_payments.before_loop
async def before_auto_verify():
    await bot.wait_until_ready()

# --- COMANDOS DEL BOT ---

@bot.tree.command(name="depositar", description="Genera una factura para depositar sats a tu cuenta virtual")
@app_commands.describe(monto="Cantidad en satoshis a depositar (mínimo 10)")
async def depositar(interaction: discord.Interaction, monto: int):
    try:
        if monto < 10:
            await interaction.response.send_message("🔶 El monto mínimo es 10 satoshis", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        wallet.get_or_create_account(user_id, interaction.user.name)
        
        headers = {'X-Api-Key': INVOICE_KEY, 'Content-type': 'application/json'}
        payload = {
            "out": False,
            "amount": monto,
            "memo": f"Deposito user:{user_id}",
            "unit": "sat"
        }
        
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers, timeout=10)
        
        if response.status_code != 201:
            await interaction.response.send_message("🔴 Error al crear factura", ephemeral=True)
            return
        
        invoice_data = response.json()
        payment_hash = invoice_data.get('payment_hash')
        invoice = invoice_data.get('bolt11')
        
        wallet.add_transaction(payment_hash, user_id, 'deposit', monto, invoice, 'pending')
        
        qr_buffer = generate_lightning_qr(invoice)
        
        embed = discord.Embed(
            title="📥 Depósito Pendiente",
            description=f"**{monto:,} sats** para tu cuenta virtual",
            color=0x9932CC
        )
        
        embed.add_field(name="💡 Instrucciones", 
                       value="Paga la factura con tu wallet Lightning\nEl saldo se acreditará automáticamente", 
                       inline=False)
        
        embed.set_footer(text=FOOTER_TEXT)
        
        if qr_buffer:
            qr_file = discord.File(qr_buffer, filename="qr.png")
            embed.set_image(url="attachment://qr.png")
            await interaction.response.send_message(embed=embed, file=qr_file)
        else:
            await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message("⚠️ Error interno", ephemeral=True)

@bot.tree.command(name="balance", description="Muestra el balance de tu cuenta virtual")
async def balance(interaction: discord.Interaction):
    try:
        user_id = str(interaction.user.id)
        account = wallet.get_or_create_account(user_id, interaction.user.name)
        
        embed = discord.Embed(
            title="💰 Mi Balance",
            description=f"**{account['balance_sats']:,} sats**",
            color=0xF7931A
        )
        
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message("⚠️ Error al obtener balance", ephemeral=True)

@bot.tree.command(name="retirar", description="Retira sats de tu cuenta virtual")
@app_commands.describe(factura="Factura Lightning BOLT11", monto="Cantidad a retirar")
async def retirar(interaction: discord.Interaction, factura: str, monto: int):
    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message("🔶 Factura no válida", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        account = wallet.get_or_create_account(user_id, interaction.user.name)
        
        if monto > account['balance_sats']:
            await interaction.response.send_message(f"🔴 Saldo insuficiente. Tienes {account['balance_sats']:,} sats", ephemeral=True)
            return
        
        # Pagar factura
        headers = {'X-Api-Key': ADMIN_KEY, 'Content-type': 'application/json'}
        payload = {"out": True, "bolt11": factura}
        
        response = requests.post(f"{LNBITS_URL}/api/v1/payments", json=payload, headers=headers, timeout=10)
        
        if response.status_code != 201:
            await interaction.response.send_message("🔴 Error al procesar el retiro", ephemeral=True)
            return
        
        payment_data = response.json()
        
        # Descontar balance
        wallet.update_balance(user_id, -monto)
        wallet.add_transaction(payment_data.get('payment_hash', 'unknown'), user_id, 'withdraw', monto, factura, 'completed')
        
        embed = discord.Embed(
            title="✅ Retiro Exitoso",
            description=f"Has retirado **{monto:,} sats**",
            color=0x28a745
        )
        
        embed.add_field(name="💳 Balance Restante", value=f"**{account['balance_sats'] - monto:,} sats**")
        embed.set_footer(text=FOOTER_TEXT)
        
        # ✅ CORRECCIÓN: Usar send_message en lugar de send_edit
        await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message("⚠️ Error al procesar retiro", ephemeral=True)

# ✅ NUEVO COMANDO: Transferencias entre usuarios
@bot.tree.command(name="enviar", description="Envía sats a otro usuario del bot")
@app_commands.describe(usuario="Usuario destino", monto="Cantidad de satoshis")
async def enviar(interaction: discord.Interaction, usuario: discord.User, monto: int):
    try:
        if monto <= 0:
            await interaction.response.send_message("🔶 Monto inválido", ephemeral=True)
            return
        
        if usuario.id == interaction.user.id:
            await interaction.response.send_message("🔶 No puedes enviarte a ti mismo", ephemeral=True)
            return
        
        user_id_origen = str(interaction.user.id)
        account_origen = wallet.get_or_create_account(user_id_origen, interaction.user.name)
        
        if monto > account_origen['balance_sats']:
            await interaction.response.send_message(f"🔴 Saldo insuficiente. Tienes {account_origen['balance_sats']:,} sats", ephemeral=True)
            return
        
        user_id_destino = str(usuario.id)
        wallet.get_or_create_account(user_id_destino, usuario.name)
        
        # Transferir
        wallet.update_balance(user_id_origen, -monto)
        wallet.update_balance(user_id_destino, monto)
        
        # Registrar transacciones
        tx_id = f"transfer_{datetime.now().timestamp()}"
        wallet.add_transaction(tx_id, user_id_origen, 'transfer_out', monto, f"Enviado a {usuario.name}", 'completed')
        wallet.add_transaction(tx_id, user_id_destino, 'transfer_in', monto, f"Recibido de {interaction.user.name}", 'completed')
        
        embed = discord.Embed(
            title="✅ Transferencia Exitosa",
            description=f"Has enviado **{monto:,} sats** a {usuario.mention}",
            color=0x00ff00
        )
        
        new_balance = account_origen['balance_sats'] - monto
        embed.add_field(name="💰 Tu nuevo balance", value=f"**{new_balance:,} sats**")
        embed.set_footer(text=FOOTER_TEXT)
        
        await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error: {e}")
        await interaction.response.send_message("⚠️ Error al enviar", ephemeral=True)

# Evento cuando el bot está listo
@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    await bot.tree.sync()
    auto_verify_payments.start()
    print('✅ Comandos sincronizados y verificador automático activado')
    
    # Enviar mensaje al canal de logs (opcional)
    try:
        owner = await bot.fetch_user(YOUR_DISCORD_ID)
        await owner.send("✅ Bot Lightning está activo y funcionando correctamente")
    except:
        pass

# --- INICIO DEL BOT ---
def main():
    # Inicializar BD
    init_database()
    
    # Iniciar Flask en segundo plano
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Iniciar bot
    bot.run(TOKEN)

if __name__ == "__main__":
    main()

