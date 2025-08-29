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
PORT = int(os.environ.get("PORT", 5000))  # Use port 5000
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
    from discord.ext import commands
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

            # API calls (same as before)
            # ...

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
        # Initialization details (same as before)
        # ...

    def setup_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(f'Bot logged in as {self.bot.user} (ID: {self.bot.user.id})')
            # ...

    def setup_commands(self):
        @self.bot.command(name='start')
        async def start_tracking(ctx):
            """Start milestone tracking in this channel"""
            # ...

        @self.bot.command(name='stop')
        async def stop_tracking(ctx):
            """Stop milestone tracking"""
            # ...

        @self.bot.command(name='status')
        async def status(ctx):
            """Get current game status"""
            # ...

        @self.bot.command(name='goal')
        async def set_goal(ctx, new_goal: int):
            """Set a new milestone goal"""
            # ...

    async def send_update(self):
        """Send milestone update to target channel"""
        # ...

    async def milestone_loop(self):
        """Background loop for milestone updates"""
        # ...

    def run(self):
        """Run the bot"""
        try:
            self.bot.run(DISCORD_TOKEN, log_handler=None)
        except Exception as e:
            logger.error(f"Bot failed to start: {e}")
            sys.exit(1)

def main():
    """Main entry point"""
    keep_alive()  # Start the Flask server
    time.sleep(2)  # Delay to ensure Flask is running
    bot = MilestoneBot()  # Create the bot instance
    logger.info("Starting Discord bot...")
    bot.run()  # Run the bot

if __name__ == "__main__":
    main()
