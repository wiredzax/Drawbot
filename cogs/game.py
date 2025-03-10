import discord
from discord.ext import commands
import logging
import os
from io import BytesIO
from typing import Optional, List, Tuple
from datetime import datetime, timedelta  # Updated to import timedelta
import asyncio
import uuid
from .utils import check_vram_usage

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class GameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game_active = False
        self.evolution_steps = []
        self.current_step = 0
        self.max_steps = 5

    async def evolve_image(self, prompt: str, init_image_bytes: BytesIO, user_id: int) -> Tuple[Optional[List[BytesIO]], Optional[timedelta]]:
        img2img_cog = self.bot.get_cog("Img2ImgCog")
        if not img2img_cog:
            return None, None
        return await img2img_cog.generate_image_img2img(prompt, init_image_bytes, "DeepNegative_xl_v1", {}, user_id)

    @commands.command(name="startgame")
    async def start_game(self, ctx, *, prompt: str):
        """Starts an image evolution game with an initial prompt."""
        if self.game_active:
            await ctx.send("A game is already active! Finish it with !evolve or wait.")
            return
        
        txt2img_cog = self.bot.get_cog("Txt2ImgCog")
        if not txt2img_cog:
            await ctx.send("Txt2ImgCog not loaded!")
            return

        self.game_active = True
        self.evolution_steps = []
        self.current_step = 0
        
        images, duration = await txt2img_cog.generate_image_txt2img(prompt, "DeepNegative_xl_v1", {}, ctx.author.id)
        if images:
            self.evolution_steps.append((prompt, images[0]))
            await ctx.send(f"Game started by {ctx.author.mention} with '{prompt}' (Step 1/{self.max_steps})", file=discord.File(images[0], filename="step_1.png"))
        else:
            self.game_active = False
            await ctx.send("Failed to start game.")

    @commands.command(name="evolve")
    async def evolve(self, ctx, *, prompt: str):
        """Evolves the current image with a new prompt."""
        if not self.game_active:
            await ctx.send("No game active! Start one with !startgame.")
            return
        if self.current_step >= self.max_steps:
            await ctx.send("Game complete! Here’s the evolution chain:")
            for i, (step_prompt, img) in enumerate(self.evolution_steps, 1):
                img.seek(0)
                await ctx.send(f"Step {i}: '{step_prompt}'", file=discord.File(img, filename=f"step_{i}.png"))
            self.game_active = False
            return

        init_image = self.evolution_steps[-1][1]
        wait_message = await ctx.send("Evolving image... Please wait.")
        images, duration = await self.evolve_image(prompt, init_image, ctx.author.id)
        
        if images:
            self.current_step += 1
            self.evolution_steps.append((prompt, images[0]))
            stats_cog = self.bot.get_cog("StatsCog")
            if stats_cog:
                stats_cog.update_user_stats(ctx.author.id, evolutions=1)
            await wait_message.delete()
            await ctx.send(f"Evolved by {ctx.author.mention} with '{prompt}' (Step {self.current_step + 1}/{self.max_steps})", file=discord.File(images[0], filename=f"step_{self.current_step + 1}.png"))
        else:
            await wait_message.delete()
            await ctx.send("Failed to evolve image.")

async def setup(bot):
    await bot.add_cog(GameCog(bot))