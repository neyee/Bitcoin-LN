import discord
from discord.ext import commands, tasks
import requests
import asyncio
import json
import random
import os
import sqlite3  # Importa sqlite3
from datetime import datetime

# Lee la configuración desde config.json
with open('config.json', 'r') as f:
    config = json.load(f)

TOKEN = config['TOKEN']
ADMIN_ROLE_ID = config['ADMIN_ROLE_ID']
API_DOLAR_URL = config['https://api.yadio.io/compare/2/ARS']
FLASH_FOLDER = config['FLASH_FOLDER']
BOT_PREFIX = config['BOT_PREFIX']

# Intents necesarios
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Inicializa el bot
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# Base de datos SQLite
DATABASE_PATH = 'data/usuarios.db'

# Inicializa la tasa de cambio
tasabsdolar = None

# ------------------- Funciones de Base de Datos -------------------

def crear_conexion():
    """Crea una conexión a la base de datos SQLite."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        return conn
    except sqlite3.Error as e:
        print(f"Error al conectar a la base de datos: {e}")
        return None

def crear_tablas():
    """Crea las tablas 'usuarios' y 'configuracion' si no existen."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id TEXT PRIMARY KEY,
                    saldo_bs REAL DEFAULT 0.0,
                    saldo_usd REAL DEFAULT 0.0
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS configuracion (
                    clave TEXT PRIMARY KEY,
                    valor TEXT
                )
            """)
            conn.commit()
            print("Tablas creadas o ya existentes.")
        except sqlite3.Error as e:
            print(f"Error al crear tablas: {e}")
        finally:
            conn.close()
    else:
        print("No se pudo crear la conexión a la base de datos.")

def obtener_saldo(user_id):
    """Obtiene el saldo en Bs y USD de un usuario desde la base de datos."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT saldo_bs, saldo_usd FROM usuarios WHERE id = ?", (str(user_id),))
            data = cursor.fetchone()
            if data:
                return data[0], data[1]  # saldo_bs, saldo_usd
            else:
                return 0.0, 0.0  # Saldo por defecto si no existe el usuario
        except sqlite3.Error as e:
            print(f"Error al obtener el saldo: {e}")
            return None, None
        finally:
            conn.close()
    else:
        print("No se pudo crear la conexión a la base de datos.")
        return None, None


def actualizar_saldo(user_id, saldo_bs, saldo_usd):
    """Actualiza el saldo en Bs y USD de un usuario en la base de datos."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO usuarios (id, saldo_bs, saldo_usd)
                VALUES (?, ?, ?)
            """, (str(user_id), saldo_bs, saldo_usd))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error al actualizar el saldo: {e}")
        finally:
            conn.close()
    else:
        print("No se pudo crear la conexión a la base de datos.")

def obtener_usd_disponibles():
    """Obtiene la cantidad de USD disponibles desde la base de datos."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT valor FROM configuracion WHERE clave = 'usd_disponibles'")
            data = cursor.fetchone()
            if data:
                return float(data[0])
            else:
                return 0.0  # Valor por defecto si no existe la configuración
        except sqlite3.Error as e:
            print(f"Error al obtener los USD disponibles: {e}")
            return None
        finally:
            conn.close()
    else:
        print("No se pudo crear la conexión a la base de datos.")
        return None

def actualizar_usd_disponibles(cantidad):
    """Actualiza la cantidad de USD disponibles en la base de datos."""
    conn = crear_conexion()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO configuracion (clave, valor)
                VALUES ('usd_disponibles', ?)
            """, (str(cantidad),))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error al actualizar los USD disponibles: {e}")
        finally:
            conn.close()
    else:
        print("No se pudo crear la conexión a la base de datos.")

# ------------------- Funciones Auxiliares -------------------

async def obtener_tasa_cambio():
    """Obtiene la tasa de cambio desde la API."""
    try:
        response = requests.get(API_DOLAR_URL)
        response.raise_for_status()
        data = response.json()
        tasa = data['rates']['VES']
        return tasa
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener la tasa de cambio: {e}")
        return None


def cargar_imagenes_flash():
    """Carga la lista de imágenes disponibles en la carpeta 'flash'."""
    try:
        imagenes = [f for f in os.listdir(FLASH_FOLDER) if os.path.isfile(os.path.join(FLASH_FOLDER, f))]
        return imagenes
    except FileNotFoundError:
        print(f"La carpeta '{FLASH_FOLDER}' no fue encontrada.")
        return []
    except Exception as e:
        print(f"Error al cargar imágenes flash: {e}")
        return []

# ------------------- Comandos -------------------

