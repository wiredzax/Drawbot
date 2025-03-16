# cogs/utils.py
import discord
from discord.ext import commands
import aiohttp
import logging
import os
import yaml
from io import BytesIO
from PIL import Image
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timedelta
import asyncio
import aiofiles
import GPUtil
from dotenv import load_dotenv
import random
from config.default_model import DEFAULT_MODEL
from config.available_models import AVAILABLE_MODELS  # Import from new location

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

load_dotenv()

# --- Constants ---
PROMPT_PREFIX = "embedding:SimplePositiveXLv2,"
DEFAULT_NEGATIVE_PROMPT = "embedding:DeepNegative_xl_v1"
COMFYUI_API_URL = os.getenv("COMFYUI_API_URL", "http://127.0.0.1:8188")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", 120))
RATE_LIMIT_REQUESTS = 5
RATE_LIMIT_WINDOW = 60
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", 5))
VRAM_THRESHOLD_GB = float(os.getenv("VRAM_THRESHOLD_GB", 20))
VRAM_CHECK_INTERVAL = 1
STATIC_WIDTH = int(os.getenv("STATIC_WIDTH", 1024))
STATIC_HEIGHT = int(os.getenv("STATIC_HEIGHT", 1024))
MAX_IMAGE_DIMENSION = int(os.getenv("MAX_IMAGE_DIMENSION", 3000))
WORKFLOWS_PATH = os.getenv("WORKFLOWS_PATH", "workflows")
IMAGE_OUTPUT_PATH = os.getenv("IMAGE_OUTPUT_PATH", "generated_images")

PROMPT_DIR = "prompts"
STYLES_FILE = os.path.join(PROMPT_DIR, "styles.txt")
SUBJECTS_FILE = os.path.join(PROMPT_DIR, "subjects.txt")
SETTINGS_FILE = os.path.join(PROMPT_DIR, "settings.txt")

# --- Cache ---
class Cache:
    workflows = {}
    prompt_options = {}

    @staticmethod
    async def load_workflow(name: str) -> Dict:
        if name not in Cache.workflows:
            async with aiofiles.open(os.path.join(WORKFLOWS_PATH, name), 'r', encoding='utf-8') as f:
                workflow_data = yaml.safe_load(await f.read())
                if workflow_data:
                    for key in list(workflow_data.keys()):
                        workflow_data[int(key)] = workflow_data.pop(key)
                    Cache.workflows[name] = workflow_data
                else:
                    logger.error(f"{name} is empty or invalid YAML")
        return Cache.workflows.get(name, {}).copy()

    @staticmethod
    async def load_prompt_options(file_path: str) -> List[str]:
        if file_path not in Cache.prompt_options:
            try:
                if not os.path.exists(file_path):
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    async with aiofiles.open(file_path, 'w') as f:
                        await f.write("")
                    return []
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    options = [line.strip() async for line in f if line.strip()]
                Cache.prompt_options[file_path] = options
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")
                return []
        return Cache.prompt_options[file_path].copy()

# --- Parameter Definitions ---
def get_settable_parameters():
    return {
        "steps": {"default": 35, "description": "Number of sampling steps (higher = more detail, slower)"},
        "cfg": {"default": 4.0, "description": "Classifier-free guidance scale (overridden to 2.2 for 'uncanny')"},
        "batch": {"default": 1, "description": "Number of images to generate (max: 5)"},
        "hr": {"default": "no", "description": "Enable high-resolution output (yes/no)"},
        "width": {"default": STATIC_WIDTH, "description": "Width of the generated image"},
        "height": {"default": STATIC_HEIGHT, "description": "Height of the generated image"},
        "model": {"default": "uncanny", "description": "Model to use (e.g., indigo, uncanny)"},
        "noneg": {"default": "false", "description": "Disable negative prompt (true/false)"},
        "sampler_name": {"default": "dpmpp_2m_sde", "description": "Sampling algorithm"},
        "scheduler": {"default": "exponential", "description": "Scheduler for sampling"},
        "depth": {"default": "no", "description": "Generate a depth map (yes/no)"},
        "colorize": {"default": "no", "description": "Colorize the depth map (yes/no)"},
        "method": {"default": "spectral", "description": "Color scheme for depth map"}
    }

