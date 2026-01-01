import discord
from discord.ext import commands
from discord import app_commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def command_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        commands_list = [cmd.name for cmd in self.bot.commands if not cmd.hidden]
        return [
            app_commands.Choice(name=cmd, value=cmd)
            for cmd in commands_list if current.lower() in cmd.lower()
        ][:25]
    
    @commands.hybrid_command(name="도움말", aliases=["help"])
    @app_commands.describe(command_name="(옵션) 명령어 이름")
    @app_commands.autocomplete(command_name=command_autocomplete)
    async def help(self, ctx, command_name: str = None):
        """명령어 목록 보여주기 (= /도움말 [(선택사항) 명령어 이름]) [= !help]"""
        
        if command_name:
            command = self.bot.get_command(command_name)
            
            if not command or command.hidden:
                embed = discord.Embed(
                    title=":warning: 존재하지 않는 명령어입니다 :warning:",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return

            embed = discord.Embed(
                title=f"명령어: {command.name}",
                description=command.help or "설명 없음",
                color=discord.Color.from_str("#ffffff")
            )
            if command.aliases:
                embed.add_field(name="별칭", value=", ".join(f"`{alias}`" for alias in command.aliases), inline=False)
            
            await ctx.send(embed=embed)

        else:
            embed = discord.Embed(
                title=":clipboard: 도움말 :clipboard:",
                color=discord.Color.from_str("#ffffff")
            )
            
            cogs = self.bot.cogs
            
            for cog_name, cog in cogs.items():
                commands_list = cog.get_commands()
                visible_commands = [cmd for cmd in commands_list if not cmd.hidden]
                
                if not visible_commands:
                    continue
                
                cmd_names = ", ".join([f"`{cmd.name}`" for cmd in visible_commands])
                embed.add_field(name=cog.qualified_name, value=cmd_names, inline=False)
            
            uncategorized = [cmd for cmd in self.bot.commands if cmd.cog is None and not cmd.hidden]
            if uncategorized:
                 cmd_names = ", ".join([f"`{cmd.name}`" for cmd in uncategorized])
                 embed.add_field(name="기타", value=cmd_names, inline=False)

            embed.set_footer(text=f"명령어 도움말: {ctx.clean_prefix}help [명령어]")
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Help(bot))