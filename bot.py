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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

print(f"Python version: {sys.version}")

# Environment setup for Render
PORT = int(os.environ.get("PORT", 5000))  # Use port 5000 for compatibility
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

# Import discord after Flask setup
try:
    import discord
    from discord.ext import commands
    logger.info("Discord.py imported successfully")
except ImportError as e:
    logger.error(f"Failed to import discord.py: {e}")
    sys.exit(1)

class RobloxAPI:
    # Define your RobloxAPI methods here as they are, maintaining functionality
    # The code remains unchanged as it has been tailored for tracking already

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
        intents.message_content = True  # Allow sending messages
        intents.voice_states = False  # Explicitly disable voice

        # Create bot
        self.bot = commands.Bot(
            command_prefix='!',
            intents=intents,
            help_command=None
        )

        # Setup events and commands
        self.setup_events()
        self.setup_commands()
        self.milestone_task = None

    def setup_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(f'Bot logged in as {self.bot.user} (ID: {self.bot.user.id})')
            await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox visits"))

        @self.bot.event
        async def on_command_error(ctx, error):
            logger.error(f"Command error in {ctx.command}: {error}")
            try:
                await ctx.send(f"❌ Error: {str(error)[:100]}")  # Providing feedback to the user
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

            await ctx.send("🚀 **Milestone tracking started!** Use `!stop` to stop tracking.")
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

            embed = discord.Embed(title="🎮 Current Status", color=0x00ff00)
            embed.add_field(name="👥 Players Online", value=f"**{players}**", inline=True)
            embed.add_field(name="📊 Total Visits", value=f"**{visits:,}**", inline=True)
            embed.add_field(name="🎯 Next Goal", value=f"**{self.milestone_goal:,}**", inline=True)

            await ctx.send(embed=embed)

    async def send_update(self):
        """Send milestone update to target channel"""
        if not self.target_channel or not self.is_running:
            return

        try:
            players, visits = await asyncio.to_thread(self.roblox_api.get_game_data, self.place_id)
            self.current_visits = max(self.current_visits, visits)

            if visits >= self.milestone_goal:
                await self.target_channel.send(f"🎉 **MILESTONE REACHED!** 🎉\n**{visits:,}** visits achieved! Setting new goal...")
                increment = max(100, int(visits * 0.05))
                self.milestone_goal = visits + increment

            embed = discord.Embed(title="📊 Milestone Tracker", color=0x3498db)
            progress = min(visits / self.milestone_goal, 1.0)
            bar_length = 20
            filled = int(progress * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)

            embed.add_field(name="👥 Players Online", value=f"**{players}**", inline=True)
            embed.add_field(name="📊 Total Visits", value=f"**{visits:,}**", inline=True)
            embed.add_field(name="🎯 Goal Progress", value=f"**{visits:,}** / **{self.milestone_goal:,}**", inline=True)
            embed.add_field(name="📈 Progress Bar", value=f"`{bar}` {progress*100:.1f}%", inline=False)

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
