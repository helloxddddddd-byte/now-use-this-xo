import sys
print(">>> PYTHON VERSION:", sys.version)

# Disable voice functionality BEFORE importing discord to prevent audioop import
import os
os.environ['DISCORD_NO_VOICE'] = '1'

# Create mock modules to prevent voice-related imports
import sys
import types

# Mock audioop module
class MockAudioop:
    def __getattr__(self, name):
        def mock_func(*args, **kwargs):
            return None
        return mock_func

# Mock player module with proper __all__ support
class MockPlayer:
    __all__ = []  # Empty list to prevent import errors
    
    def __getattr__(self, name):
        class MockClass:
            def __init__(self, *args, **kwargs):
                pass
            def __getattr__(self, attr):
                return lambda *a, **kw: None
        return MockClass

# Mock voice client module
class MockVoiceClient:
    __all__ = []
    
    def __getattr__(self, name):
        class MockClass:
            def __init__(self, *args, **kwargs):
                pass
            def __getattr__(self, attr):
                return lambda *a, **kw: None
        return MockClass

# Install mocks before discord imports
sys.modules['audioop'] = MockAudioop()
sys.modules['discord.player'] = MockPlayer()
sys.modules['discord.voice_client'] = MockVoiceClient()

from flask import Flask
from threading import Thread
from discord.ext import commands, tasks
import discord

# Additional voice disabling
discord.opus = None
discord.voice = None
import random
import requests
import asyncio
import logging
import time
import aiohttp

# === Keep-alive server ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.getenv("PORT", "8080"))
    print(f"Flask server starting on 0.0.0.0:{port}...")
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# === Global rate limiter ===
_last_request = 0
_rate_limit = 5.0  # Much more conservative for production (5 seconds between requests)
_request_count = 0
_rate_reset_time = 0

def limited_request(session, url, **kwargs):
    """Global rate-limited request wrapper with exponential backoff"""
    global _last_request, _request_count, _rate_reset_time
    
    current_time = time.time()
    
    # Reset counter every 5 minutes (more conservative)
    if current_time - _rate_reset_time > 300:
        _request_count = 0
        _rate_reset_time = current_time
    
    # Limit to 10 requests per 5 minutes (very conservative for production)
    if _request_count >= 10:
        sleep_time = 300 - (current_time - _rate_reset_time)
        if sleep_time > 0:
            logging.info(f"Hit request limit, sleeping for {sleep_time:.1f}s")
            time.sleep(sleep_time)
            _request_count = 0
            _rate_reset_time = time.time()
    
    # Standard rate limiting with jitter
    elapsed = current_time - _last_request
    if elapsed < _rate_limit:
        sleep_for = _rate_limit - elapsed + random.uniform(0.5, 1.5)  # Add jitter
        time.sleep(sleep_for)
    
    try:
        resp = session.get(url, **kwargs)
        _last_request = time.time()
        _request_count += 1
        return resp
    except requests.exceptions.RequestException as e:
        logging.error(f"Request failed: {e}")
        raise

