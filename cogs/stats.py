# cogs/stats.py
import discord
from discord.ext import commands
import logging
import sqlite3
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class StatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def update_user_stats(self, guild_id: str, user_id: int, username: str, images: int = 0, canvas_contributions: int = 0, evolutions: int = 0, depth_maps: int = 0, total_time: float = 0):
        with sqlite3.connect(self.bot.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO user_stats (
                    guild_id, user_id, images, canvas_contributions, evolutions, depth_maps, last_generated, total_time, username
                ) VALUES (?, ?, 
                        COALESCE((SELECT images FROM user_stats WHERE guild_id = ? AND user_id = ?), 0) + ?,
                        COALESCE((SELECT canvas_contributions FROM user_stats WHERE guild_id = ? AND user_id = ?), 0) + ?,
                        COALESCE((SELECT evolutions FROM user_stats WHERE guild_id = ? AND user_id = ?), 0) + ?,
                        COALESCE((SELECT depth_maps FROM user_stats WHERE guild_id = ? AND user_id = ?), 0) + ?,
                        ?, 
                        COALESCE((SELECT total_time FROM user_stats WHERE guild_id = ? AND user_id = ?), 0) + ?,
                        ?)
            """, (guild_id, user_id, 
                  guild_id, user_id, images,
                  guild_id, user_id, canvas_contributions,
                  guild_id, user_id, evolutions,
                  guild_id, user_id, depth_maps,
                  datetime.now().isoformat(),
                  guild_id, user_id, total_time,
                  username))
            conn.commit()
        logger.debug(f"Updated stats for {username} ({user_id}) in guild {guild_id}: images +{images}, canvas +{canvas_contributions}, evolutions +{evolutions}, depth_maps +{depth_maps}, time +{total_time}")

    @commands.command(name="stats")
    async def stats_command(self, ctx):
        guild_id = str(ctx.guild.id) if ctx.guild else "DM"
        user_id = ctx.author.id
        with sqlite3.connect(self.bot.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT images, canvas_contributions, evolutions, depth_maps, last_generated, total_time
                FROM user_stats 
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id))
            row = c.fetchone()
        
        stats = row if row else (0, 0, 0, 0, "Never", 0)
        embed = discord.Embed(title=f"✨ {ctx.author.name}'s Stats ✨", color=discord.Color.blue())
        embed.add_field(name="Images Generated", value=stats[0], inline=True)
        embed.add_field(name="Canvas Contributions", value=stats[1], inline=True)
        embed.add_field(name="Evolutions", value=stats[2], inline=True)
        embed.add_field(name="Depth Maps", value=stats[3], inline=True)
        embed.add_field(name="Last Generated", value=stats[4], inline=False)
        embed.add_field(name="Total Time (s)", value=f"{stats[5]:.2f}", inline=False)
        embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
        await ctx.send(embed=embed)

    @commands.command(name="leaderboard")
    async def leaderboard_command(self, ctx, top_n: int = 5):
        if not ctx.guild:
            await ctx.send("This command can only be used in a guild.")
            return
        
        guild_id = str(ctx.guild.id)
        with sqlite3.connect(self.bot.db_path) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, images, username 
                FROM user_stats 
                WHERE guild_id = ? 
                ORDER BY images DESC 
                LIMIT ?
            """, (guild_id, top_n))
            rows = c.fetchall()

        if not rows:
            await ctx.send("No stats recorded for this guild yet.")
            return

        leaderboard_lines = []
        for i, (user_id, count, username) in enumerate(rows, 1):
            if not username:
                user = self.bot.get_user(int(user_id))
                username = user.display_name if user else f"Unknown User ({user_id})"
            leaderboard_lines.append(f"{i}. {username} - {count} images")

        embed = discord.Embed(
            title=f"🏆 Top {top_n} Creators in {ctx.guild.name} 🏆",
            description="\n".join(leaderboard_lines),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Stats based on images generated via !draw command")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(StatsCog(bot))