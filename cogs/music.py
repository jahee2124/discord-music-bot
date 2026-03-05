import asyncio
import discord
import yt_dlp
from discord.ext import commands
from discord import app_commands

yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['default', 'mweb'],
        }
    },
    'compat_opts': ['no-youtube-unavailable-videos'],
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class GuildMusicState:
    """서버별 음악 상태 관리"""
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.is_playing = False

    def clear(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.is_playing = False


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.3):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, query, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        url = data['url'] if stream else ytdl.prepare_filename(data)
        
        return cls(discord.FFmpegPCMAudio(
            url,
            before_options=ffmpeg_options['before_options'],
            options=ffmpeg_options['options']
        ), data=data)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        """서버별 상태 가져오기 (없으면 생성)"""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """음성 채널에 혼자 남으면 자동 퇴장"""
        if member.bot:
            return
        
        if before.channel is not None:
            voice_client = member.guild.voice_client
            
            if voice_client and voice_client.channel == before.channel:
                members = [m for m in before.channel.members if not m.bot]
                
                if len(members) == 0:
                    await asyncio.sleep(10)
                    
                    members = [m for m in voice_client.channel.members if not m.bot]
                    if len(members) == 0:
                        state = self.get_state(member.guild.id)
                        state.clear()
                        await voice_client.disconnect()

    @commands.hybrid_command(name="입장", aliases=["join"])
    async def join(self, ctx, *, channel: discord.VoiceChannel = None):
        """입력한 음성채널 또는 사용자가 있는 채널 입장 (= /입장) [= !join]"""
        if channel is None and ctx.author.voice:
            channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        if channel:
            await channel.connect()
        else:
            embed = discord.Embed(
                title=":warning: 음성 채널에 먼저 들어가거나 채널명을 입력해주세요 :warning:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="재생", aliases=["play", "p", "ㅔ", "P", "ㅖ"])
    @app_commands.describe(query="제목 또는 링크")
    async def play(self, ctx, *, query):
        """플레이리스트에 음악 추가 (= /재생 [검색어]) [= !play, !p]"""
        state = self.get_state(ctx.guild.id)

        async with ctx.typing():
            
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            if player is None:
                embed = discord.Embed(
                    title=":question: 노래를 가져오지 못했습니다. 검색어를 확인해주세요 :grey_question:",
                    color=discord.Color.from_str("#ff6600")
                )
                await ctx.send(embed=embed)
                return

            await state.queue.put(player)
            position = state.queue.qsize()

            duration_sec = player.data.get("duration") or 0
            h, rem = divmod(duration_sec, 3600)
            m, s = divmod(rem, 60)
            duration_str = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

            embed=discord.Embed(
                title=':mag_right: 음악 검색 결과 :cd:',
                description=f'[{player.title}]({player.url})',
                color=discord.Color.from_str("#1a75ff")
            )
            embed.add_field(name=":stopwatch: 길이", value=duration_str)
            embed.add_field(name=":scroll: 대기열", value=f"#{position}번째로 추가됨")
            thumbnail = player.data.get("thumbnail")
            if not thumbnail:
                thumbnails = player.data.get("thumbnails") or []
                thumbnail = thumbnails[-1]["url"] if thumbnails else None
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            await ctx.send(embed=embed)

            if not state.is_playing and not ctx.voice_client.is_paused():
                await self.play_next(ctx)

    async def play_next(self, ctx):
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            state.current = await state.queue.get()
            state.is_playing = True
            ctx.voice_client.play(state.current, after=lambda e: self.bot.loop.create_task(self.play_check(ctx, e)))

            position = state.queue.qsize()

            duration_sec = state.current.data.get("duration") or 0
            h, rem = divmod(duration_sec, 3600)
            m, s = divmod(rem, 60)
            duration_str = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

            embed=discord.Embed(
                title=f':musical_note: NOW PLAYING: {state.current.title} :level_slider:',
                description=f'[{state.current.title}]({state.current.url})',
                color=discord.Color.from_str("#00ff00")
            )
            embed.add_field(name=":stopwatch: 길이", value=duration_str)
            embed.add_field(name=":scroll: 대기열", value=f"#{position}곡 대기중")
            thumbnail = state.current.data.get("thumbnail")
            if not thumbnail:
                thumbnails = state.current.data.get("thumbnails") or []
                thumbnail = thumbnails[-1]["url"] if thumbnails else None
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            await ctx.send(embed=embed)
        else:
            state.current = None
            state.is_playing = False

    async def play_check(self, ctx, error):
        state = self.get_state(ctx.guild.id)
        if error:
            print(f'에러: {error}')
        state.is_playing = False
        await self.play_next(ctx)

    @commands.hybrid_command(name="스킵", aliases=["skip", "s"])
    async def skip(self, ctx):
        """현재 재생중인 노래 스킵 (= /스킵) [= !skip, !s]"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            embed = discord.Embed(
                title=":track_next: 현재 재생 중인 노래를 건너뜁니다 :track_next:",
                color=discord.Color.from_str("#ffcc00")
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=":question: 현재 재생 중인 노래가 없습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="정지", aliases=["pause", "일시정지"])
    async def pause(self, ctx):
        """재생중인 음악 일시정지 (= /정지) [= !pause, !일시정지]"""
        if ctx.voice_client is None:
            embed = discord.Embed(
                title=":warning: 봇이 음성 채널에 연결되어 있지 않습니다 :warning:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)
        elif ctx.voice_client.is_paused() or not ctx.voice_client.is_playing():
            embed = discord.Embed(
                title=":question: 음악이 이미 일시 정지 중이거나 재생 중이지 않습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)
        else:
            ctx.voice_client.pause()
            embed = discord.Embed(
                title=":pause_button: 음악이 일시 정지되었습니다 :pause_button:",
                color=discord.Color.from_str("#ffcc00")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="재개", aliases=["resume"])
    async def resume(self, ctx):
        """일시정지된 음악 다시 재생 (= /재개) [= !resume]"""
        if ctx.voice_client is None:
            embed = discord.Embed(
                title=":warning: 봇이 음성 채널에 연결되어 있지 않습니다 :warning:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)
        elif ctx.voice_client.is_playing() or not ctx.voice_client.is_paused():
            embed = discord.Embed(
                title=":question: 음악이 이미 재생 중이거나 재생할 음악이 존재하지 않습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)
        else:
            ctx.voice_client.resume()
            embed = discord.Embed(
                title=":arrow_forward: 음악이 다시 재생됩니다 :arrow_forward:",
                color=discord.Color.from_str("#ffcc00")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="플리", aliases=["플레이리스트", "playlist", "pl"])
    async def playlist(self, ctx):
        """플레이리스트 목록 출력 (= /플리) [= !playlist, !pl]"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            message = ''
            temp_queue = list(state.queue._queue)
            for idx, player in enumerate(temp_queue, start=1):
                message += f'{idx}. {player.title}\n'

            embed = discord.Embed(
                title=":scroll: PLAYLIST :scroll:\n",
                description=message,
                color=discord.Color.from_str("#1a75ff")
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=":question: 대기열이 비어 있습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="삭제", aliases=["delete", "remove", "rm"])
    @app_commands.describe(index="대기열에서 삭제할 노래 번호")
    async def remove(self, ctx, index: int):
        """플레이리스트에 있는 곡 삭제. (= /삭제 [번호]) [= !remove, rm]"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            temp_queue = list(state.queue._queue)
            if 0 < index <= len(temp_queue):
                removed = temp_queue.pop(index - 1)

                embed=discord.Embed(
                    title=f':wastebasket: 삭제: {removed.title} :wastebasket:',
                    color=discord.Color.from_str("#ffcc00")
                )
                await ctx.send(embed=embed)
                # Rebuild the queue
                state.queue = asyncio.Queue()
                for item in temp_queue:
                    await state.queue.put(item)
            else:
                embed = discord.Embed(
                title=":warning: 유효한 번호를 입력하세요 :warning:",
                color=discord.Color.from_str("#ff6600")
                )
                await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=":question: 대기열이 비어 있습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="음량", aliases=["volume", "볼륨", "vol"])
    @app_commands.describe(volume="(옵션) 0 - 100%")
    async def volume(self, ctx, volume: int = None):
        """음량 조절 또는 현재 음량 확인(= /음량 [(선택사항)1 ~ 100 (기본값 30)]) [= !volume, !볼륨]"""
        if ctx.voice_client is None:
            embed = discord.Embed(
                title=":warning: 봇이 음성 채널에 연결되어 있지 않습니다 :warning:",
                color=discord.Color.from_str("#ff6600")
            )
            return await ctx.send(embed=embed)
        
        if ctx.voice_client.source is None:
            embed = discord.Embed(
                title=":question: 현재 재생 중인 음악이 없습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            return await ctx.send(embed=embed)
        
        if volume is not None:
            volume = max(0, min(100, volume))
            ctx.voice_client.source.volume = volume / 100
            embed = discord.Embed(
            title=f":sound: 음량을 {volume}%로 변경했습니다 :level_slider:",
            color=discord.Color.from_str("#ffcc00")
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
            title=f":sound: 현재 음량: {ctx.voice_client.source.volume * 100}% :level_slider:",
            color=discord.Color.from_str("#ffcc00")
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="퇴장", aliases=["quit"])
    async def stop(self, ctx):
        """재생을 중단하고 음성채널 퇴장 (= /퇴장) [= !quit]"""
        if ctx.voice_client is None:
            embed = discord.Embed(
                title=":warning: 봇이 음성 채널에 연결되어 있지 않습니다 :warning:",
                color=discord.Color.from_str("#ff6600")
            )
            return await ctx.send(embed=embed)
        
        state = self.get_state(ctx.guild.id)
        state.clear()
        await ctx.voice_client.disconnect()

        embed = discord.Embed(
            title=":door: 음성 채널에서 퇴장했습니다 :robot:",
            color=discord.Color.from_str("#ffcc00")
        )
        await ctx.send(embed=embed)

    @play.before_invoke
    async def ensure_voice(self, ctx):
        if not (ctx.author.voice and ctx.author.voice.channel):
            embed=discord.Embed(
                title=":warning: 사용자가 음성 채널에 연결되어 있지 않습니다 :warning:",
                color=discord.Color.from_str("#ff6600")
            )
            await ctx.send(embed=embed)
            raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                embed=discord.Embed(
                    title=":warning: 사용자가 음성 채널에 연결되어 있지 않습니다 :warning:",
                    color=discord.Color.from_str("#ff6600")
                )
                await ctx.send(embed=embed)
                raise commands.CommandError("Author not connected to a voice channel.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))