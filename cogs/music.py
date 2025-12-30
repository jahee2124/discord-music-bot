import asyncio
import discord
import yt_dlp
from discord.ext import commands

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
        self.guild_states: dict[int, GuildMusicState] = {}  # guild_id -> GuildMusicState

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
        """사용자가 있는 음성채널 입장 (= /입장)"""
        if channel is None and ctx.author.voice:
            channel = ctx.author.voice.channel

        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        if channel:
            await channel.connect()
        else:
            await ctx.send("음성 채널에 먼저 들어가거나 채널명을 입력해주세요.")

    @commands.hybrid_command(name="재생", aliases=["play", "p"])
    async def play(self, ctx, *, query):
        """플레이리스트에 음악 추가 (= /재생 [검색어])"""
        state = self.get_state(ctx.guild.id)

        async with ctx.typing():
            
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            if player is None:
                await ctx.send("노래를 가져오지 못했습니다. 검색어를 확인해주세요.")
                return

            await state.queue.put(player)
            position = state.queue.qsize()
            await ctx.send(f'{player.title}, #{position}번째로 대기열에 추가.')

            if not state.is_playing and not ctx.voice_client.is_paused():
                await self.play_next(ctx)

    async def play_next(self, ctx):
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            state.current = await state.queue.get()
            state.is_playing = True
            ctx.voice_client.play(state.current, after=lambda e: self.bot.loop.create_task(self.play_check(ctx, e)))
            await ctx.send(f'Now playing: {state.current.title}')
        else:
            state.current = None
            state.is_playing = False

    async def play_check(self, ctx, error):
        state = self.get_state(ctx.guild.id)
        if error:
            print(f'에러: {error}')
        state.is_playing = False
        await self.play_next(ctx)

    @commands.hybrid_command(name="스킵", aliases=["skip"])
    async def skip(self, ctx):
        """현재 재생중인 노래 스킵 (= /스킵)"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("현재 노래를 건너뜁니다.")
            await self.play_next(ctx)
        else:
            await ctx.send("현재 재생 중인 노래가 없습니다.")

    @commands.hybrid_command(name="정지", aliases=["pause"])
    async def pause(self, ctx):
        """재생중인 음악 일시정지 (= /일시정지)"""
        if ctx.voice_client.is_paused() or not ctx.voice_client.is_playing():
            await ctx.send("음악이 이미 일시 정지 중이거나 재생 중이지 않습니다.")
        else:
            ctx.voice_client.pause()
            await ctx.send("음악이 일시 정지되었습니다.")

    @commands.hybrid_command(name="재개", aliases=["resume"])
    async def resume(self, ctx):
        ''' 일시정지된 음악 다시 재생 (= /재개)'''
        if ctx.voice_client.is_playing() or not ctx.voice_client.is_paused():
            await ctx.send("음악이 이미 재생 중이거나 재생할 음악이 존재하지 않습니다.")
        else:
            ctx.voice_client.resume()
            await ctx.send("음악이 다시 재생됩니다.")

    @commands.hybrid_command(name="플리", aliases=["플레이리스트", "playlist"])
    async def playlist(self, ctx):
        """플레이리스트 목록 출력 (= /플리)"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            message = '플레이리스트:\n'
            temp_queue = list(state.queue._queue)
            for idx, player in enumerate(temp_queue, start=1):
                message += f'{idx}. {player.title}\n'
            await ctx.send(message)
        else:
            await ctx.send("대기열이 비어 있습니다.")

    @commands.hybrid_command(name="삭제", aliases=["delete", "remove"])
    async def remove(self, ctx, index: int):
        """플레이리스트에 있는 곡 삭제. (= /삭제 [번호])"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            temp_queue = list(state.queue._queue)
            if 0 < index <= len(temp_queue):
                removed = temp_queue.pop(index - 1)
                await ctx.send(f'삭제: {removed.title}')
                # Rebuild the queue
                state.queue = asyncio.Queue()
                for item in temp_queue:
                    await state.queue.put(item)
            else:
                await ctx.send("유효한 번호를 입력하세요.")
        else:
            await ctx.send("대기열이 비어 있습니다.")

    @commands.hybrid_command(name="음량", aliases=["volume"])
    async def volume(self, ctx, volume: int):
        """음량 조절 (= /음량 [1 ~ 100 (기본값 30)])"""

        if ctx.voice_client is None:
            return await ctx.send('Not connected to a voice channel.')

        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f'Changed volume to {volume}%')

    @commands.hybrid_command(name="퇴장", aliases=["quit"])
    async def stop(self, ctx):
        """재생을 중단하고 음성채널 퇴장 (= /퇴장)"""

        await ctx.voice_client.disconnect()

    @play.before_invoke
    async def ensure_voice(self, ctx):
        if not (ctx.author.voice and ctx.author.voice.channel):
            await ctx.send("You are not connected to a voice channel.")
            raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))