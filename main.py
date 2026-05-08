import os
import discord
import random
import asyncio
import json
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
from typing import Dict, List, Set, Optional
from enum import Enum

# --- CONFIGURACIÓN ---
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = '!'
COLOR_PRIMARY = 0xE91E63  # Rosa Bingo
COLOR_SECONDARY = 0x9C27B0  # Púrpura
COLOR_WIN = 0xFFD700  # Dorado

# --- ESTADOS DEL JUEGO ---
class GameState(Enum):
    WAITING = "esperando"
    ACTIVE = "activo"
    COMPLETED = "terminado"

class BingoCard:
    """Representa una tarjeta de Bingo 5x5"""
    
    def __init__(self, card_id: int, user_id: int):
        self.card_id = card_id
        self.user_id = user_id
        self.numbers = self._generate_card()
        self.marked = [[False] * 5 for _ in range(5)]
        self.bingo = False
    
    def _generate_card(self) -> List[List[int]]:
        """Genera una tarjeta de bingo válida 5x5"""
        card = []
        
        # Columnas B - I - N - G - O
        ranges = [
            (1, 15),   # B
            (16, 30),  # I
            (31, 45),  # N
            (46, 60),  # G
            (61, 75)   # O
        ]
        
        for col, (min_num, max_num) in enumerate(ranges):
            column_nums = random.sample(range(min_num, max_num + 1), 5)
            for row in range(5):
                if len(card) <= row:
                    card.append([0] * 5)
                card[row][col] = column_nums[row]
        
        # Espacio gratis en el centro
        card[2][2] = "⭐"
        self.marked[2][2] = True
        
        return card
    
    def mark_number(self, number: int) -> bool:
        """Marca un número en la tarjeta si existe"""
        for row in range(5):
            for col in range(5):
                if self.numbers[row][col] == number:
                    self.marked[row][col] = True
                    return True
        return False
    
    def check_bingo(self) -> bool:
        """Verifica si la tarjeta tiene bingo"""
        # Verificar filas
        for row in range(5):
            if all(self.marked[row][col] for col in range(5)):
                self.bingo = True
                return True
        
        # Verificar columnas
        for col in range(5):
            if all(self.marked[row][col] for row in range(5)):
                self.bingo = True
                return True
        
        # Verificar diagonales
        if all(self.marked[i][i] for i in range(5)):
            self.bingo = True
            return True
        
        if all(self.marked[i][4-i] for i in range(5)):
            self.bingo = True
            return True
        
        return False
    
    def get_progress(self) -> int:
        """Obtiene el porcentaje de progreso"""
        marked_count = sum(sum(row) for row in self.marked)
        return int((marked_count / 25) * 100)
    
    def to_discord_embed(self, username: str) -> discord.Embed:
        """Convierte la tarjeta a un embed de Discord"""
        embed = discord.Embed(
            title=f"🎯 Tarjeta de Bingo - {username}",
            color=COLOR_PRIMARY
        )
        
        # Construir representación de la tarjeta
        card_text = "`"
        # Cabeceras
        card_text += "   B    I    N    G    O   \n"
        card_text += "┌────┬────┬────┬────┬────┐\n"
        
        for row in range(5):
            row_text = ""
            for col in range(5):
                value = self.numbers[row][col]
                marked = self.marked[row][col]
                
                if value == "⭐":
                    display = "⭐"
                else:
                    display = str(value).zfill(2)
                
                if marked:
                    display = f"**{display}**"
                
                row_text += f"│ {display} "
            
            card_text += row_text + "│\n"
            if row < 4:
                card_text += "├────┼────┼────┼────┼────┤\n"
        
        card_text += "└────┴────┴────┴────┴────┘`"
        
        embed.description = card_text
        embed.add_field(
            name="📊 Progreso",
            value=f"`{'█' * (self.get_progress() // 5)}{'░' * (20 - self.get_progress() // 5)}` {self.get_progress()}%",
            inline=False
        )
        
        embed.set_footer(text=f"ID: {self.card_id} | ¡Marca tus números!")
        return embed

