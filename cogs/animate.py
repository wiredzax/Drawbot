# animate.py
import discord
import os
from discord.ext import commands
from io import BytesIO
from datetime import datetime, timedelta
import asyncio
import uuid
from PIL import Image
import logging
import yaml
from typing import Dict, Optional, List, Tuple  # Added missing typing imports
from .utils import parse_prompt, check_vram_usage, submit_comfyui_workflow, fetch_comfyui_outputs, WORKFLOWS_PATH, COMFYUI_API_URL, AVAILABLE_MODELS, PROMPT_PREFIX, DEFAULT_NEGATIVE_PROMPT

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class AnimateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.animate_workflow = {}
        self.load_workflow()
        logger.info("AnimateCog initialized")

    def load_workflow(self):
        try:
            with open(os.path.join(WORKFLOWS_PATH, "animate_workflow.yaml"), 'r', encoding='utf-8') as f:
                workflow_data = yaml.safe_load(f)
                if workflow_data is None:
                    logger.error("animate_workflow.yaml is empty or invalid YAML")
                    return
                for key in list(workflow_data.keys()):
                    workflow_data[int(key)] = workflow_data.pop(key)
                self.animate_workflow.update(workflow_data)
                logger.info("animate_workflow.yaml loaded successfully")
        except Exception as e:
            logger.error(f"Error loading animate_workflow.yaml: {e}")

    async def generate_image_animate(self, prompt: str, negative_prompt: str, params: Dict[str, str], user_id: int, seed: int) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        logger.info(f"Generating animation frame for user {user_id} with seed {seed}")
        workflow = self.animate_workflow.copy()
        if not workflow:
            logger.error("Animate workflow not loaded")
            return None, None

        model_key = params.get("model", self.bot.user_model_preferences.get(user_id, "uncanny"))
        ckpt_name = AVAILABLE_MODELS.get(model_key.lower(), AVAILABLE_MODELS["uncanny"])
        workflow[3]["inputs"]["ckpt_name"] = ckpt_name

        no_neg = params.get("noneg", "false").lower() == "true"
        if ckpt_name == AVAILABLE_MODELS["uncanny"] and not no_neg:
            negative_prompt = "lowres, (worst quality, bad quality:1.2), bad anatomy, sketch, jpeg artifacts, old, oldest, censored, bar_censor, copyright_name, (dialogue), text, speech bubble, Dialogue box, error, fewer, extra, missing, worst quality, low quality, watermark, signature, extra digits, username, scan, abstract, multiple views, (censored), worst quality, low quality, logo, bad hands, mutated hands"
            prompt_prefix = "masterpiece, very awa, best quality, amazing quality, very aesthetic, absurdres, newest, intricate details"
            workflow[7]["inputs"]["cfg"] = 2.2
            workflow[7]["inputs"]["sampler_name"] = "euler_ancestral"
            workflow[7]["inputs"]["scheduler"] = "sgm_uniform"
        else:
            prompt_prefix = PROMPT_PREFIX

        workflow[5]["inputs"]["text"] = f"{prompt_prefix} {prompt}".strip()
        workflow[6]["inputs"]["text"] = "" if no_neg else (negative_prompt or DEFAULT_NEGATIVE_PROMPT)

        workflow[7]["inputs"]["steps"] = int(params.get("steps", 35))
        if ckpt_name != AVAILABLE_MODELS["uncanny"]:
            workflow[7]["inputs"]["cfg"] = float(params.get("cfg", 4.0))
        workflow[7]["inputs"]["seed"] = seed
        if ckpt_name != AVAILABLE_MODELS["uncanny"]:
            workflow[7]["inputs"]["sampler_name"] = params.get("sampler_name", "dpmpp_2m_sde")
            workflow[7]["inputs"]["scheduler"] = params.get("scheduler", "exponential")

        start_time = datetime.now()
        if not check_vram_usage():
            logger.warning("VRAM threshold exceeded before animate generation")
            return None, None

        prompt_id = await submit_comfyui_workflow(workflow)
        if not prompt_id:
            logger.error("Failed to submit animate workflow to ComfyUI")
            return None, None

        images = await fetch_comfyui_outputs(prompt_id)
        if images:
            return images, datetime.now() - start_time
        logger.warning("No images returned from animate workflow")
        return None, None

    @commands.command(name="animate")
    async def animate(self, ctx, *, prompt: str):
        logger.info(f"Animate command invoked by {ctx.author.id}: '{prompt}'")
        positive_prompt, negative_prompt_user, params = parse_prompt(self.bot, prompt)
        negative_prompt = negative_prompt_user if negative_prompt_user is not None else DEFAULT_NEGATIVE_PROMPT
        num_frames = min(int(params.get("frames", 5)), 10)
        frame_speed = max(50, min(int(params.get("speed", 500)), 2000))

        wait_message = await ctx.send("Generating animation... Please wait.")
        images = []
        start_time = datetime.now()
        base_seed = uuid.uuid4().int & (1<<63)-1

        for i in range(num_frames):
            seed = base_seed + i
            frame_images, _ = await self.generate_image_animate(positive_prompt, negative_prompt, params, ctx.author.id, seed)
            if frame_images:
                images.extend(frame_images)
            else:
                await wait_message.delete()
                await ctx.send(f"Failed to generate frame {i+1}.")
                return

        if images:
            frames = [Image.open(img).convert('RGB') for img in images]
            gif_buffer = BytesIO()
            frames[0].save(gif_buffer, format="GIF", save_all=True, append_images=frames[1:], duration=frame_speed, loop=0, optimize=True)
            gif_buffer.seek(0)
            file = discord.File(gif_buffer, filename=f"animation_{uuid.uuid4()}.gif")
            duration = datetime.now() - start_time
            await wait_message.delete()
            await ctx.send(f"Animation generated in {duration}", file=file)
            gif_buffer.close()
            for img in images:
                img.close()

async def setup(bot):
    logger.info("Setting up AnimateCog")
    await bot.add_cog(AnimateCog(bot))