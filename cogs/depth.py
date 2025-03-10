# cogs/depth.py
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
from .utils import Cache, parse_prompt, check_vram_usage, submit_comfyui_workflow, fetch_comfyui_outputs, monitor_vram_during_task, COMFYUI_API_URL
from config.default_model import DEFAULT_MODEL  # Add this if needed
from config.available_models import AVAILABLE_MODELS  # Add this if needed

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

VALID_COLORIZE_METHODS = [
    "Spectral", "terrain", "viridis", "plasma", "inferno", "magma", "cividis", 
    "twilight", "rainbow", "gist_rainbow", "gist_ncar", "gist_earth", "turbo", 
    "jet", "afmhot", "copper", "seismic", "hsv", "brg"
]
DEFAULT_COLORIZE_METHOD = "Spectral"

class DepthCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def generate_depth_map(self, init_image_bytes: BytesIO, colorize: bool = False, colorize_method: str = DEFAULT_COLORIZE_METHOD) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        workflow = await Cache.load_workflow("depth_workflow.yaml")
        if not workflow:
            logger.error("Depth workflow not loaded.")
            return None, None

        unique_filename = f"depth_input_{uuid.uuid4()}.png"
        workflow[3]["inputs"]["image"] = unique_filename

        if colorize and 7 in workflow and 8 in workflow:
            if colorize_method not in VALID_COLORIZE_METHODS:
                logger.warning(f"Invalid colorize method '{colorize_method}', defaulting to '{DEFAULT_COLORIZE_METHOD}'")
                colorize_method = DEFAULT_COLORIZE_METHOD
            workflow[7]["inputs"]["colorize_method"] = colorize_method
            if 6 in workflow:
                del workflow[6]  # Remove grayscale output
        else:
            if 7 in workflow:
                del workflow[7]  # Remove colorize node
            if 8 in workflow:
                del workflow[8]  # Remove colored output

        start_time = datetime.now()
        if not check_vram_usage():
            logger.warning("VRAM threshold exceeded before depth map generation.")
            return None, None

        init_image_bytes.seek(0)
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("image", init_image_bytes.read(), filename=unique_filename, content_type="image/png")
                async with session.post(f"{COMFYUI_API_URL}/upload/image", data=form) as upload_response:
                    upload_response.raise_for_status()
        except Exception as e:
            logger.error(f"Error uploading image for depth map: {e}")
            return None, None
        finally:
            init_image_bytes.seek(0)  # Reset for potential reuse

        async def task():
            prompt_id = await submit_comfyui_workflow(workflow)
            if not prompt_id:
                logger.error("Failed to submit depth workflow.")
                return None
            return await fetch_comfyui_outputs(prompt_id)

        self.bot.task_queue.put_nowait(task)
        try:
            images = await asyncio.wait_for(task(), timeout=120)  # Assuming API_TIMEOUT from utils
            if images:
                return images, datetime.now() - start_time
            logger.warning("No images returned from depth map workflow.")
            return None, None
        except asyncio.CancelledError:
            logger.warning("Depth map task cancelled due to VRAM threshold.")
            return None, None
        except Exception as e:
            logger.error(f"Depth map generation error: {e}")
            return None, None

    @commands.command(name="depth")
    async def depth(self, ctx, *, args: str = ""):
        """Generates a depth map from an attached or replied-to image.
        Options: 'colorize:yes' for colored output, 'method:<name>' to choose color scheme.
        Available methods: Spectral (default), terrain, viridis, plasma, etc."""
        if not ctx.message.attachments and not ctx.message.reference:
            await ctx.send("Please attach an image or reply to an image to generate a depth map.")
            return

        _, _, params = parse_prompt(self.bot, args)
        colorize = params.get("colorize", "no").lower() == "yes"
        colorize_method = params.get("method", DEFAULT_COLORIZE_METHOD)

        if colorize and colorize_method not in VALID_COLORIZE_METHODS:
            valid_methods_str = ", ".join(VALID_COLORIZE_METHODS)
            await ctx.send(f"Invalid method '{colorize_method}'. Available: {valid_methods_str}. Using '{DEFAULT_COLORIZE_METHOD}'.")
            colorize_method = DEFAULT_COLORIZE_METHOD

        init_image_data = await (ctx.message.attachments[0].read() if ctx.message.attachments else
                                 (await ctx.channel.fetch_message(ctx.message.reference.message_id)).attachments[0].read())
        init_image_bytes = BytesIO(init_image_data)

        wait_message = await ctx.send("Generating depth map... (Starting)")
        try:
            images, duration = await self.generate_depth_map(init_image_bytes, colorize=colorize, colorize_method=colorize_method)
            if images:
                guild_id = str(ctx.guild.id) if ctx.guild else "DM"
                stats_cog = self.bot.get_cog("StatsCog")
                if stats_cog:
                    stats_cog.update_user_stats(guild_id, ctx.author.id, ctx.author.display_name, depth_maps=1, total_time=duration.total_seconds())
                filename = f"depth_colorized_{uuid.uuid4()}.png" if colorize else f"depth_{uuid.uuid4()}.png"
                files = [discord.File(img, filename=filename) for img in images]
                await wait_message.edit(content=f"Depth map generated in {duration}")
                await ctx.send(files=files)
            else:
                await wait_message.edit(content="Failed to generate depth map.")
        except Exception as e:
            logger.error(f"Depth command error: {e}")
            await wait_message.edit(content=f"Error generating depth map: {str(e)}")
        finally:
            init_image_bytes.close()

async def setup(bot):
    await bot.add_cog(DepthCog(bot))