class BingoGame:
    """Maneja la lógica de una partida de Bingo"""
    
    def __init__(self, channel_id: int, host_id: int):
        self.channel_id = channel_id
        self.host_id = host_id
        self.state = GameState.WAITING
        self.players: Dict[int, BingoCard] = {}  # user_id -> BingoCard
        self.drawn_numbers: List[int] = []
        self.current_number: Optional[int] = None
        self.winners: List[int] = []
        self.created_at = datetime.now()
        self.last_number_time: Optional[datetime] = None
    
    def add_player(self, user_id: int) -> Optional[BingoCard]:
        """Agrega un jugador a la partida"""
        if user_id in self.players:
            return None
        
        if len(self.players) >= 20:
            return None
        
        card_id = len(self.players) + 1
        card = BingoCard(card_id, user_id)
        self.players[user_id] = card
        return card
    
    def remove_player(self, user_id: int) -> bool:
        """Elimina un jugador"""
        if user_id in self.players:
            del self.players[user_id]
            return True
        return False
    
    def draw_number(self) -> Optional[int]:
        """Saca un nuevo número"""
        if len(self.drawn_numbers) >= 75:
            return None
        
        available = [n for n in range(1, 76) if n not in self.drawn_numbers]
        if not available:
            return None
        
        number = random.choice(available)
        self.drawn_numbers.append(number)
        self.current_number = number
        self.last_number_time = datetime.now()
        
        # Marcar número en todas las tarjetas
        for player_id, card in self.players.items():
            card.mark_number(number)
            
            # Verificar si alguien ganó
            if not card.bingo and card.check_bingo():
                self.winners.append(player_id)
        
        return number
    
    def get_letter_for_number(self, number: int) -> str:
        """Obtiene la letra correspondiente al número"""
        if 1 <= number <= 15:
            return "B"
        elif 16 <= number <= 30:
            return "I"
        elif 31 <= number <= 45:
            return "N"
        elif 46 <= number <= 60:
            return "G"
        else:
            return "O"
    
    def get_embed_status(self) -> discord.Embed:
        """Obtiene el embed del estado del juego"""
        embed = discord.Embed(
            title="🎮 Sala de Bingo",
            color=COLOR_SECONDARY if self.state == GameState.WAITING else COLOR_PRIMARY,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📊 Estado",
            value=f"`{self.state.value.upper()}`",
            inline=True
        )
        
        embed.add_field(
            name="👥 Jugadores",
            value=f"`{len(self.players)}/20`",
            inline=True
        )
        
        if self.state == GameState.ACTIVE:
            embed.add_field(
                name="🎲 Números sorteados",
                value=f"`{len(self.drawn_numbers)}/75`",
                inline=True
            )
            
            if self.current_number:
                letter = self.get_letter_for_number(self.current_number)
                embed.add_field(
                    name="🔢 Último número",
                    value=f"`{letter}-{self.current_number}`",
                    inline=True
                )
            
            # Mostrar últimos 10 números
            if self.drawn_numbers:
                last_numbers = self.drawn_numbers[-10:][::-1]
                numbers_text = " ".join([f"`{self.get_letter_for_number(n)}{n}`" for n in last_numbers])
                embed.add_field(
                    name="📝 Últimos números",
                    value=numbers_text,
                    inline=False
                )
        
        elif self.state == GameState.WAITING:
            embed.add_field(
                name="⏳ Esperando jugadores",
                value="Usa `/bingo unirse` para participar\nUsa `/bingo iniciar` para empezar",
                inline=False
            )
        
        if self.winners:
            embed.add_field(
                name="🏆 Ganadores",
                value=f"`{len(self.winners)} jugador(es) han cantado BINGO!`",
                inline=False
            )
        
        embed.set_footer(text=f"Sala creada • {self.created_at.strftime('%H:%M')}")
        return embed

