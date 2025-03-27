# cogs/img2img.py
import discord
from discord.ext import commands
import aiohttp
import logging
import os
from io import BytesIO
from PIL import Image
import yaml
from typing import Optional, List, Tuple, Dict
from datetime import datetime, timedelta
import asyncio
import uuid
import random
from .utils import Cache, parse_prompt, check_vram_usage, submit_comfyui_workflow, fetch_comfyui_outputs, handle_reactions, PROMPT_PREFIX, DEFAULT_NEGATIVE_PROMPT, API_TIMEOUT, MAX_BATCH_SIZE, MAX_IMAGE_DIMENSION, check_image_size, COMFYUI_API_URL
from config.default_model import DEFAULT_MODEL
from config.available_models import AVAILABLE_MODELS

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

REACTION_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
REACTION_TIMEOUT = 120

class Img2ImgCog(commands.Cog):
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

    async def generate_image_img2img(self, prompt: str, init_image_bytes: BytesIO, negative_prompt: str, params: Dict[str, str], user_id: int) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        workflow_name = "img2img_hr_workflow.yaml" if params.get("hr", "no").lower() == "yes" else "img2img_workflow.yaml"
        workflow = await Cache.load_workflow(workflow_name)
        if not workflow:
            return None, None

        model_key = params.get("model", self.bot.user_model_preferences.get(user_id, DEFAULT_MODEL))
        ckpt_name = AVAILABLE_MODELS.get(model_key.lower(), AVAILABLE_MODELS[DEFAULT_MODEL])
        if params.get("model"):
            self.bot.user_model_preferences[user_id] = model_key.lower()
            await self.bot.save_preferences()

        workflow[4]["inputs"]["ckpt_name"] = ckpt_name
        no_neg = params.get("noneg", "false").lower() == "true"
        if ckpt_name == AVAILABLE_MODELS["uncanny"] and not no_neg:
            negative_prompt = "lowres, (worst quality, bad quality:1.2), bad anatomy, sketch..."
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

        unique_filename = f"input_{uuid.uuid4()}.png"
        workflow[5]["inputs"]["image"] = unique_filename

        start_time = datetime.now()
        if not check_vram_usage():
            return None, None

        init_image_bytes.seek(0)
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("image", init_image_bytes.read(), filename=unique_filename, content_type="image/png")
                async with session.post(f"{COMFYUI_API_URL}/upload/image", data=form) as upload_response:
                    upload_response.raise_for_status()
        except Exception as e:
            logger.error(f"Image upload failed: {e}")
            return None, None
        finally:
            init_image_bytes.seek(0)

        async def task():
            prompt_id = await submit_comfyui_workflow(workflow)
            if not prompt_id:
                return None
            return await fetch_comfyui_outputs(prompt_id)

        self.bot.task_queue.put_nowait(task)
        images = await asyncio.wait_for(task(), timeout=API_TIMEOUT)
        return images, datetime.now() - start_time if images else None

    async def generate_image_upscale(self, init_image_bytes: BytesIO) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        workflow = await Cache.load_workflow("upscale_workflow.yaml")
        if not workflow:
            return None, None

        unique_filename = f"upscale_input_{uuid.uuid4()}.png"
        workflow[3]["inputs"]["image"] = unique_filename

        start_time = datetime.now()
        if not check_vram_usage():
            return None, None

        init_image_bytes.seek(0)
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("image", init_image_bytes.read(), filename=unique_filename, content_type="image/png")
                async with session.post(f"{COMFYUI_API_URL}/upload/image", data=form) as upload_response:
                    upload_response.raise_for_status()
        except Exception as e:
            logger.error(f"Upscale upload failed: {e}")
            return None, None
        finally:
            init_image_bytes.seek(0)

        async def task():
            prompt_id = await submit_comfyui_workflow(workflow)
            if not prompt_id:
                return None
            return await fetch_comfyui_outputs(prompt_id)

        self.bot.task_queue.put_nowait(task)
        images = await asyncio.wait_for(task(), timeout=API_TIMEOUT)
        return images, datetime.now() - start_time if images else None

    async def generate_image_inpaint(self, init_image_bytes: BytesIO, mask_bytes: BytesIO, prompt: str, negative_prompt: str, params: Dict[str, str], user_id: int) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        workflow = await Cache.load_workflow("inpaint_workflow.yaml")
        if not workflow:
            return None, None

        image_filename = f"inpaint_image_{uuid.uuid4()}.png"
        mask_filename = f"inpaint_mask_{uuid.uuid4()}.png"
        workflow[3]["inputs"]["image"] = image_filename
        workflow[4]["inputs"]["image"] = mask_filename

        model_key = params.get("model", self.bot.user_model_preferences.get(user_id, DEFAULT_MODEL))
        workflow[5]["inputs"]["ckpt_name"] = AVAILABLE_MODELS.get(model_key.lower(), AVAILABLE_MODELS[DEFAULT_MODEL])
        workflow[6]["inputs"]["text"] = f"{PROMPT_PREFIX} {prompt}".strip()
        workflow[7]["inputs"]["text"] = negative_prompt or DEFAULT_NEGATIVE_PROMPT
        workflow[9]["inputs"].update({
            "steps": self._safe_int(params.get("steps"), 35),
            "cfg": self._safe_float(params.get("cfg"), 4.0),
            "seed": random.randint(0, 2**63 - 1)
        })

        start_time = datetime.now()
        if not check_vram_usage():
            return None, None

        try:
            async with aiohttp.ClientSession() as session:
                for data, filename in [(init_image_bytes, image_filename), (mask_bytes, mask_filename)]:
                    data.seek(0)
                    form = aiohttp.FormData()
                    form.add_field("image", data.read(), filename=filename, content_type="image/png")
                    async with session.post(f"{COMFYUI_API_URL}/upload/image", data=form) as upload_response:
                        upload_response.raise_for_status()
        except Exception as e:
            logger.error(f"Inpaint upload failed: {e}")
            return None, None
        finally:
            init_image_bytes.seek(0)
            mask_bytes.seek(0)

        async def task():
            prompt_id = await submit_comfyui_workflow(workflow)
            if not prompt_id:
                return None
            return await fetch_comfyui_outputs(prompt_id)

        self.bot.task_queue.put_nowait(task)
        images = await asyncio.wait_for(task(), timeout=API_TIMEOUT)
        return images, datetime.now() - start_time if images else None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if message.attachments or (message.reference and message.reference.message_id):
            content_lower = message.content.lower()
            if content_lower.startswith(('!upscale', '!inpaint', '!img2img', '!depth', '!addcanvas')):
                return

            if message.attachments:
                attachment = message.attachments[0]
                if not attachment.content_type.startswith('image'):
                    return
                init_image_data = await attachment.read()
            elif message.reference:
                replied_message = await message.channel.fetch_message(message.reference.message_id)
                if replied_message.author == self.bot.user and replied_message.attachments:
                    attachment = replied_message.attachments[0]
                    if not attachment.content_type.startswith('image'):
                        return
                    init_image_data = await attachment.read()
                else:
                    return

            is_valid, width, height = check_image_size(init_image_data)
            if not is_valid:
                await message.channel.send(f"Image too large (max {MAX_IMAGE_DIMENSION}px, got {width}x{height}).")
                return

            with BytesIO(init_image_data) as init_image_bytes:
                prompt, negative_prompt_user, params = parse_prompt(self.bot, message.content or "enhance")
                negative_prompt = negative_prompt_user if negative_prompt_user is not None else DEFAULT_NEGATIVE_PROMPT
                depth_mode = params.get("depth", "no").lower() == "yes"

                if depth_mode:
                    depth_cog = self.bot.get_cog("DepthCog")
                    if not depth_cog:
                        await message.channel.send("DepthCog not loaded.")
                        return
                    colorize = params.get("colorize", "no").lower() == "yes"
                    colorize_method = params.get("method", "Spectral")
                    wait_message = await message.channel.send("Generating depth map... Please wait.")
                    images, duration = await depth_cog.generate_depth_map(init_image_bytes, colorize=colorize, colorize_method=colorize_method)
                    if images:
                        filename = f"depth_colorized_{uuid.uuid4()}.png" if colorize else f"depth_{uuid.uuid4()}.png"
                        files = [discord.File(img, filename=filename) for img in images]
                        await wait_message.delete()
                        await message.channel.send(f"Depth map generated in {duration}", files=files)
                    else:
                        await wait_message.delete()
                        await message.channel.send("Failed to generate depth map.")
                else:
                    await self.handle_generation_request(message.channel, message.author, prompt, negative_prompt, params, init_image_bytes)

    @commands.command(name="upscale")
    async def upscale(self, ctx):
        if not ctx.message.attachments and not ctx.message.reference:
            await ctx.send("Please attach an image or reply to an image to upscale.")
            return
        
        with BytesIO(await (ctx.message.attachments[0].read() if ctx.message.attachments else
                            (await ctx.channel.fetch_message(ctx.message.reference.message_id)).attachments[0].read())) as init_image_bytes:
            wait_message = await ctx.send("Upscaling image... Please wait.")
            try:
                images, duration = await self.generate_image_upscale(init_image_bytes)
                if images:
                    guild_id = str(ctx.guild.id) if ctx.guild else "DM"
                    stats_cog = self.bot.get_cog("StatsCog")
                    if stats_cog:
                        stats_cog.update_user_stats(guild_id, ctx.author.id, ctx.author.display_name, images=len(images), total_time=duration.total_seconds())
                    files = [discord.File(img, filename=f"upscaled_{uuid.uuid4()}.png") for img in images]
                    await wait_message.delete()
                    await ctx.send(f"Upscaled image in {duration}", files=files)
                else:
                    await wait_message.delete()
                    await ctx.send("Failed to upscale image.")
            except Exception as e:
                logger.error(f"Upscale error: {e}")
                await wait_message.delete()
                await ctx.send(f"Error: {str(e)}")

    @commands.command(name="inpaint")
    async def inpaint(self, ctx, *, prompt: str):
        if not ctx.message.reference or not ctx.message.attachments:
            await ctx.send("Please reply to an image and attach a mask (white = edit area).")
            return
        
        replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if replied_message.author != self.bot.user or not replied_message.attachments:
            await ctx.send("Please reply to a bot-generated image.")
            return
        
        with BytesIO(await replied_message.attachments[0].read()) as init_image_bytes, BytesIO(await ctx.message.attachments[0].read()) as mask_bytes:
            positive_prompt, negative_prompt_user, params = parse_prompt(self.bot, prompt)
            negative_prompt = negative_prompt_user or DEFAULT_NEGATIVE_PROMPT

            wait_message = await ctx.send("Inpainting image... Please wait.")
            try:
                images, duration = await self.generate_image_inpaint(init_image_bytes, mask_bytes, positive_prompt, negative_prompt, params, ctx.author.id)
                if images:
                    guild_id = str(ctx.guild.id) if ctx.guild else "DM"
                    stats_cog = self.bot.get_cog("StatsCog")
                    if stats_cog:
                        stats_cog.update_user_stats(guild_id, ctx.author.id, ctx.author.display_name, images=len(images), total_time=duration.total_seconds())
                    files = [discord.File(img, filename=f"inpainted_{uuid.uuid4()}.png") for img in images]
                    await wait_message.delete()
                    await ctx.send(f"Inpainted image in {duration}", files=files)
                else:
                    await wait_message.delete()
                    await ctx.send("Failed to inpaint image.")
            except Exception as e:
                logger.error(f"Inpaint error: {e}")
                await wait_message.delete()
                await ctx.send(f"Error: {str(e)}")

    @commands.command(name="img2img")
    async def img2img(self, ctx, *, prompt: str):
        if not ctx.message.attachments and not ctx.message.reference:
            await ctx.send("Please attach an image or reply to an image for img2img.")
            return
        
        with BytesIO(await (ctx.message.attachments[0].read() if ctx.message.attachments else
                            (await ctx.channel.fetch_message(ctx.message.reference.message_id)).attachments[0].read())) as init_image_bytes:
            prompt_text, negative_prompt_user, params = parse_prompt(self.bot, prompt)
            negative_prompt = negative_prompt_user or DEFAULT_NEGATIVE_PROMPT
            await self.handle_generation_request(ctx.channel, ctx.author, prompt_text, negative_prompt, params, init_image_bytes)

    async def handle_generation_request(self, channel, author, prompt: str, negative_prompt: str, params: Dict[str, str], init_image_bytes: BytesIO):
        if not check_vram_usage():
            await channel.send("GPU VRAM usage too high. Try again later.")
            return

        wait_message = await channel.send("Generating image... Please wait.")
        try:
            output_bytes_list, duration = await self.generate_image_img2img(prompt, init_image_bytes, negative_prompt, params, author.id)
            if output_bytes_list:
                guild_id = str(channel.guild.id) if channel.guild else "DM"
                stats_cog = self.bot.get_cog("StatsCog")
                if stats_cog:
                    stats_cog.update_user_stats(guild_id, author.id, author.display_name, images=len(output_bytes_list), total_time=duration.total_seconds())

                image_files = []
                total_size = 0
                for i, output in enumerate(output_bytes_list):
                    output.seek(0)
                    size = output.getbuffer().nbytes
                    total_size += size
                    file = discord.File(output, filename=f"img2img_{author.id}_{i}.png")
                    image_files.append(file)

                max_size = 25 * 1024 * 1024
                if total_size > max_size:
                    await wait_message.delete()
                    chunks = []
                    current_chunk = []
                    current_size = 0
                    for file in image_files:
                        file_size = file.fp.getbuffer().nbytes
                        if current_size + file_size > max_size:
                            chunks.append(current_chunk)
                            current_chunk = [file]
                            current_size = file_size
                        else:
                            current_chunk.append(file)
                            current_size += file_size
                    if current_chunk:
                        chunks.append(current_chunk)

                    param_str = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "None"
                    user_model = self.bot.user_model_preferences.get(author.id, DEFAULT_MODEL)
                    content = (
                        f"**Img2Img Prompt:** `{prompt}`\n"
                        f"**Negative Prompt:** `{negative_prompt if not params.get('noneg', 'false').lower() == 'true' else 'None'}`\n"
                        f"**Parameters:** `{param_str}`\n"
                        f"**Model:** `{user_model}`\n"
                        f"**Time:** `{duration}`\n"
                        f"{author.mention}, images split due to size. React with ✅ to approve, ❌ to delete, or 🔁 to regenerate."
                    )
                    sent_messages = []
                    for chunk in chunks:
                        msg = await channel.send(content if not sent_messages else "Continued...", files=chunk)
                        sent_messages.append(msg)
                        if not sent_messages[1:]:
                            reaction = await handle_reactions(self.bot, msg, author, content, chunk)
                            if reaction == '✅':
                                await msg.clear_reactions()
                            elif reaction == '❌':
                                for m in sent_messages:
                                    await m.delete()
                            elif reaction == '🔁':
                                for m in sent_messages:
                                    await m.delete()
                                await self.handle_generation_request(channel, author, prompt, negative_prompt, params, init_image_bytes)
                    return

                param_str = ", ".join(f"{k}: {v}" for k, v in params.items()) if params else "None"
                user_model = self.bot.user_model_preferences.get(author.id, DEFAULT_MODEL)
                content = (
                    f"**Img2Img Prompt:** `{prompt}`\n"
                    f"**Negative Prompt:** `{negative_prompt if not params.get('noneg', 'false').lower() == 'true' else 'None'}`\n"
                    f"**Parameters:** `{param_str}`\n"
                    f"**Model:** `{user_model}`\n"
                    f"**Time:** `{duration}`\n"
                    f"{author.mention}, react with ✅ to approve, ❌ to delete, or 🔁 to regenerate."
                )
                await wait_message.delete()
                sent_message = await channel.send(content, files=image_files)
                reaction = await handle_reactions(self.bot, sent_message, author, content, image_files)
                if reaction == '✅':
                    await sent_message.clear_reactions()
                elif reaction == '❌':
                    await sent_message.delete()
                elif reaction == '🔁':
                    await sent_message.delete()
                    await self.handle_generation_request(channel, author, prompt, negative_prompt, params, init_image_bytes)
            else:
                await wait_message.delete()
                await channel.send("Failed to generate image or timed out.")
        except asyncio.TimeoutError:
            await wait_message.delete()
            await channel.send("Generation took too long. Try again later.")
        except discord.errors.HTTPException as e:
            logger.error(f"Discord HTTP error: {e}")
            await wait_message.delete()
            await channel.send("Failed to upload images. They might be too large.")
        except Exception as e:
            logger.error(f"Img2img error: {e}", exc_info=True)
            await wait_message.delete()
            await channel.send(f"Error: {str(e)}. Please try again later.")
        finally:
            init_image_bytes.seek(0)  # Reset, caller closes

async def setup(bot):
    await bot.add_cog(Img2ImgCog(bot))