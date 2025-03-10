# cogs/Admin.py
import discord
from discord.ext import commands
import logging
import json
import os
import asyncio
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

load_dotenv()
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")  # Can be None if not set

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.admin_file = "admins.json"
        self.admins = self.load_admins()
        self.admin_role_id = int(ADMIN_ROLE_ID) if ADMIN_ROLE_ID and ADMIN_ROLE_ID.isdigit() else None
        logger.debug(f"Initialized AdminCog with admins: {self.admins}")
        logger.debug(f"Bot owner_id: {self.bot.owner_id}")
        logger.debug(f"Admin role ID: {self.admin_role_id}")

    def load_admins(self):
        """Load admin IDs from admins.json, creating an empty list if it doesn't exist or is invalid."""
        try:
            if os.path.exists(self.admin_file):
                with open(self.admin_file, 'r') as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                        logger.error(f"{self.admin_file} is not a list, resetting to empty")
                        self.save_admins([])
                        return []
                    valid_admins = []
                    for admin_id in data:
                        if isinstance(admin_id, str) and admin_id.isdigit():
                            valid_admins.append(admin_id)
                        else:
                            logger.warning(f"Invalid admin ID in {self.admin_file}: {admin_id}")
                    return valid_admins
            else:
                logger.info(f"{self.admin_file} not found, creating empty admin list.")
                self.save_admins([])
                return []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self.admin_file}: {e}, resetting to empty")
            self.save_admins([])
            return []
        except Exception as e:
            logger.error(f"Error loading admins: {e}")
            return []

    def save_admins(self, admins):
        """Save admin IDs to admins.json."""
        try:
            with open(self.admin_file, 'w') as f:
                json.dump(admins, f, indent=4)
            logger.debug("Admins saved successfully.")
        except Exception as e:
            logger.error(f"Error saving admins: {e}")

    async def is_admin(self, ctx):
        """Check if a user is an admin, guild owner, has admin role, or is bot owner."""
        user_id = str(ctx.author.id)
        logger.debug(f"Checking admin status for user_id: {user_id}")
        logger.debug(f"Admins list: {self.admins}")
        if user_id in self.admins:
            logger.debug(f"{user_id} found in admins.json")
            return True
        if ctx.guild and self.admin_role_id:
            member = ctx.guild.get_member(ctx.author.id) or await ctx.guild.fetch_member(ctx.author.id)
            if member and any(role.id == self.admin_role_id for role in member.roles):
                logger.debug(f"{user_id} has admin role ID {self.admin_role_id}")
                return True
        if ctx.guild:
            if ctx.guild.owner is None:
                logger.warning(f"Guild owner is None for guild {ctx.guild.id}, attempting to fetch guild data")
                try:
                    guild = self.bot.get_guild(ctx.guild.id) or await self.bot.fetch_guild(ctx.guild.id)
                    if guild is None:
                        logger.error(f"Failed to fetch guild {ctx.guild.id}")
                    elif guild.owner_id == ctx.author.id:
                        logger.debug(f"{user_id} is guild owner (fetched), Guild: {guild.name}, Owner ID: {guild.owner_id}")
                        return True
                    else:
                        logger.debug(f"{user_id} is not guild owner (fetched owner: {guild.owner_id})")
                except Exception as e:
                    logger.error(f"Error fetching guild {ctx.guild.id}: {e}")
            elif ctx.guild.owner.id == ctx.author.id:
                logger.debug(f"{user_id} is guild owner, Guild: {ctx.guild.name}, Owner ID: {ctx.guild.owner.id}")
                return True
            else:
                logger.debug(f"{user_id} is not guild owner (owner: {ctx.guild.owner_id if ctx.guild.owner else 'None'})")
        else:
            logger.debug("Command run in DMs, no guild context")
        logger.debug(f"Bot owner_id: {self.bot.owner_id}")
        if not self.admins and self.bot.owner_id:
            if user_id == str(self.bot.owner_id):
                logger.debug(f"{user_id} is bot owner")
                return True
        logger.debug(f"{user_id} is not an admin")
        return False

    async def cog_check(self, ctx):
        """Global check to restrict all commands in this cog to admins, guild owners, or bot owner."""
        if not await self.is_admin(ctx):
            await ctx.send("You do not have permission to use this command.")
            return False
        return True

    @commands.command(name="reload")
    async def reload(self, ctx, cog: str = None):
        """Reload a specific cog or all cogs."""
        if cog:
            try:
                await self.bot.reload_extension(f"cogs.{cog}")
                await ctx.send(f"Reloaded cog: {cog}")
                logger.info(f"Reloaded cog: {cog} by {ctx.author}")
            except Exception as e:
                await ctx.send(f"Failed to reload {cog}: {str(e)}")
                logger.error(f"Reload failed for {cog}: {e}")
        else:
            for filename in os.listdir("cogs"):
                if filename.endswith(".py") and filename != "__init__.py":
                    try:
                        await self.bot.reload_extension(f"cogs.{filename[:-3]}")
                        logger.info(f"Reloaded cog: {filename[:-3]}")
                    except Exception as e:
                        logger.error(f"Reload failed for {filename[:-3]}: {e}")
            await ctx.send("Reloaded all cogs.")

    @commands.command(name="shutdown")
    async def shutdown(self, ctx):
        """Shut down the bot."""
        await ctx.send("Shutting down...")
        logger.info(f"Shutdown initiated by {ctx.author}")
        await self.bot.close()

    @commands.command(name="addadmin")
    async def add_admin(self, ctx, user: discord.User):
        """Add a user to the admin list."""
        user_id = str(user.id)
        if user_id in self.admins:
            await ctx.send(f"{user.name} is already an admin.")
            return
        self.admins.append(user_id)
        self.save_admins(self.admins)
        await ctx.send(f"Added {user.name} as an admin.")
        logger.info(f"Added admin: {user_id} by {ctx.author}")

    @commands.command(name="removeadmin")
    async def remove_admin(self, ctx, user: discord.User):
        """Remove a user from the admin list."""
        user_id = str(user.id)
        if user_id not in self.admins:
            await ctx.send(f"{user.name} is not an admin.")
            return
        self.admins.remove(user_id)
        self.save_admins(self.admins)
        await ctx.send(f"Removed {user.name} from admins.")
        logger.info(f"Removed admin: {user_id} by {ctx.author}")

    @commands.command(name="listadmins")
    async def list_admins(self, ctx):
        """List all current admins in a formatted embed."""
        embed = discord.Embed(title="Admin List", color=discord.Color.blue())

        # Bot Owner
        bot_owner = self.bot.get_user(self.bot.owner_id) if self.bot.owner_id else None
        embed.add_field(
            name="Bot Owner",
            value=bot_owner.mention if bot_owner else "Unknown",
            inline=False
        )

        # Server Owner (Super Admin)
        if ctx.guild:
            guild_owner = ctx.guild.owner
            if guild_owner is None:
                try:
                    guild = await self.bot.fetch_guild(ctx.guild.id)
                    guild_owner = guild.get_member(guild.owner_id) or await guild.fetch_member(guild.owner_id)
                except Exception as e:
                    logger.error(f"Error fetching guild owner: {e}")
            embed.add_field(
                name="Server Owner (Super Admin)",
                value=f"{guild_owner.mention} (Owner-equivalent)" if guild_owner else "Unknown",
                inline=False
            )
        else:
            embed.add_field(
                name="Server Owner (Super Admin)",
                value="No guild context (DMs)",
                inline=False
            )

        # Admins (via ID)
        if not self.admins:
            embed.add_field(name="Admins (via ID)", value="None", inline=False)
        else:
            admin_mentions = []
            for admin_id in self.admins:
                try:
                    user = self.bot.get_user(int(admin_id))
                    admin_mentions.append(user.mention if user else f"<@{admin_id}> (Unknown)")
                except ValueError:
                    logger.warning(f"Invalid admin ID in list: {admin_id}, skipping")
                    continue
            embed.add_field(
                name="Admins (via ID)",
                value=", ".join(admin_mentions) if admin_mentions else "None",
                inline=False
            )

        # Role-Based Admins
        if ctx.guild and self.admin_role_id:
            role = ctx.guild.get_role(self.admin_role_id)
            if role:
                role_members = [m.mention for m in ctx.guild.members if role in m.roles]
                embed.add_field(
                    name="Role-Based Admins",
                    value=f"Users with the '{role.name}' role ({role.mention})\n" + 
                          (", ".join(role_members) if role_members else "None"),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Role-Based Admins",
                    value="Admin role not found in this guild",
                    inline=False
                )
        else:
            embed.add_field(
                name="Role-Based Admins",
                value="No admin role set or not in a guild",
                inline=False
            )

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))