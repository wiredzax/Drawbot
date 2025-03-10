#Bot26.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import json
import asyncio
import aiofiles
import time
import sqlite3

load_dotenv()
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.members = True  # Add members intent
        super().__init__(command_prefix="!", intents=intents)
        self.user_model_preferences = {}
        self.task_queue = asyncio.Queue()
        self.max_concurrent_tasks = 2
        self.running_tasks = 0
        self.db_path = os.getenv("DB_PATH", "guild_stats.db")
        self.preferences_file = os.getenv("PREFERENCES_FILE", "user_preferences.json")
        self.setup_db()

    def setup_db(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    guild_id TEXT,
                    user_id TEXT,
                    images INTEGER DEFAULT 0,
                    canvas_contributions INTEGER DEFAULT 0,
                    evolutions INTEGER DEFAULT 0,
                    depth_maps INTEGER DEFAULT 0,
                    last_generated TEXT,
                    total_time REAL DEFAULT 0,
                    username TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            c.execute("PRAGMA table_info(user_stats)")
            columns = [col[1] for col in c.fetchall()]
            if "username" not in columns:
                c.execute("ALTER TABLE user_stats ADD COLUMN username TEXT")
            conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

async def load_preferences(self):
    try:
        if os.path.exists(self.preferences_file):
            async with aiofiles.open(self.preferences_file, 'r') as f:
                self.user_model_preferences = {int(k): v for k, v in json.loads(await f.read()).items()}
            logger.info(f"Loaded preferences from {self.preferences_file}")
        else:
            self.user_model_preferences = {}
    except Exception as e:
        logger.error(f"Error loading preferences: {e}")
        self.user_model_preferences = {}

async def save_preferences(self):
    try:
        async with aiofiles.open(self.preferences_file, 'w') as f:
            await f.write(json.dumps(self.user_model_preferences))
        logger.debug("Saved preferences")
    except Exception as e:
        logger.error(f"Error saving preferences: {e}")

async def process_queue(self):
    while True:
        if self.running_tasks < self.max_concurrent_tasks:
            task = await self.task_queue.get()
            self.running_tasks += 1
            logger.debug(f"Processing task, queue size: {self.task_queue.qsize()}")
            try:
                await task()
            finally:
                self.running_tasks -= 1
                self.task_queue.task_done()
        await asyncio.sleep(0.1)

bot = Bot()
bot.load_preferences = load_preferences.__get__(bot, commands.Bot)
bot.save_preferences = save_preferences.__get__(bot, commands.Bot)
bot.process_queue = process_queue.__get__(bot, commands.Bot)

async def load_cogs():
    for filename in os.listdir("cogs"):
        if filename.endswith(".py") and filename != "__init__.py":
            await bot.load_extension(f"cogs.{filename[:-3]}")
            logger.info(f"Loaded cog: {filename[:-3]}")

@bot.event
async def on_ready():
    bot.start_time = time.time()
    await bot.load_preferences()
    bot.loop.create_task(bot.process_queue())
    if not bot.owner_id:
        app_info = await bot.application_info()
        bot.owner_id = app_info.owner.id
        logger.info(f"Bot owner ID set to {bot.owner_id}")
    logger.info(f"Bot logged in as {bot.user}")
    await load_cogs()

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN not set in .env file.")
        print("Error: DISCORD_BOT_TOKEN not set in .env file.")
    else:
        bot.run(DISCORD_BOT_TOKEN)