# --- BOT PRINCIPAL ---
class BingoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=PREFIX, intents=intents)
        self.games: Dict[int, BingoGame] = {}  # channel_id -> BingoGame
        self.number_tasks: Dict[int, asyncio.Task] = {}  # channel_id -> task
    
    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Comandos sincronizados")
        self.auto_end_games.start()
    
    @tasks.loop(minutes=5)
    async def auto_end_games(self):
        """Termina automáticamente juegos inactivos"""
        for channel_id, game in list(self.games.items()):
            if game.state == GameState.WAITING:
                time_elapsed = datetime.now() - game.created_at
                if time_elapsed > timedelta(minutes=10):
                    channel = self.get_channel(channel_id)
                    if channel:
                        await channel.send("⏰ **Sala cerrada por inactividad**")
                    del self.games[channel_id]
                    
                    if channel_id in self.number_tasks:
                        self.number_tasks[channel_id].cancel()
                        del self.number_tasks[channel_id]
    
    async def start_number_drawer(self, channel_id: int, game: BingoGame):
        """Maneja el sorteo automático de números"""
        await asyncio.sleep(5)  # Pausa inicial
        
        while game.state == GameState.ACTIVE and len(game.drawn_numbers) < 75:
            number = game.draw_number()
            channel = self.get_channel(channel_id)
            
            if number and channel:
                letter = game.get_letter_for_number(number)
                embed = discord.Embed(
                    title=f"🎲 Número {letter}-{number}",
                    description=f"¡Ha salido el **{letter}-{number}**!",
                    color=COLOR_PRIMARY
                )
                
                # Mostrar estadísticas
                embed.add_field(
                    name="📊 Progreso",
                    value=f"`{len(game.drawn_numbers)}/75` números sorteados",
                    inline=True
                )
                
                if len(game.drawn_numbers) >= 50:
                    embed.set_footer(text="🎯 ¡El juego está en su recta final!")
                
                await channel.send(embed=embed)
                
                # Verificar ganadores
                if game.winners:
                    await self.end_game(channel_id, game)
                    break
            
            # Esperar entre números (configurable)
            await asyncio.sleep(8)
        
        # Si se terminaron los números sin ganador
        if game.state == GameState.ACTIVE and len(game.drawn_numbers) >= 75:
            await self.end_game(channel_id, game, force=True)
    
    async def end_game(self, channel_id: int, game: BingoGame, force: bool = False):
        """Termina el juego actual"""
        game.state = GameState.COMPLETED
        
        channel = self.get_channel(channel_id)
        if not channel:
            return
        
        embed = discord.Embed(
            title="🏆 **¡BINGO!**" if game.winners else "🎮 **Juego Terminado**",
            color=COLOR_WIN if game.winners else COLOR_SECONDARY
        )
        
        if game.winners:
            winners_text = []
            for winner_id in game.winners:
                user = channel.guild.get_member(winner_id)
                if user:
                    winners_text.append(f"{user.mention} 🎉")
            
            embed.description = f"**¡Felicidades a los ganadores!**\n\n" + "\n".join(winners_text)
            embed.add_field(
                name="📊 Estadísticas finales",
                value=f"• Números sorteados: `{len(game.drawn_numbers)}`\n• Jugadores: `{len(game.players)}`\n• Tarjetas activas: `{len(game.players)}`",
                inline=False
            )
        else:
            embed.description = "**¡El juego ha terminado sin ganadores!**"
            embed.add_field(
                name="📊 Estadísticas",
                value=f"• Números sorteados: `{len(game.drawn_numbers)}/75`\n• Jugadores participantes: `{len(game.players)}`",
                inline=False
            )
        
        # Mostrar ganadores con más detalle
        if game.winners:
            top_cards = []
            for winner_id in game.winners[:3]:
                card = game.players.get(winner_id)
                if card:
                    user = channel.guild.get_member(winner_id)
                    top_cards.append(f"**{user.display_name if user else winner_id}** - {card.get_progress()}% completado")
            
            if top_cards:
                embed.add_field(name="🎯 Top jugadores", value="\n".join(top_cards), inline=False)
        
        embed.set_footer(text="¡Gracias por jugar!")
        await channel.send(embed=embed)
        
        # Limpiar juego
        if channel_id in self.number_tasks:
            self.number_tasks[channel_id].cancel()
            del self.number_tasks[channel_id]
        
        del self.games[channel_id]

bot = BingoBot()

# --- COMANDOS SLASH ---

@bot.tree.command(name="bingo", description="🎮 Crea una nueva sala de bingo")
async def bingo_create(interaction: discord.Interaction):
    """Crea una nueva sala de bingo en el canal"""
    
    if interaction.channel_id in bot.games:
        await interaction.response.send_message(
            "❌ Ya hay un juego activo en este canal. Espera a que termine.",
            ephemeral=True
        )
        return
    
    game = BingoGame(interaction.channel_id, interaction.user.id)
    bot.games[interaction.channel_id] = game
    
    embed = game.get_embed_status()
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url)
    
    await interaction.response.send_message(embed=embed)
    await interaction.followup.send(
        "🎯 **¡Sala de Bingo creada!**\n"
        "• Usa `/bingo unirse` para obtener una tarjeta\n"
        "• Usa `/bingo iniciar` para empezar la partida\n"
        "• Usa `/bingo salir` para abandonar la sala",
        ephemeral=True
    )

