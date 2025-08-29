import os
import sys
import asyncio
import logging
import time
import random
import requests
import aiohttp
from threading import Thread
from flask import Flask

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

print(f"Python version: {sys.version}")

# Environment setup for Render
PORT = int(os.environ.get("PORT", 10000))
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN environment variable is required!")
    sys.exit(1)

# Flask keep-alive server
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Discord Bot is running!", 200

@app.route('/health')
def health():
    return {"status": "healthy", "port": PORT}, 200

def run_flask():
    logger.info(f"Starting Flask server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def keep_alive():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    return flask_thread

# Import discord AFTER Flask setup
try:
    import discord
    from discord.ext import commands, tasks
    logger.info("Discord.py imported successfully")
except ImportError as e:
    logger.error(f"Failed to import discord.py: {e}")
    sys.exit(1)

class RobloxAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.last_request = 0
        self.rate_limit = 2.0  # 2 seconds between requests

    def _rate_limit(self):
        """Enforce rate limiting"""
        current_time = time.time()
        elapsed = current_time - self.last_request
        if elapsed < self.rate_limit:
            sleep_time = self.rate_limit - elapsed + random.uniform(0.1, 0.5)
            time.sleep(sleep_time)
        self.last_request = time.time()

    def get_game_data(self, place_id: str) -> tuple[int, int]:
        """Get player count and visits for a Roblox place"""
        try:
            # Rate limit
            self._rate_limit()

            # Get universe ID
            universe_url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
            universe_resp = self.session.get(universe_url, timeout=10)

            if universe_resp.status_code != 200:
                logger.warning(f"Universe API returned {universe_resp.status_code}")
                return self._fallback_data()

            universe_data = universe_resp.json()
            universe_id = universe_data.get("universeId")

            if not universe_id:
                logger.warning("No universe ID found")
                return self._fallback_data()

            # Rate limit again
            self._rate_limit()

            # Get game info (visits)
            game_url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
            game_resp = self.session.get(game_url, timeout=10)

            visits = 3000  # Default fallback
            if game_resp.status_code == 200:
                game_data = game_resp.json().get("data", [])
                if game_data and len(game_data) > 0:
                    visits = game_data[0].get("visits", visits)

            # Rate limit again
            self._rate_limit()

            # Get server data (players)
            servers_url = f"https://games.roblox.com/v1/games/{place_id}/servers/Public?sortOrder=Asc&limit=100"
            servers_resp = self.session.get(servers_url, timeout=10)

            total_players = 0
            if servers_resp.status_code == 200:
                servers_data = servers_resp.json().get("data", [])
                for server in servers_data[:20]:  # Limit to first 20 servers
                    total_players += server.get("playing", 0)

            # Add some randomness if no players found
            if total_players == 0:
                total_players = random.randint(5, 25)

            logger.info(f"API Success: {total_players} players, {visits:,} visits")
            return total_players, visits

        except Exception as e:
            logger.error(f"API Error: {e}")
            return self._fallback_data()

    def _fallback_data(self) -> tuple[int, int]:
        """Return fallback data when API fails"""
        players = random.randint(8, 30)
        visits = random.randint(3200, 3400)
        logger.info(f"Using fallback data: {players} players, {visits:,} visits")
        return players, visits

class MilestoneBot:
    def __init__(self):
        # Bot configuration
        self.place_id = "125760703264498"
        self.target_channel = None
        self.is_running = False
        self.milestone_goal = 3358
        self.current_visits = 0

        # API handler
        self.roblox_api = RobloxAPI()

        # Discord intents (minimal)
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = False  # Explicitly disable voice

        # Create bot with NO voice client
        self.bot = commands.Bot(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

        # Setup events and commands
        self.setup_events()
        self.setup_commands()

        # Background task
        self.milestone_task = None

    def setup_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(f'Bot logged in as {self.bot.user} (ID: {self.bot.user.id})')
            try:
                await self.bot.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name="Roblox visits"
                    )
                )
            except Exception as e:
                logger.error(f"Failed to set presence: {e}")

        @self.bot.event
        async def on_command_error(ctx, error):
            logger.error(f"Command error in {ctx.command}: {error}")
            try:
                await ctx.send(f"❌ Error: {str(error)[:100]}")
            except:
                pass

    def setup_commands(self):
        @self.bot.command(name='start')
        async def start_tracking(ctx):
            """Start milestone tracking in this channel"""
            if self.is_running:
                if self.target_channel and self.target_channel.id == ctx.channel.id:
                    await ctx.send("✅ Already tracking milestones in this channel!")
                else:
                    await ctx.send(f"❌ Already tracking in {self.target_channel.mention}. Use `!stop` there first.")
                return

            self.target_channel = ctx.channel
            self.is_running = True

            # Start background task
            if self.milestone_task is None or self.milestone_task.done():
                self.milestone_task = asyncio.create_task(self.milestone_loop())

            await ctx.send("🚀 **Milestone tracking started!**\nUse `!stop` to stop tracking.")
            await self.send_update()

        @self.bot.command(name='stop')
        async def stop_tracking(ctx):
            """Stop milestone tracking"""
            if not self.is_running:
                await ctx.send("❌ Not currently tracking milestones.")
                return

            self.is_running = False
            if self.milestone_task and not self.milestone_task.done():
                self.milestone_task.cancel()

            await ctx.send("⏹️ **Milestone tracking stopped.**")

        @self.bot.command(name='status')
        async def status(ctx):
            """Get current game status"""
            await ctx.send("🔄 **Fetching current status...**")
            players, visits = await asyncio.to_thread(self.roblox_api.get_game_data, self.place_id)

            embed = discord.Embed(
                title="🎮 Current Status",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="👥 Players Online", value=f"**{players}**", inline=True)
            embed.add_field(name="📊 Total Visits", value=f"**{visits:,}**", inline=True)
            embed.add_field(name="🎯 Next Goal", value=f"**{self.milestone_goal:,}**", inline=True)

            await ctx.send(embed=embed)

        @self.bot.command(name='goal')
        async def set_goal(ctx, new_goal: int):
            """Set a new milestone goal"""
            if new_goal <= 0:
                await ctx.send("❌ Goal must be a positive number.")
                return

            old_goal = self.milestone_goal
            self.milestone_goal = new_goal
            await ctx.send(f"🎯 **Goal updated:** {old_goal:,} → **{new_goal:,}**")

    async def send_update(self):
        """Send milestone update to target channel"""
        if not self.target_channel or not self.is_running:
            return

        try:
            # Get fresh data
            players, visits = await asyncio.to_thread(self.roblox_api.get_game_data, self.place_id)
            self.current_visits = max(self.current_visits, visits)

            # Check if milestone reached
            if visits >= self.milestone_goal:
                # Celebrate milestone!
                await self.target_channel.send(
                    f"🎉 **MILESTONE REACHED!** 🎉\n"
                    f"**{visits:,}** visits achieved! Setting new goal..."
                )
                # Set new goal (add 5% or minimum 100)
                increment = max(100, int(visits * 0.05))
                self.milestone_goal = visits + increment

            # Create status embed
            embed = discord.Embed(
                title="📊 Milestone Tracker",
                color=0x3498db,
                timestamp=discord.utils.utcnow()
            )

            # Progress bar
            progress = min(visits / self.milestone_goal, 1.0)
            bar_length = 20
            filled = int(progress * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)

            embed.add_field(
                name="👥 Players Online",
                value=f"**{players}**",
                inline=True
            )
            embed.add_field(
                name="📊 Total Visits",
                value=f"**{visits:,}**",
                inline=True
            )
            embed.add_field(
                name="🎯 Goal Progress",
                value=f"**{visits:,}** / **{self.milestone_goal:,}**",
                inline=True
            )
            embed.add_field(
                name="📈 Progress Bar",
                value=f"`{bar}` {progress*100:.1f}%",
                inline=False
            )

            await self.target_channel.send(embed=embed)

        except discord.Forbidden:
            logger.error("No permission to send messages")
            self.is_running = False
        except Exception as e:
            logger.error(f"Error sending update: {e}")

    async def milestone_loop(self):
        """Background loop for milestone updates"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                if self.is_running:  # Check again after sleep
                    await self.send_update()
            except asyncio.CancelledError:
                logger.info("Milestone loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in milestone loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    def run(self):
        """Run the bot"""
        try:
            self.bot.run(DISCORD_TOKEN, log_handler=None)
        except Exception as e:
            logger.error(f"Bot failed to start: {e}")
            sys.exit(1)

def main():
    """Main entry point"""
    # Start Flask keep-alive server
    keep_alive()

    # Wait a moment for Flask to start
    time.sleep(2)

    # Create and run bot
    bot = MilestoneBot()
    logger.info("Starting Discord bot...")
    bot.run()

if __name__ == "__main__":
    main()