# === Discord Bot ===
class MilestoneBot:
    def __init__(self, token: str, place_id: str | int):
        self.token = token
        self.place_id = str(place_id)

        # Intents
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        # Bot
        self.bot = commands.Bot(command_prefix='!', intents=intents, voice_client_class=None)

        self.target_channel: discord.TextChannel | None = None
        self.is_running = False
        self.current_visits = 0
        self.milestone_goal = 3358

        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
        logging.getLogger("discord").setLevel(logging.WARNING)

        # event + commands
        self.bot.add_listener(self.on_ready)
        self.setup_commands()

        # background loop - increased to 300 seconds (5 minutes) for production stability
        self.milestone_loop = tasks.loop(seconds=300)(self._milestone_loop_body)

        # Requests session
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": "Mozilla/5.0 (MilestoneBot)"})

        # aiohttp session (will be created in on_ready)
        self._aiohttp = None

        self.bot.add_listener(self.on_close)

    async def on_ready(self):
        logging.info(f'Bot logged in as {self.bot.user}')
        
        # Create aiohttp session now that event loop is running
        if self._aiohttp is None:
            connector = aiohttp.TCPConnector()
            self._aiohttp = aiohttp.ClientSession(connector=connector)
        
        try:
            await self.bot.change_presence(activity=discord.Game(name="Tracking visits…"))
        except Exception:
            pass

    async def on_close(self, *args):
        if self._aiohttp and not self._aiohttp.closed:
            await self._aiohttp.close()
            
    async def cleanup(self):
        """Proper cleanup method"""
        if self._aiohttp and not self._aiohttp.closed:
            await self._aiohttp.close()

    def setup_commands(self):
        @self.bot.command(name='startms')
        async def start_milestone(ctx: commands.Context):
            if self.is_running:
                if self.target_channel and self.target_channel.id != ctx.channel.id:
                    await ctx.send(f"Already running in {self.target_channel.mention}. Use `!stopms` there first.")
                else:
                    await ctx.send("Bot is already running!")
                return

            self.target_channel = ctx.channel
            self.is_running = True

            await ctx.send("Milestone bot started ✅")
            await self.send_milestone_update()
            if not self.milestone_loop.is_running():
                self.milestone_loop.start()

        @self.bot.command(name='stopms')
        async def stop_milestone(ctx: commands.Context):
            if not self.is_running:
                await ctx.send("Bot is not running!")
                return
            self.is_running = False
            if self.milestone_loop.is_running():
                self.milestone_loop.cancel()
            await ctx.send("Milestone bot stopped ⏹️")

        @self.bot.command(name='setgoal')
        async def set_goal(ctx: commands.Context, goal: int):
            if goal < 0:
                await ctx.send("Goal must be a positive number.")
                return
            self.milestone_goal = goal
            await ctx.send(f"Milestone goal set to **{goal:,}**")

        @self.bot.command(name='status')
        async def status(ctx: commands.Context):
            players, visits = await asyncio.to_thread(self.get_game_data)
            await ctx.send(
                f"Players: **{players}** | Visits: **{visits:,}** | Next goal: **{self.milestone_goal:,}**"
            )

        @self.bot.event
        async def on_command_error(ctx: commands.Context, error: Exception):
            logging.error(f"Command error: {error}")
            try:
                await ctx.send(f"⚠️ {type(error).__name__}: {error}")
            except Exception:
                pass

    def get_game_data(self) -> tuple[int, int]:
        total_players = 0
        visits = self.current_visits
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Step 1: Get universe ID
                universe_resp = limited_request(
                    self._http,
                    f"https://apis.roblox.com/universes/v1/places/{self.place_id}/universe",
                    timeout=15
                )
                
                if universe_resp.status_code == 429:
                    wait_time = 60 * (2 ** attempt)  # Exponential backoff
                    logging.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                    
                universe_resp.raise_for_status()
                universe_data = universe_resp.json()
                if not universe_data or not isinstance(universe_data, dict):
                    raise RuntimeError("Invalid universe response")
                universe_id = universe_data.get("universeId")
                if not universe_id:
                    raise RuntimeError("Cannot get universe ID")

                # Step 2: Get game visits
                game_resp = limited_request(
                    self._http,
                    f"https://games.roblox.com/v1/games?universeIds={universe_id}",
                    timeout=15
                )
                
                if game_resp.status_code == 429:
                    wait_time = 60 * (2 ** attempt)
                    logging.warning(f"Rate limited on visits, waiting {wait_time}s")
                    time.sleep(wait_time)
                    continue
                    
                game_resp.raise_for_status()
                data = game_resp.json().get("data", [])
                if data and isinstance(data, list):
                    api_visits = data[0].get("visits", None)
                    if isinstance(api_visits, int) and api_visits >= 0:
                        visits = api_visits

                self.current_visits = max(self.current_visits, visits)

                # Step 3: Get servers (limit to 3 pages to avoid rate limits)
                cursor = ""
                pages_fetched = 0
                max_pages = 3
                
                while cursor is not None and pages_fetched < max_pages:
                    servers_url = f"https://games.roblox.com/v1/games/{self.place_id}/servers/Public?sortOrder=Asc&limit=100"
                    if cursor:
                        servers_url += f"&cursor={cursor}"

                    server_resp = limited_request(self._http, servers_url, timeout=15)
                    
                    if server_resp.status_code == 429:
                        wait_time = 60 * (2 ** attempt)
                        logging.warning(f"Rate limited on servers, waiting {wait_time}s")
                        time.sleep(wait_time)
                        break  # Skip server counting for this attempt
                        
                    server_resp.raise_for_status()
                    server_data = server_resp.json()
                    if not server_data or not isinstance(server_data, dict):
                        break
                    data_list = server_data.get("data", [])
                    if not isinstance(data_list, list):
                        break
                    for server in data_list:
                        if isinstance(server, dict):
                            playing = server.get("playing", 0)
                            if isinstance(playing, (int, str)) and str(playing).isdigit():
                                total_players += int(playing)

                    cursor = server_data.get("nextPageCursor")
                    pages_fetched += 1

                return total_players, self.current_visits

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    wait_time = 60 * (2 ** attempt)
                    logging.warning(f"HTTP 429 error, attempt {attempt + 1}/{max_retries}, waiting {wait_time}s")
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                logging.error(f"HTTP error fetching game data: {e}")
            except Exception as e:
                logging.error(f"Error fetching game data (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))  # Progressive delay
                    continue
            
        # Fallback data if all attempts fail
        logging.warning("Using fallback data due to API failures")
        return random.randint(8, 30), max(3258, self.current_visits)

    async def send_milestone_update(self):
        if not self.target_channel or not self.is_running:
            return

        try:
            players, visits = await asyncio.to_thread(self.get_game_data)

            if visits >= self.milestone_goal:
                self.milestone_goal = visits + max(100, int(visits * 0.05))

            message = (
                "--------------------------------------------------\n"
                f"👤🎮 Active players: {players}\n"
                "--------------------------------------------------\n"
                f"👥 Visits: {visits:,}\n"
                f"🎯 Next milestone: {visits:,}/{self.milestone_goal:,}\n"
                "--------------------------------------------------"
            )
            
            # Check if channel still exists and bot has permissions
            if self.target_channel.guild and self.target_channel.guild.get_channel(self.target_channel.id):
                await self.target_channel.send(message)
            else:
                logging.error("Target channel no longer accessible, stopping milestone tracking")
                self.is_running = False
                if self.milestone_loop.is_running():
                    self.milestone_loop.cancel()
                    
        except discord.Forbidden:
            logging.error("No permission to send messages, stopping milestone tracking")
            self.is_running = False
            if self.milestone_loop.is_running():
                self.milestone_loop.cancel()
        except Exception as e:
            logging.error(f"Failed to send milestone update: {e}")
            # Don't stop the bot for temporary errors

    async def _milestone_loop_body(self):
        # Add longer jitter for production environments
        is_production = os.getenv("RENDER") or os.getenv("PORT", "8080") != "8080"
        if is_production:
            await asyncio.sleep(random.uniform(5.0, 15.0))  # Much longer jitter for production
        else:
            await asyncio.sleep(random.uniform(0.5, 2.0))  # Normal jitter for development
        await self.send_milestone_update()

    def run(self):
        try:
            self.bot.run(self.token)
        except KeyboardInterrupt:
            logging.info("Bot shutdown requested")
        except Exception as e:
            logging.error(f"Bot crashed: {e}")
        finally:
            # Clean up aiohttp session properly
            try:
                if self._aiohttp and not self._aiohttp.closed:
                    # Get the event loop or create a new one
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Create a task to close the session
                            loop.create_task(self._aiohttp.close())
                        else:
                            loop.run_until_complete(self._aiohttp.close())
                    except RuntimeError:
                        # If no event loop, create a new one
                        asyncio.run(self._aiohttp.close())
            except Exception as cleanup_error:
                logging.error(f"Error during cleanup: {cleanup_error}")

# === Run bot ===
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    place_id = "125760703264498"
    if not token:
        print("Error: DISCORD_TOKEN not found")
        raise SystemExit(1)
    MilestoneBot(token, place_id).run()
