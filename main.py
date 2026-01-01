import datetime
import logging
import os
import traceback
import typing
import platform

import discord
from discord.ext import commands
from dotenv import load_dotenv
from discord import opus

#macOS - Opus 라이브러리 로드
if platform.system() == 'Darwin':
    if not opus.is_loaded():
        opus_paths = [
            '/opt/homebrew/lib/libopus.dylib',      # Apple Silicon (M1, M2, M3, M4)
            '/usr/local/lib/libopus.dylib',         # Intel Mac
        ]
        
        found = False
        for path in opus_paths:
            try:
                opus.load_opus(path)
                found = True
                break
            except OSError:
                continue
        
        if not found:
            print("경고: Opus 라이브러리를 찾을 수 없습니다. 'brew install opus'를 실행했는지 확인하세요.")


# class CustomHelpCommand(commands.HelpCommand):
#     async def send_bot_help(self, mapping):
#         embed = discord.Embed(
#             title=":clipboard: 도움말 :clipboard:",
#             color=discord.Color.from_str("#ffffff")
#         )
#         for cog, commands_list in mapping.items():
#             commands_list = [cmd for cmd in commands_list if not cmd.hidden]
#             if not commands_list:
#                 continue
#             cog_name = cog.qualified_name if cog else "기타"
#             cmd_names = ", ".join([f"`{cmd.name}`" for cmd in commands_list])
#             embed.add_field(name=cog_name, value=cmd_names, inline=False)
        
#         embed.set_footer(text=f"명령어 도움말: {self.context.clean_prefix}help [명령어]")
#         await self.get_destination().send(embed=embed)

#     async def send_command_help(self, command):
#         embed = discord.Embed(
#             title=f"명령어: {command.name}",
#             description=command.help or "설명 없음",
#             color=discord.Color.from_str("#ffffff")
#         )
#         if command.aliases:
#             embed.add_field(name="별칭", value=", ".join(f"`{alias}`" for alias in command.aliases), inline=False)
#         await self.get_destination().send(embed=embed)

class CustomBot(commands.Bot):
    _uptime: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)

    def __init__(self, prefix: str, ext_dir: str, *args: typing.Any, **kwargs: typing.Any) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(*args, **kwargs, command_prefix=commands.when_mentioned_or(prefix), intents=intents, help_command=None)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ext_dir = ext_dir
        self.synced = False

    async def _load_extensions(self) -> None:
        if not os.path.isdir(self.ext_dir):
            self.logger.error(f"Extension directory {self.ext_dir} does not exist.")
            return
        for filename in os.listdir(self.ext_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                try:
                    await self.load_extension(f"{self.ext_dir}.{filename[:-3]}")
                    self.logger.info(f"Loaded extension {filename[:-3]}")
                except commands.ExtensionError:
                    self.logger.error(f"Failed to load extension {filename[:-3]}\n{traceback.format_exc()}")

    async def on_error(self, event_method: str, *args: typing.Any, **kwargs: typing.Any) -> None:
        self.logger.error(f"An error occurred in {event_method}.\n{traceback.format_exc()}")

    async def on_ready(self) -> None:
        self.logger.info(f"Logged in as {self.user} ({self.user.id})")

    async def setup_hook(self) -> None:
        await self._load_extensions()
        if not self.synced:
            await self.tree.sync()
            self.synced = not self.synced
            self.logger.info("Synced command tree")

    def run(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        load_dotenv()
        try:
            super().run(str(os.getenv("TOKEN")), *args, **kwargs)
        except (discord.LoginFailure, KeyboardInterrupt):
            self.logger.info("Exiting...")
            exit()

    @property
    def user(self) -> discord.ClientUser:
        assert super().user, "Bot is not ready yet"
        return typing.cast(discord.ClientUser, super().user)

    @property
    def uptime(self) -> datetime.timedelta:
        return datetime.datetime.now(datetime.timezone.utc) - self._uptime


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    bot = CustomBot(prefix="!", ext_dir="cogs")
    bot.run()


if __name__ == "__main__":
    main()