@bot.tree.command(name="unirse", description="🎮 Únete a la partida de bingo actual")
async def bingo_join(interaction: discord.Interaction):
    """Únete a la partida de bingo"""
    
    game = bot.games.get(interaction.channel_id)
    
    if not game:
        await interaction.response.send_message(
            "❌ No hay ninguna sala de bingo activa en este canal.\nUsa `/bingo` para crear una.",
            ephemeral=True
        )
        return
    
    if game.state != GameState.WAITING:
        await interaction.response.send_message(
            "❌ La partida ya comenzó. Espera a la siguiente ronda.",
            ephemeral=True
        )
        return
    
    if interaction.user.id in game.players:
        await interaction.response.send_message(
            "❌ Ya tienes una tarjeta en esta partida.",
            ephemeral=True
        )
        return
    
    card = game.add_player(interaction.user.id)
    
    if not card:
        await interaction.response.send_message(
            "❌ La sala está llena (máximo 20 jugadores).",
            ephemeral=True
        )
        return
    
    embed = card.to_discord_embed(interaction.user.display_name)
    await interaction.response.send_message(
        f"✅ **¡Bienvenido {interaction.user.mention}!** Tu tarjeta está lista.",
        embed=embed
    )
    
    # Actualizar embed del juego
    game_embed = game.get_embed_status()
    await interaction.channel.send(embed=game_embed)

@bot.tree.command(name="salir", description="🎮 Abandona la partida actual")
async def bingo_leave(interaction: discord.Interaction):
    """Abandona la partida actual"""
    
    game = bot.games.get(interaction.channel_id)
    
    if not game:
        await interaction.response.send_message(
            "❌ No hay ninguna sala de bingo activa.",
            ephemeral=True
        )
        return
    
    if game.state != GameState.WAITING:
        await interaction.response.send_message(
            "❌ No puedes salir de una partida en curso.",
            ephemeral=True
        )
        return
    
    if game.remove_player(interaction.user.id):
        await interaction.response.send_message(
            f"👋 {interaction.user.mention} ha abandonado la sala.",
            ephemeral=False
        )
        
        # Si no quedan jugadores, cerrar sala
        if len(game.players) == 0:
            await interaction.channel.send("⏰ **Sala cerrada por falta de jugadores**")
            del bot.games[interaction.channel_id]
    else:
        await interaction.response.send_message(
            "❌ No estás en esta partida.",
            ephemeral=True
        )

@bot.tree.command(name="iniciar", description="🎮 Inicia la partida de bingo")
async def bingo_start(interaction: discord.Interaction):
    """Inicia la partida de bingo"""
    
    game = bot.games.get(interaction.channel_id)
    
    if not game:
        await interaction.response.send_message(
            "❌ No hay ninguna sala de bingo activa.",
            ephemeral=True
        )
        return
    
    if game.state != GameState.WAITING:
        await interaction.response.send_message(
            "❌ La partida ya está en curso o ha terminado.",
            ephemeral=True
        )
        return
    
    if interaction.user.id != game.host_id:
        await interaction.response.send_message(
            "❌ Solo el creador de la sala puede iniciar la partida.",
            ephemeral=True
        )
        return
    
    if len(game.players) < 1:
        await interaction.response.send_message(
            "❌ Debe haber al menos 1 jugador para iniciar.",
            ephemeral=True
        )
        return
    
    game.state = GameState.ACTIVE
    
    embed = discord.Embed(
        title="🎮 **¡La partida ha comenzado!**",
        description=f"Participantes: **{len(game.players)}** jugadores\n"
                   f"¡Buena suerte a todos! 🍀",
        color=COLOR_PRIMARY
    )
    
    # Lista de jugadores
    players_list = []
    for user_id in game.players.keys():
        user = interaction.guild.get_member(user_id)
        if user:
            players_list.append(f"• {user.display_name}")
    
    if players_list:
        embed.add_field(name="👥 Jugadores", value="\n".join(players_list[:10]), inline=False)
        if len(players_list) > 10:
            embed.add_field(name="...", value=f"y {len(players_list) - 10} más", inline=False)
    
    await interaction.response.send_message(embed=embed)
    
    # Iniciar el sorteador de números
    task = asyncio.create_task(bot.start_number_drawer(interaction.channel_id, game))
    bot.number_tasks[interaction.channel_id] = task