@bot.tree.command(name="bal", description="Muestra tu saldo.")
async def bal(interaction: discord.Interaction):
    """Muestra el saldo del usuario en Bs y USD."""
    user_id = interaction.user.id
    saldo_bs, saldo_usd = obtener_saldo(user_id)

    if saldo_bs is None or saldo_usd is None:
        await interaction.response.send_message("Error al obtener el saldo. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    embed = discord.Embed(title="Tu Saldo", color=discord.Color.green())
    embed.add_field(name="Bolívares (Bs)", value=f"{saldo_bs:.2f}", inline=False)
    embed.add_field(name="Dólares (USD)", value=f"{saldo_usd:.2f}", inline=False)
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="tip", description="Da propina a otro usuario.")
async def tip(interaction: discord.Interaction, usuario: discord.Member, monto_bs: float):
    """Da propina a otro usuario en Bolívares."""
    donante_id = interaction.user.id
    receptor_id = usuario.id

    if donante_id == receptor_id:
        await interaction.response.send_message("¡No puedes darte propina a ti mismo!", ephemeral=True)
        return

    if monto_bs <= 0:
        await interaction.response.send_message("El monto debe ser mayor que cero.", ephemeral=True)
        return

    saldo_bs_donante, saldo_usd_donante = obtener_saldo(donante_id)
    saldo_bs_receptor, saldo_usd_receptor = obtener_saldo(receptor_id)

    if saldo_bs_donante is None or saldo_usd_donante is None or saldo_bs_receptor is None or saldo_usd_receptor is None:
        await interaction.response.send_message("Error al obtener el saldo. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    if saldo_bs_donante < monto_bs:
        await interaction.response.send_message("No tienes suficiente saldo en Bolívares.", ephemeral=True)
        return

    # Actualiza los saldos en la base de datos
    actualizar_saldo(donante_id, saldo_bs_donante - monto_bs, saldo_usd_donante)
    actualizar_saldo(receptor_id, saldo_bs_receptor + monto_bs, saldo_usd_receptor)

    await interaction.response.send_message(f"{interaction.user.mention} ha dado {monto_bs:.2f} Bs a {usuario.mention}")


@bot.tree.command(name="addcash", description="Añade saldo a un usuario (solo admin).")
async def addcash(interaction: discord.Interaction, usuario: discord.Member, monto_bs: float = 0.0, monto_usd: float = 0.0):
    """Añade saldo en Bs o USD a un usuario (solo admin)."""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("¡Solo los administradores pueden usar este comando!", ephemeral=True)
        return

    receptor_id = usuario.id
    saldo_bs, saldo_usd = obtener_saldo(receptor_id)

    if saldo_bs is None or saldo_usd is None:
        await interaction.response.send_message("Error al obtener el saldo. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    # Actualiza los saldos en la base de datos
    actualizar_saldo(receptor_id, saldo_bs + monto_bs, saldo_usd + monto_usd)

    await interaction.response.send_message(f"Se han añadido {monto_bs:.2f} Bs y {monto_usd:.2f} USD a {usuario.mention}")


@bot.tree.command(name="work", description="Trabaja para ganar dinero.")
async def work(interaction: discord.Interaction):
    """Permite al usuario trabajar para ganar una cantidad aleatoria de Bs."""
    user_id = interaction.user.id
    ganancia_bs = random.randint(50, 150)  # Rango de ganancia
    saldo_bs, saldo_usd = obtener_saldo(user_id)

    if saldo_bs is None or saldo_usd is None:
        await interaction.response.send_message("Error al obtener el saldo. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    # Actualiza el saldo en la base de datos
    actualizar_saldo(user_id, saldo_bs + ganancia_bs, saldo_usd)

    await interaction.response.send_message(f"{interaction.user.mention} ha trabajado y ganado {ganancia_bs:.2f} Bs")

@bot.tree.command(name="daily", description="Reclama tu bono diario.")
async def daily(interaction: discord.Interaction):
    """Permite al usuario reclamar un bono diario en Bs."""
    user_id = interaction.user.id
    bono_bs = 100.0  # Cantidad del bono diario
    saldo_bs, saldo_usd = obtener_saldo(user_id)
    if saldo_bs is None or saldo_usd is None:
        await interaction.response.send_message("Error al obtener el saldo. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    # Actualiza el saldo en la base de datos
    actualizar_saldo(user_id, saldo_bs + bono_bs, saldo_usd)

    await interaction.response.send_message(f"{interaction.user.mention} ha reclamado su bono diario de {bono_bs:.2f} Bs")



@bot.tree.command(name="convertir", description="Convierte Bolívares a Dólares.")
async def convertir(interaction: discord.Interaction, monto_bs: float):
    """Convierte una cantidad de Bolívares a Dólares."""
    global tasabsdolar
    if not tasabsdolar:
        tasabsdolar = await obtener_tasa_cambio()
    if tasabsdolar is None:
        await interaction.response.send_message("No se pudo obtener la tasa de cambio. Inténtalo de nuevo más tarde.", ephemeral=True)
        return

    dolares = monto_bs / tasabsdolar
    await interaction.response.send_message(f"{monto_bs:.2f} Bs son equivalentes a {dolares:.2f} USD (Tasa de cambio: 1 USD = {tasabsdolar:.2f} VES)")


@bot.tree.command(name="fash", description="Muestra un producto o promoción.")
async def fash(interaction: discord.Interaction):
    """Muestra una imagen aleatoria de la carpeta 'flash'."""
    imagenes = cargar_imagenes_flash()

    if not imagenes:
        await interaction.response.send_message("No hay imágenes disponibles para mostrar.", ephemeral=True)
        return

    imagen_seleccionada = random.choice(imagenes)
    imagen_path = os.path.join(FLASH_FOLDER, imagen_seleccionada)

    try:
        file = discord.File(imagen_path)
        embed = discord.Embed(title="¡Mira esta oferta!", color=discord.Color.blue())
        embed.set_image(url=f"attachment://{imagen_seleccionada}")  #Importante para mostrar la imagen
        await interaction.response.send_message(embed=embed, file=file) # Enviar el embed y el archivo
    except FileNotFoundError:
        await interaction.response.send_message("La imagen no se encontró.", ephemeral=True)
    except Exception as e:
        print(f"Error al enviar la imagen: {e}")
        await interaction.response.send_message("Ocurrió un error al mostrar la imagen.", ephemeral=True)


# ------------------- Comandos de Admin -------------------

@bot.tree.command(name="setusd", description="Establece la cantidad de USD disponibles (solo admin).")
async def setusd(interaction: discord.Interaction, cantidad: float):
    """Establece la cantidad de USD disponibles (solo para administradores)."""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("¡Solo los administradores pueden usar este comando!", ephemeral=True)
        return

    actualizar_usd_disponibles(cantidad)
    await interaction.response.send_message(f"Se han establecido {cantidad:.2f} USD disponibles.")

@bot.tree.command(name="getusd", description="Muestra la cantidad de USD disponibles (solo admin).")
async def getusd(interaction: discord.Interaction):
  """Muestra la cantidad de USD disponibles (solo para administradores)."""
  if not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message("¡Solo los administradores pueden usar este comando!", ephemeral=True)
    return
  usd_disponibles = obtener_usd_disponibles()
  if usd_disponibles is None:
    await interaction.response.send_message("Error al obtener los USD disponibles. Inténtalo de nuevo más tarde.", ephemeral=True)
    return

  await interaction.response.send_message(f"USD disponibles: {usd_disponibles:.2f}")

#Comando para actualizar la tasa de cambio (solo admin)
@bot.command(name="actualizar_tasa")
async def actualizar_tasa(ctx):
    """Actualiza la tasa de cambio Bs a Dólar (solo para administradores)."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("¡Solo los administradores pueden usar este comando!")
        return

    global tasabsdolar
    tasabsdolar = await obtener_tasa_cambio()

    if tasabsdolar:
        await ctx.send(f"Tasa de cambio actualizada: 1 USD = {tasabsdolar} VES")
    else:
        await ctx.send("No se pudo actualizar la tasa de cambio. Revisa la API.")

# ------------------- Tareas en Segundo Plano -------------------

@tasks.loop(minutes=15)
async def actualizar_tasa_periodicamente():
    """Actualiza la tasa de cambio cada 15 minutos."""
    global tasabsdolar
    nueva_tasa = await obtener_tasa_cambio()
    if nueva_tasa and nueva_tasa != tasabsdolar:
        tasabsdolar = nueva_tasa
        print(f"Tasa de cambio actualizada (tarea en segundo plano): 1 USD = {tasabsdolar:.2f} VES")

@tasks.loop(minutes=5)
async def cambiar_presencia():
    """Cambia la presencia del bot cada 5 minutos."""
    usd_disponibles = obtener_usd_disponibles()
    if usd_disponibles is None:
      usd_disponibles = "Error"
    else:
      usd_disponibles = f"{usd_disponibles:.2f}"
    statuses = [
        f"USD Disp: {usd_disponibles}",
        "Usando /bal",
        "Hecho con Python",
        f"Tasa: {tasabsdolar:.2f} VES" if tasabsdolar else "Cargando Tasa..."
    ]
    await bot.change_presence(activity=discord.Game(random.choice(statuses)))


# ------------------- Eventos -------------------

@bot.event
async def on_ready():
    """Se ejecuta cuando el bot está listo."""
    print(f'Bot conectado como {bot.user.name}')

    # Sincroniza los comandos slash
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error al sincronizar comandos: {e}")

    # Carga la tasa de cambio inicial
    global tasabsdolar
    tasabsdolar = await obtener_tasa_cambio()
    if tasabsdolar:
        print(f"Tasa de cambio inicial: 1 USD = {tasabsdolar:.2f} VES")
    else:
        print("No se pudo obtener la tasa de cambio al inicio.")

    # Inicia las tareas en segundo plano
    actualizar_tasa_periodicamente.start()
    cambiar_presencia.start()

    # Crea las tablas de la base de datos si no existen
    crear_tablas()

# ------------------- Ejecución del Bot -------------------

if __name__ == "__main__":
    # Carga los comandos (si tienes comandos en archivos separados)
    # bot.load_extension("cogs.comandos_economia")
    # bot.load_extension("cogs.comandos_admin")

    # Inicia el bot
    bot.run(TOKEN)
