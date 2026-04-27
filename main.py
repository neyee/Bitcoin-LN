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

# --- BASE DE DATOS SQLITE PARA CUENTAS VIRTUALES ---
def init_database():
    conn = sqlite3.connect('virtual_wallet.db')
    cursor = conn.cursor()
    
    # Tabla de cuentas de usuario
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            user_id TEXT PRIMARY KEY,
            balance_sats INTEGER DEFAULT 0,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de transacciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id TEXT PRIMARY KEY,
            user_id TEXT,
            type TEXT,
            amount_sats INTEGER,
            invoice TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES accounts (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# --- FUNCIONES DE BILLETERA VIRTUAL ---
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
        return {
            'user_id': account[0],
            'balance_sats': account[1],
            'username': account[2],
            'created_at': account[3],
            'last_activity': account[4]
        }
    
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
            'completed_at': tx[7]
        } for tx in transactions]

# Instancia global de la wallet virtual
wallet = VirtualWallet()

# --- FUNCIONES DE VERIFICACIÓN DE PAGOS ---
def check_invoice_status(payment_hash: str) -> dict:
    """Verifica el estado de una factura en LNBits"""
    try:
        headers = {
            'X-Api-Key': INVOICE_KEY,
            'Content-type': 'application/json'
        }
        
        # Verificar si podemos usar el endpoint de verificación
        response = requests.get(
            f"{LNBITS_URL}/api/v1/payments/{payment_hash}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            # Intentar con el endpoint de facturas
            response = requests.get(
                f"{LNBITS_URL}/api/v1/payments?limit=10",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                payments = response.json()
                for payment in payments:
                    if payment.get('payment_hash') == payment_hash:
                        return payment
            
            return {'paid': False, 'error': 'No encontrado'}
    
    except Exception as e:
        print(f"Error verificando factura: {e}")
        return {'paid': False, 'error': str(e)}

def generate_lightning_qr(lightning_invoice: str):
    """Genera un código QR para una factura Lightning"""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(f"lightning:{lightning_invoice}")
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"Error generando QR: {e}")
        return None

# --- COMANDOS DEL BOT ---
@bot.tree.command(name="depositar", description="Genera una factura para depositar sats a tu cuenta virtual")
@app_commands.describe(
    monto="Cantidad en satoshis a depositar (mínimo 10)",
    descripcion="Descripción del depósito (opcional)"
)
async def depositar(interaction: discord.Interaction, monto: int, descripcion: str = "Depósito a cuenta virtual"):
    """Genera una factura para que el usuario deposite sats"""
    try:
        if monto < 10:
            await interaction.response.send_message("🔶 El monto mínimo es 10 satoshis", ephemeral=True)
            return
        
        # Asegurar que el usuario tiene cuenta virtual
        user_id = str(interaction.user.id)
        username = interaction.user.name
        account = wallet.get_or_create_account(user_id, username)
        
        # Crear factura en LNBits
        headers = {
            'X-Api-Key': INVOICE_KEY,
            'Content-type': 'application/json'
        }
        payload = {
            "out": False,
            "amount": monto,
            "memo": f"Deposito user:{user_id} - {descripcion[:100]}",
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
        payment_hash = invoice_data.get('payment_hash')
        invoice = invoice_data.get('bolt11')
        
        if not invoice or not payment_hash:
            await interaction.response.send_message("🔴 La factura generada no es válida", ephemeral=True)
            return
        
        # Registrar transacción pendiente
        wallet.add_transaction(payment_hash, user_id, 'deposit', monto, invoice, 'pending')
        
        # Generar QR
        qr_buffer = generate_lightning_qr(invoice)
        
        embed = discord.Embed(
            title="📥 Depósito Pendiente",
            description=f"**{monto:,} sats** para tu cuenta virtual",
            color=0x9932CC,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📝 Factura Lightning",
            value=f"```{invoice[:150]}...```" if len(invoice) > 150 else f"```{invoice}```",
            inline=False
        )
        
        embed.add_field(
            name="💡 Instrucciones",
            value="1️⃣ Paga la factura con tu wallet Lightning\n"
                  "2️⃣ Usa `/verificar` para confirmar tu depósito\n"
                  "3️⃣ También puedes verificar automáticamente en unos segundos",
            inline=False
        )
        
        embed.add_field(
            name="🔍 ID de Seguimiento",
            value=f"`{payment_hash[:16]}...`",
            inline=False
        )
        
        embed.set_footer(text=FOOTER_TEXT)
        
        if qr_buffer:
            qr_file = discord.File(qr_buffer, filename=f"deposit_{monto}sats.png")
            embed.set_image(url=f"attachment://deposit_{monto}sats.png")
            await interaction.response.send_message(embed=embed, file=qr_file)
        else:
            await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error en depositar: {e}")
        await interaction.response.send_message("⚠️ Error interno del sistema", ephemeral=True)

@bot.tree.command(name="verificar", description="Verifica si un depósito pendiente fue recibido")
async def verificar_deposito(interaction: discord.Interaction):
    """Verifica todos los depósitos pendientes del usuario"""
    try:
        user_id = str(interaction.user.id)
        pending_txs = wallet.get_pending_transactions(user_id)
        
        if not pending_txs:
            await interaction.response.send_message(
                "📭 No tienes depósitos pendientes por verificar", 
                ephemeral=True
            )
            return
        
        # Verificar cada transacción pendiente
        verificadas = []
        nuevos_depositos = 0
        
        for tx in pending_txs:
            status = check_invoice_status(tx['tx_id'])
            
            if status.get('paid', False):
                # ¡Pago confirmado!
                wallet.update_balance(user_id, tx['amount_sats'])
                wallet.add_transaction(tx['tx_id'], user_id, 'deposit', 
                                      tx['amount_sats'], tx['invoice'], 'completed')
                nuevos_depositos += tx['amount_sats']
                verificadas.append({
                    'tx_id': tx['tx_id'],
                    'amount': tx['amount_sats'],
                    'confirmed': True
                })
            else:
                verificadas.append({
                    'tx_id': tx['tx_id'],
                    'amount': tx['amount_sats'],
                    'confirmed': False
                })
        
        # Mostrar resultados
        embed = discord.Embed(
            title="🔍 Verificación de Depósitos",
            color=0x00ff00 if nuevos_depositos > 0 else 0xffa500,
            timestamp=datetime.now()
        )
        
        for v in verificadas:
            status_emoji = "✅" if v['confirmed'] else "⏳"
            status_text = "Confirmado" if v['confirmed'] else "Pendiente"
            embed.add_field(
                name=f"{status_emoji} Depósito por {v['amount']:,} sats",
                value=f"Estado: **{status_text}**\nID: `{v['tx_id'][:16]}...`",
                inline=False
            )
        
        if nuevos_depositos > 0:
            account = wallet.get_or_create_account(user_id)
            embed.add_field(
                name="💰 Balance Actualizado",
                value=f"**{account['balance_sats']:,} sats** (+{nuevos_depositos:,} sats nuevos)",
                inline=False
            )
        
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error en verificar_deposito: {e}")
        await interaction.response.send_message("⚠️ Error al verificar depósitos", ephemeral=True)

@bot.tree.command(name="mibalance", description="Muestra el balance de tu cuenta virtual")
async def mi_balance(interaction: discord.Interaction):
    """Muestra el balance virtual del usuario"""
    try:
        user_id = str(interaction.user.id)
        account = wallet.get_or_create_account(user_id, interaction.user.name)
        
        embed = discord.Embed(
            title="💰 Mi Balance Virtual",
            color=0xF7931A,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="💳 Saldo Disponible",
            value=f"**{account['balance_sats']:,} sats**",
            inline=False
        )
        
        embed.add_field(
            name="👤 Usuario",
            value=interaction.user.name,
            inline=True
        )
        
        embed.add_field(
            name="📅 Cuenta creada",
            value=account['created_at'][:10] if account['created_at'] else "Hoy",
            inline=True
        )
        
        # Mostrar últimas transacciones
        txs = wallet.get_user_transactions(user_id, 3)
        if txs:
            tx_list = []
            for tx in txs:
                status_emoji = "✅" if tx['status'] == 'completed' else "⏳"
                tipo = "📥 Depósito" if tx['type'] == 'deposit' else "📤 Retiro"
                tx_list.append(f"{status_emoji} {tipo}: {tx['amount_sats']:,} sats")
            
            embed.add_field(
                name="📋 Últimas transacciones",
                value="\n".join(tx_list),
                inline=False
            )
        
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)
    
    except Exception as e:
        print(f"Error en mi_balance: {e}")
        await interaction.response.send_message("⚠️ Error al obtener balance", ephemeral=True)

@bot.tree.command(name="retirar", description="Retira sats de tu cuenta virtual a una wallet externa")
@app_commands.describe(
    factura="Factura Lightning BOLT11 para recibir el pago",
    monto="Cantidad de satoshis a retirar (opcional, usa el monto de la factura si no se especifica)"
)
async def retirar_fondos(interaction: discord.Interaction, factura: str, monto: int = None):
    """Permite a cualquier usuario retirar fondos de su cuenta virtual"""
    try:
        if not factura.startswith("lnbc"):
            await interaction.response.send_message(
                "🔶 La factura no parece ser válida (debe comenzar con 'lnbc')",
                ephemeral=True
            )
            return
        
        user_id = str(interaction.user.id)
        account = wallet.get_or_create_account(user_id, interaction.user.name)
        
        # Verificar saldo suficiente
        if account['balance_sats'] <= 0:
            await interaction.response.send_message(
                "🔴 No tienes saldo disponible para retirar",
                ephemeral=True
            )
            return
        
        # Si no se especifica monto, intentar deducir de la factura
        if not monto:
            await interaction.response.send_message(
                "🔶 Debes especificar el monto a retirar",
                ephemeral=True
            )
            return
        
        if monto > account['balance_sats']:
            await interaction.response.send_message(
                f"🔴 Saldo insuficiente. Tienes {account['balance_sats']:,} sats, "
                f"intentas retirar {monto:,} sats",
                ephemeral=True
            )
            return
        
        # Pagar la factura con la wallet principal
        headers = {
            'X-Api-Key': ADMIN_KEY,
            'Content-type': 'application/json'
        }
        payload = {
            "out": True,
            "bolt11": factura
        }
        
        # Primero verificar que tenemos saldo en la wallet principal
        wallet_response = requests.get(
            f"{LNBITS_URL}/api/v1/wallet",
            headers=headers,
            timeout=10
        )
        
        if wallet_response.status_code != 200:
            await interaction.response.send_message(
                "🔴 No se pudo verificar el saldo de la wallet principal",
                ephemeral=True
            )
            return
        
        wallet_sats = wallet_response.json().get('balance', 0) / 1000
        
        if wallet_sats < monto:
            await interaction.response.send_message(
                "🔴 La wallet principal no tiene suficientes fondos en este momento. "
                "Contacta al administrador.",
                ephemeral=True
            )
            return
        
        # Intentar el pago
        response = requests.post(
            f"{LNBITS_URL}/api/v1/payments",
            json=payload,
            headers=headers,
            timeout=10
        )
        
        payment_data = response.json()
        
        if response.status_code != 201 or 'error' in payment_data:
            error = payment_data.get('detail', payment_data.get('error', 'Error desconocido'))
            await interaction.response.send_message(
                f"🔴 Error al procesar el retiro: {error}",
                ephemeral=True
            )
            return
        
        # Descontar del balance virtual
        wallet.update_balance(user_id, -monto)
        wallet.add_transaction(
            payment_data.get('payment_hash', 'unknown'),
            user_id,
            'withdraw',
            monto,
            factura,
            'completed'
        )
        
        # Mostrar confirmación
        embed = discord.Embed(
            title="✅ Retiro Exitoso",
            description=f"Has retirado **{monto:,} sats** de tu cuenta virtual",
            color=0x28a745,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="🔍 Hash del Pago",
            value=f"```{payment_data.get('payment_hash', 'N/A')}```",
            inline=False
        )
        
        embed.add_field(
            name="💳 Balance Restante",
            value=f"**{account['balance_sats'] - monto:,} sats**",
            inline=True
        )
        
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_me