# --- Utility Functions ---
def parse_prompt(bot, text: str) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    text = text.strip() if text else ""
    positive_prompt = ""
    negative_prompt = None
    params = {}
    import re

    valid_params = set(get_settable_parameters().keys())
    param_pattern = rf"({'|'.join(valid_params)}):([^:,\s]*(?:\s+[^:,\s]+)*)(?=\s*(?:,|\s+\w+:|$))"
    matches = re.findall(param_pattern, text, re.IGNORECASE)
    for key, value in matches:
        params[key.lower()] = value.strip()
        text = re.sub(rf"{key}:{re.escape(value)}\s*(?:,|\s+)?", "", text).strip()

    text = re.sub(r'\s*,\s*', ', ', text).strip()

    if "neg:" in text.lower():
        prompt_parts = re.split(r"(?i)neg:", text, 1)
        positive_prompt = prompt_parts[0].strip()
        negative_prompt = prompt_parts[1].strip() if len(prompt_parts) > 1 else None
    else:
        positive_prompt = text.strip()

    if "neg" in params:
        if negative_prompt:
            negative_prompt = f"{params['neg']}, {negative_prompt}"
        else:
            negative_prompt = params["neg"]
        del params["neg"]

    return positive_prompt or "enhance", negative_prompt, params

def validate_resolution(width: int, height: int) -> Tuple[int, int]:
    width = max(0, min(width, 2048))
    height = max(0, min(height, 2048))
    if width == 0 or height == 0:
        logger.warning(f"Resolution {width}x{height} is invalid; using {STATIC_WIDTH}x{STATIC_HEIGHT}")
        return STATIC_WIDTH, STATIC_HEIGHT
    logger.debug(f"Validated resolution: {width}x{height}")
    return width, height

def check_vram_usage() -> bool:
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if not gpus:
            logger.warning("No GPUs found by GPUtil. VRAM check disabled.")
            return True
        gpu = gpus[0]
        vram_used_gb = gpu.memoryUsed / 1024
        logger.debug(f"VRAM: {vram_used_gb:.2f}GB/{VRAM_THRESHOLD_GB}GB")
        return vram_used_gb <= VRAM_THRESHOLD_GB
    except ImportError:
        logger.warning("GPUtil not installed. VRAM checks disabled. Install with 'pip install gputil'.")
        return True
    except Exception as e:
        logger.error(f"VRAM check failed: {e}")
        return True

async def monitor_vram_during_task(task: asyncio.Task, interval: float = VRAM_CHECK_INTERVAL) -> None:
    while not task.done():
        if not check_vram_usage():
            task.cancel()
            await interrupt_api_generation()
            break
        await asyncio.sleep(interval)

async def interrupt_api_generation() -> bool:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as session:
            async with session.post(f"{COMFYUI_API_URL}/api/interrupt") as response:
                return response.status == 200
    except Exception as e:
        logger.error(f"Interrupt failed: {e}")
        return False

def check_image_size(image_data: bytes, max_dimension: int = MAX_IMAGE_DIMENSION) -> Tuple[bool, int, int]:
    try:
        with Image.open(BytesIO(image_data)) as image:
            width, height = image.size
        return (width <= max_dimension and height <= max_dimension), width, height
    except Exception as e:
        logger.error(f"Image size check failed: {e}")
        return False, 0, 0

async def submit_comfyui_workflow(workflow: Dict) -> Optional[str]:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=API_TIMEOUT)) as session:
            async with session.post(f"{COMFYUI_API_URL}/prompt", json={"prompt": workflow}) as response:
                if not response.ok:
                    raise aiohttp.ClientError(f"{response.status}: {await response.text()}")
                return (await response.json()).get("prompt_id")
    except Exception as e:
        logger.error(f"Workflow submission failed: {e}")
        return None

