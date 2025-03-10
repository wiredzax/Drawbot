# cogs/canvas.py
import discord
from discord.ext import commands
import aiohttp
import logging
import os
import yaml
from io import BytesIO
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
import asyncio
import uuid
from .utils import check_vram_usage, submit_comfyui_workflow, fetch_comfyui_outputs, monitor_vram_during_task, WORKFLOWS_PATH, IMAGE_OUTPUT_PATH, COMFYUI_API_URL, AVAILABLE_MODELS
from config.default_model import DEFAULT_MODEL  # Add this if needed
from config.available_models import AVAILABLE_MODELS  # Add this if needed

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class CanvasCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.canvas_image = None  # BytesIO of current canvas
        self.canvas_workflow = {}
        self.last_channel = None  # To store guild context
        self.load_workflow()

    def load_workflow(self):
        try:
            with open(os.path.join(WORKFLOWS_PATH, "inpaint_workflow.yaml"), 'r', encoding='utf-8') as f:
                workflow_data = yaml.safe_load(f)
                if workflow_data is None:
                    logger.error("inpaint_workflow.yaml is empty or invalid YAML")
                    return
                for key in list(workflow_data.keys()):
                    workflow_data[int(key)] = workflow_data.pop(key)
                self.canvas_workflow.update(workflow_data)
                logger.info("CANVAS workflow loaded from inpaint_workflow.yaml")
        except Exception as e:
            logger.error(f"Error loading inpaint_workflow.yaml: {e}")

    async def update_canvas(self, prompt: str, mask_bytes: BytesIO, user_id: int) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        if not self.canvas_image:
            return None, None
        
        workflow = self.canvas_workflow.copy()
        image_filename = f"canvas_{uuid.uuid4()}.png"
        mask_filename = f"canvas_mask_{uuid.uuid4()}.png"
        workflow[3]["inputs"]["image"] = image_filename
        workflow[4]["inputs"]["image"] = mask_filename

        model_key = self.bot.user_model_preferences.get(user_id, "uncanny")
        ckpt_name = AVAILABLE_MODELS.get(model_key.lower(), AVAILABLE_MODELS["uncanny"])
        workflow[5]["inputs"]["ckpt_name"] = ckpt_name

        workflow[6]["inputs"]["text"] = f"SimplePositiveXLv2 {prompt}".strip()
        workflow[7]["inputs"]["text"] = "DeepNegative_xl_v1"

        start_time = datetime.now()
        if not check_vram_usage():
            return None, None

        async with aiohttp.ClientSession() as session:
            self.canvas_image.seek(0)
            form = aiohttp.FormData()
            form.add_field("image", self.canvas_image.read(), filename=image_filename, content_type="image/png")
            await session.post(f"{COMFYUI_API_URL}/upload/image", data=form)
            mask_bytes.seek(0)
            form = aiohttp.FormData()
            form.add_field("image", mask_bytes.read(), filename=mask_filename, content_type="image/png")
            await session.post(f"{COMFYUI_API_URL}/upload/image", data=form)

        prompt_id = await submit_comfyui_workflow(workflow)
        if not prompt_id:
            return None, None

        request_task = asyncio.create_task(fetch_comfyui_outputs(prompt_id))
        monitor_task = asyncio.create_task(monitor_vram_during_task(request_task))

        try:
            images = await request_task
            if images:
                self.canvas_image = images[0]  # Update canvas with new image
                stats_cog = self.bot.get_cog("StatsCog")
                if stats_cog and self.last_channel:
                    guild_id = str(self.last_channel.guild.id) if self.last_channel.guild else "DM"
                    stats_cog.update_user_stats(guild_id, user_id, canvas_contributions=1, total_time=(datetime.now() - start_time).total_seconds())
                return images, datetime.now() - start_time
            return None, None
        except Exception as e:
            logger.error(f"Canvas update error: {e}")
            return None, None

    @commands.command(name="startcanvas")
    async def start_canvas(self, ctx, *, prompt: str):
        """Starts a new collaborative canvas with an initial prompt."""
        txt2img_cog = self.bot.get_cog("Txt2ImgCog")
        if not txt2img_cog:
            await ctx.send("Txt2ImgCog not loaded!")
            return

        self.last_channel = ctx.channel  # Store channel for guild context
        images, duration = await txt2img_cog.generate_image_txt2img(prompt, "DeepNegative_xl_v1", {}, ctx.author.id)
        if images:
            self.canvas_image = images[0]
            guild_id = str(ctx.guild.id) if ctx.guild else "DM"
            stats_cog = self.bot.get_cog("StatsCog")
            if stats_cog:
                stats_cog.update_user_stats(guild_id, ctx.author.id, images=1, total_time=duration.total_seconds())
            await ctx.send(f"Canvas started with '{prompt}' in {duration}", file=discord.File(self.canvas_image, filename="canvas.png"))
        else:
            await ctx.send("Failed to start canvas.")

    @commands.command(name="addcanvas")
    async def add_canvas(self, ctx, *, prompt: str):
        """Adds to the canvas with a prompt and attached mask (white = edit area)."""
        if not self.canvas_image:
            await ctx.send("No canvas started! Use !startcanvas first.")
            return
        if not ctx.message.attachments:
            await ctx.send("Please attach a mask (white areas will be edited).")
            return

        self.last_channel = ctx.channel  # Store channel for guild context
        mask_data = await ctx.message.attachments[0].read()
        mask_bytes = BytesIO(mask_data)
        wait_message = await ctx.send("Updating canvas... Please wait.")
        images, duration = await self.update_canvas(prompt, mask_bytes, ctx.author.id)
        
        if images:
            await wait_message.delete()
            await ctx.send(f"Canvas updated by {ctx.author.mention} in {duration}", file=discord.File(images[0], filename="canvas.png"))
        else:
            await wait_message.delete()
            await ctx.send("Failed to update canvas.")
        mask_bytes.close()

    @commands.command(name="showcanvas")
    async def show_canvas(self, ctx):
        """Displays the current canvas."""
        if not self.canvas_image:
            await ctx.send("No canvas started! Use !startcanvas first.")
            return
        self.canvas_image.seek(0)
        await ctx.send("Current canvas:", file=discord.File(self.canvas_image, filename="canvas.png"))

async def setup(bot):
    await bot.add_cog(CanvasCog(bot))