@bot.tree.command(name="bingo", description="🎮 ¡Canta bingo cuando completes tu tarjeta!")
async def bingo_call(interaction: discord.Interaction):
    """Canta bingo para reclamar la victoria"""
    
    game = bot.games.get(interaction.channel_id)
    
    if not game:
        await interaction.response.send_message(
            "❌ No hay ninguna partida activa.",
            ephemeral=True
        )
        return
    
    if game.state != GameState.ACTIVE:
        await interaction.response.send_message(
            "❌ No hay una partida en curso.",
            ephemeral=True
        )
        return
    
    if interaction.user.id not in game.players:
        await interaction.response.send_message(
            "❌ No estás participando en esta partida.",
            ephemeral=True
        )
        return
    
    card = game.players[interaction.user.id]
    
    if card.bingo:
        await interaction.response.send_message(
            "❌ Ya has cantado bingo en esta partida.",
            ephemeral=True
        )
        return
    
    if card.check_bingo():
        if interaction.user.id not in game.winners:
            game.winners.append(interaction.user.id)
        
        embed = discord.Embed(
            title="🎉 **¡BINGO!** 🎉",
            description=f"**{interaction.user.mention} ha cantado BINGO!**",
            color=COLOR_WIN
        )
        
        # Mostrar tarjeta ganadora
        card_display = "```\n"
        for row in range(5):
            row_text = ""
            for col in range(5):
                value = card.numbers[row][col]
                if value == "⭐":
                    row_text += " ⭐ "
                else:
                    marked = "✔" if card.marked[row][col] else " "
                    row_text += f"{marked}{str(value).zfill(2)}{marked} "
            card_display += row_text + "\n"
        card_display += "```"
        
        embed.add_field(name="🏆 Tarjeta ganadora", value=card_display, inline=False)
        embed.add_field(
            name="📊 Progreso final",
            value=f"✅ {card.get_progress()}% completado",
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Terminar el juego después de un momento
        await asyncio.sleep(3)
        await bot.end_game(interaction.channel_id, game)
    else:
        await interaction.response.send_message(
            "❌ **¡No es BINGO aún!** Sigue marcando tus números.",
            ephemeral=True
        )
        
        # Mostrar progreso actual
        embed = card.to_discord_embed(interaction.user.display_name)
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="tarjeta", description="🎮 Muestra tu tarjeta de bingo actual")
async def show_card(interaction: discord.Interaction):
    """Muestra la tarjeta del jugador"""
    
    game = bot.games.get(interaction.channel_id)
    
    if not game or game.state != GameState.ACTIVE:
        await interaction.response.send_message(
            "❌ No hay una partida activa.",
            ephemeral=True
        )
        return
    
    if interaction.user.id not in game.players:
        await interaction.response.send_message(
            "❌ No estás participando en esta partida.",
            ephemeral=True
        )
        return
    
    card = game.players[interaction.user.id]
    embed = card.to_discord_embed(interaction.user.display_name)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="estado", description="🎮 Muestra el estado actual de la partida")
async def game_status(interaction: discord.Interaction):
    """Muestra el estado actual del juego"""
    
    game = bot.games.get(interaction.channel_id)
    
    if not game:
        await interaction.response.send_message(
            "❌ No hay ninguna partida activa.",
            ephemeral=True
        )
        return
    
    embed = game.get_embed_status()
    
    # Agregar lista de jugadores
    if game.players:
        players_text = []
        for user_id, card in list(game.players.items())[:10]:
            user = interaction.guild.get_member(user_id)
            if user:
                progress = card.get_progress()
                players_text.append(f"{user.display_name} - {progress}%")
        
        embed.add_field(name="👥 Jugadores", value="\n".join(players_text), inline=False)
        
        if len(game.players) > 10:
            embed.add_field(name="...", value=f"+ {len(game.players) - 10} más", inline=False)
    
    await interaction.response.send_message(embed=embed)

# --- EVENTOS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user} está listo para jugar BINGO!")
    print(f"📊 Comandos cargados: {len(bot.tree.get_commands())}")
    
    # Cambiar estado
    await bot.change_presence(
        activity=discord.Game(name="🎮 Bingo | /bingo"),
        status=discord.Status.online
    )

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Error: {error}")

# --- INICIO ---
if __name__ == "__main__":
    bot.run(TOKEN)