async def fetch_comfyui_outputs(prompt_id: str) -> Optional[List[BytesIO]]:
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(f"{COMFYUI_API_URL}/history/{prompt_id}") as response:
                    response.raise_for_status()
                    history = await response.json()
                    if prompt_id in history and "outputs" in history[prompt_id]:
                        outputs = history[prompt_id]["outputs"]
                        files = []
                        for node_id, data in outputs.items():
                            if "images" in data:
                                for img_info in data["images"]:
                                    async with session.get(f"{COMFYUI_API_URL}/view?filename={img_info['filename']}&type=output") as file_response:
                                        file_response.raise_for_status()
                                        files.append(BytesIO(await file_response.read()))
                        return files
                    await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Fetch outputs failed: {e}")
        return None

async def handle_reactions(bot, message, author, content: str, files: List[discord.File], options=['✅', '❌', '🔁']) -> Optional[str]:
    for emoji in options:
        await message.add_reaction(emoji)
    def check(reaction, user):
        return user == author and str(reaction.emoji) in options and reaction.message.id == message.id
    try:
        reaction, _ = await bot.wait_for('reaction_add', timeout=120, check=check)
        await message.edit(content=content.split('\nreact with')[0])
        return str(reaction.emoji)
    except asyncio.TimeoutError:
        await message.edit(content=content.split('\nreact with')[0])
        await message.clear_reactions()
        return None

class UtilsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.styles = []
        self.subjects = []
        self.settings = []
        self.bot.loop.create_task(self.load_prompts())

    async def load_prompts(self):
        self.styles = await Cache.load_prompt_options(STYLES_FILE)
        self.subjects = await Cache.load_prompt_options(SUBJECTS_FILE)
        self.settings = await Cache.load_prompt_options(SETTINGS_FILE)
        logger.info("Loaded prompt options for UtilsCog")

    @commands.command(name="models")
    async def models(self, ctx):
        models_list = "\n".join([f"- {key}" for key in AVAILABLE_MODELS.keys()])
        await ctx.send(f"Available models:\n```\n{models_list}\n```\nCurrent: `{self.bot.user_model_preferences.get(ctx.author.id, DEFAULT_MODEL)}`")

    @commands.command(name="resolutions")
    async def resolutions(self, ctx):
        await ctx.send(f"Custom resolutions supported: 0x0 to 2048x2048\nDefault: {STATIC_WIDTH}x{STATIC_HEIGHT}")

    @commands.command(name="params")
    async def params(self, ctx):
        params = get_settable_parameters()
        param_list = "\n".join([f"+ **{key}**: Default=`{params[key]['default']}`\n  - {params[key]['description']}" for key in params])
        await ctx.send(f"**Settable Parameters**\nUse like `draw a cat steps:50`\n```diff\n{param_list}\n```")

    @commands.command(name="inspireme")
    async def inspire_me(self, ctx):
        if not all([self.styles, self.subjects, self.settings]):
            await ctx.send("Prompt files are empty or missing. Check `prompts/`.")
            return
        style, subject, setting = random.choice(self.styles), random.choice(self.subjects), random.choice(self.settings)
        prompt = f"{style} {subject} in a {setting}"
        await ctx.send(f"Random prompt: `{prompt}`\nRun `draw {prompt}` to generate!")

    @commands.command(name="addstyle")
    async def add_style(self, ctx, style: str):
        async with aiofiles.open(STYLES_FILE, 'a', encoding='utf-8') as f:
            await f.write(f"{style}\n")
        self.styles = await Cache.load_prompt_options(STYLES_FILE)
        await ctx.send(f"Added '{style}' to styles!")

async def setup(bot):
    await bot.add_cog(UtilsCog(bot))
