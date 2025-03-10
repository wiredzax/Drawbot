# cogs/txt2img.py
import discord
from discord.ext import commands
import aiohttp
import logging
import os
from io import BytesIO
from PIL import Image
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timedelta
import asyncio
import random
from .utils import Cache, parse_prompt, validate_resolution, check_vram_usage, submit_comfyui_workflow, fetch_comfyui_outputs, monitor_vram_during_task, handle_reactions, PROMPT_PREFIX, DEFAULT_NEGATIVE_PROMPT, API_TIMEOUT, MAX_BATCH_SIZE, STATIC_WIDTH, STATIC_HEIGHT
from config.default_model import DEFAULT_MODEL
from config.available_models import AVAILABLE_MODELS

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

REACTION_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
REACTION_TIMEOUT = 120

class Txt2ImgCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _safe_int(self, value, default):
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            logger.warning(f"Invalid int '{value}', using {default}")
            return default

    def _safe_float(self, value, default):
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            logger.warning(f"Invalid float '{value}', using {default}")
            return default

    async def generate_image_txt2img(self, prompt: str, negative_prompt: str, params: Dict[str, str], user_id: int) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        workflow_name = "txt2img_hr_workflow.yaml" if params.get("hr", "no").lower() == "yes" else "txt2img_workflow.yaml"
        workflow = await Cache.load_workflow(workflow_name)
        if not workflow:
            logger.error(f"Failed to load workflow: {workflow_name}")
            return None, None

        model_key = params.get("model", self.bot.user_model_preferences.get(user_id, DEFAULT_MODEL))
        ckpt_name = AVAILABLE_MODELS.get(model_key.lower(), AVAILABLE_MODELS[DEFAULT_MODEL])
        if params.get("model"):
            self.bot.user_model_preferences[user_id] = model_key.lower()
            await self.bot.save_preferences()
            logger.debug(f"User {user_id} set model to {model_key}")

        workflow[4]["inputs"]["ckpt_name"] = ckpt_name
        no_neg = params.get("noneg", "false").lower() == "true"
        if ckpt_name == AVAILABLE_MODELS["uncanny"] and not no_neg:
            negative_prompt = "lowres, (worst quality, bad quality:1.2), bad anatomy, sketch, jpeg artifacts..."
            prompt_prefix = "masterpiece, very awa, best quality..."
            workflow[3]["inputs"].update({"cfg": 2.2, "sampler_name": "euler_ancestral", "scheduler": "sgm_uniform"})
        else:
            prompt_prefix = PROMPT_PREFIX

        workflow[6]["inputs"]["text"] = f"{prompt_prefix} {prompt}".strip()
        workflow[7]["inputs"]["text"] = "" if no_neg else (negative_prompt or DEFAULT_NEGATIVE_PROMPT)
        workflow[3]["inputs"].update({
            "steps": self._safe_int(params.get("steps"), 35),
            "cfg": self._safe_float(params.get("cfg"), 4.0) if ckpt_name != AVAILABLE_MODELS["uncanny"] else 2.2,
            "seed": random.randint(0, 2**63 - 1),
            "sampler_name": params.get("sampler_name", "dpmpp_2m_sde") if ckpt_name != AVAILABLE_MODELS["uncanny"] else "euler_ancestral",
            "scheduler": params.get("scheduler", "exponential") if ckpt_name != AVAILABLE_MODELS["uncanny"] else "sgm_uniform"
        })
        width = self._safe_int(params.get("width"), STATIC_WIDTH)
        height = self._safe_int(params.get("height"), STATIC_HEIGHT)
        width, height = validate_resolution(width, height)
        batch_size = min(self._safe_int(params.get("batch"), 1), MAX_BATCH_SIZE)
        workflow[5]["inputs"].update({"width": width, "height": height, "batch_size": batch_size})

        start_time = datetime.now()
        if not check_vram_usage():
            logger.warning("VRAM usage too high, aborting generation")
            return None, None

        async def task():
            prompt_id = await submit_comfyui_workflow(workflow)
            if not prompt_id:
                logger.error("Failed to submit workflow")
                return None
            outputs = await fetch_comfyui_outputs(prompt_id)
            return outputs

        self.bot.task_queue.put_nowait(task)
        images = await asyncio.wait_for(task(), timeout=API_TIMEOUT)
        if images:
            logger.info(f"Generated {len(images)} images for prompt: '{prompt}' in {datetime.now() - start_time}")
        else:
            logger.warning("No images generated or generation timed out")
        return images, datetime.now() - start_time if images else None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user or not message.content.lower().startswith("draw "):
            return
        full_prompt_text = message.content[5:].strip()
        if not full_prompt_text:
            await message.channel.send("Please provide a prompt after 'draw'. Example: `draw a cat`")
            return
        positive_prompt, negative_prompt_user, params = parse_prompt(self.bot, full_prompt_text)
        negative_prompt = negative_prompt_user if negative_prompt_user is not None else DEFAULT_NEGATIVE_PROMPT
        logger.info(f"User {message.author} requested: prompt='{positive_prompt}', negative_prompt='{negative_prompt}', params={params}")
        await self.handle_generation_request(message.channel, message.author, positive_prompt, negative_prompt, params)

    async def handle_generation_request(self, channel, author, prompt: str, negative_prompt: str, params: Dict[str, str]):
        if not check_vram_usage():
            await channel.send("GPU VRAM usage too high. Try again later.")
            return

        wait_message = await channel.send("Generating image... Please wait.")
        try:
            output_bytes_list, duration = await self.generate_image_txt2img(prompt, negative_prompt, params, author.id)
            if output_bytes_list:
                guild_id = str(channel.guild.id) if channel.guild else "DM"
                stats_cog = self.bot.get_cog("StatsCog")
                if stats_cog:
                    stats_cog.update_user_stats(guild_id, author.id, author.display_name, images=len(output_bytes_list), total_time=duration.total_seconds())

                def prepare_files():
                    files = []
                    for i, output in enumerate(output_bytes_list):
                        output.seek(0)
                        file = discord.File(output, filename=f"txt2img_{author.id}_{i}.png")
                        files.append(file)
                    return files

                files = await self.bot.loop.run_in_executor(None, prepare_files)
                param_str = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "None"
                user_model = self.bot.user_model_preferences.get(author.id, DEFAULT_MODEL)
                content = (
                    f"**Prompt:** `{prompt}`\n"
                    f"**Negative Prompt:** `{negative_prompt if not params.get('noneg', 'false').lower() == 'true' else 'None'}`\n"
                    f"**Parameters:** `{param_str}`\n"
                    f"**Model:** `{user_model}`\n"
                    f"**Time:** `{duration}`\n"
                    f"{author.mention}, react with ✅ to approve, ❌ to delete, or 🔁 to regenerate."
                )
                for attempt in range(3):
                    try:
                        await wait_message.delete()
                        sent_message = await channel.send(content, files=files)
                        logger.info(f"Uploaded {len(files)} images for {author} with prompt: '{prompt}'")
                        break
                    except (discord.errors.DiscordServerError, discord.errors.HTTPException) as e:
                        logger.warning(f"Attempt {attempt + 1} failed to send message: {e}")
                        if attempt < 2:
                            await asyncio.sleep(2)
                        else:
                            raise
                reaction = await handle_reactions(self.bot, sent_message, author, content, files, options=['✅', '❌', '🔁'])
                if reaction == '✅':
                    await sent_message.clear_reactions()
                elif reaction == '❌':
                    await sent_message.delete()
                elif reaction == '🔁':
                    await sent_message.delete()
                    await self.handle_generation_request(channel, author, prompt, negative_prompt, params)
            else:
                try:
                    await wait_message.delete()
                except discord.errors.NotFound:
                    logger.debug("Wait message already deleted or not found")
                await channel.send("Failed to generate image or timed out.")
        except Exception as e:
            logger.error(f"Generation error for {author}: {e}", exc_info=True)
            try:
                await wait_message.delete()
            except discord.errors.NotFound:
                logger.debug("Wait message already deleted or not found")
            await channel.send(f"Error: {str(e)}. Please try again later.")

async def setup(bot):
    await bot.add_cog(Txt2ImgCog(bot))