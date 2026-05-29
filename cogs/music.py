import asyncio
import discord
import yt_dlp
import json
import os
import random
import math

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

class PlaylistManager:
    """JSON 파일을 이용해 플레이리스트를 영구 저장하고 관리하는 클래스"""
    def __init__(self, filepath="playlists.json"):
        self.filepath = filepath
        self.playlists = self._load_data()

    def _load_data(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_data(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.playlists, f, ensure_ascii=False, indent=4)

    def add_song(self, playlist, title, url):
        if playlist not in self.playlists:
            self.playlists[playlist] = []
        
        if any(track['url'] == url for track in self.playlists[playlist]):
            return False
            
        self.playlists[playlist].append({"title": title, "url": url})
        self.save_data()
        return True

    def delete_song(self, playlist, index):
        if playlist in self.playlists and 0 <= index < len(self.playlists[playlist]):
            deleted = self.playlists[playlist].pop(index)
            if not self.playlists[playlist]:
                del self.playlists[playlist]
            self.save_data()
            return deleted
        return None

    def get_tracks(self, playlist_name, shuffle=False):
        """특정 플레이리스트의 곡 목록을 가져오거나, '통합' 입력 시 모든 곡을 중복 없이 병합하여 가져옵니다."""
        tracks = []
        
        if playlist_name == "통합":
            for pl_tracks in self.playlists.values():
                tracks.extend(pl_tracks)
                
            unique_tracks = {}
            for track in tracks:
                unique_tracks[track['url']] = track
            tracks = list(unique_tracks.values())
            
        elif playlist_name in self.playlists:
            tracks = list(self.playlists[playlist_name])
        else:
            return []

        if shuffle:
            random.shuffle(tracks)
            
        return tracks
    
    def get_all_playlists(self):
        """생성된 모든 플레이리스트(플리)의 이름과 곡 수를 반환합니다."""
        return {playlist: len(tracks) for playlist, tracks in self.playlists.items() if tracks}

    def delete_playlist(self, playlist):
        """특정 플레이리스트(폴더)를 통째로 삭제합니다."""
        if playlist in self.playlists:
            del self.playlists[playlist]
            self.save_data()
            return True
        return False

class PlaylistPaginator(discord.ui.View):
    """플리 노래 목록을 10곡씩 잘라서 보여주는 버튼 UI 클래스"""
    def __init__(self, tracks, playlist_name):
        super().__init__(timeout=120)
        self.tracks = tracks
        self.playlist_name = playlist_name
        self.current_page = 1
        self.per_page = 10
        self.total_pages = math.ceil(len(tracks) / self.per_page)

    def create_embed(self):
        """현재 페이지에 맞는 임베드 메시지를 생성합니다."""
        start_idx = (self.current_page - 1) * self.per_page
        end_idx = start_idx + self.per_page
        page_tracks = self.tracks[start_idx:end_idx]

        message = ""
        for idx, track in enumerate(page_tracks, start=start_idx + 1):
            message += f"**{idx}.** {track['title']}\n"

        embed = discord.Embed(
            title=f":folder: '{self.playlist_name}' 플리 노래 목록 ({len(self.tracks)}곡)",
            description=message,
            color=discord.Color.from_str("#1a75ff")
        )
        embed.set_footer(text=f"페이지 {self.current_page} / {self.total_pages}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == 1:
            self.current_page = self.total_pages
        else:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == self.total_pages:
            self.current_page = 1
        else:
            self.current_page += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

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
        self.webpage_url = data.get('webpage_url') or data.get('original_url') or self.url

    @classmethod
    async def from_url(cls, query, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        
        is_url = query.startswith(('http://', 'https://'))
        search_query = query if is_url else f"ytsearch:{query}"
        
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=not stream))

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
        self.playlist_manager = PlaylistManager()

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
        """대기열에 음악 추가 (= /재생 [검색어]) [= !play, !p]"""
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
                description=f'[{player.title}]({player.webpage_url})',
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
            item = await state.queue.get()
            
            if isinstance(item, dict) and item.get('lazy'):
                try:
                    state.current = await YTDLSource.from_url(item['url'], loop=self.bot.loop, stream=True)
                except Exception as e:
                    print(f"재생 오류: {e}")
                    return asyncio.run_coroutine_threadsafe(self.play_check(ctx, e), self.bot.loop)
            else:
                state.current = item
            
            if state.current is None:
                 return self.bot.loop.create_task(self.play_check(ctx, Exception("곡 정보를 불러올 수 없습니다.")))

            state.is_playing = True
            ctx.voice_client.play(state.current, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_check(ctx, e), self.bot.loop))

            position = state.queue.qsize()

            duration_sec = state.current.data.get("duration") or 0
            h, rem = divmod(duration_sec, 3600)
            m, s = divmod(rem, 60)
            duration_str = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

            embed=discord.Embed(
                title=f':musical_note: NOW PLAYING: {state.current.title} :level_slider:',
                description=f'[{state.current.title}]({state.current.webpage_url})',
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

    @commands.hybrid_command(name="대기열", aliases=["playingnext", "pn"])
    async def show_queue(self, ctx):
        """대기열 목록 출력 (= /대기열) [= !playingnext, !pn]"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            message = ''
            temp_queue = list(state.queue._queue)
            for idx, item in enumerate(temp_queue, start=1):
                title = item['title'] if isinstance(item, dict) else item.title
                message += f'{idx}. {title}\n'

            embed = discord.Embed(
                title=":scroll: PLAYING NEXT :scroll:\n",
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

    @commands.hybrid_command(name="추가", aliases=["add", "pladd", "ㅁㅇㅇ"])
    @app_commands.describe(playlist="저장할 플레이리스트 이름", query="노래 제목 또는 링크")
    async def save_to_playlist(self, ctx, playlist: str, *, query: str):
        """원하는 플레이리스트에 노래를 영구 저장합니다. (= /추가 [플리 이름] [검색어])"""
        async with ctx.typing():
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            if player is None:
                await ctx.send(embed=discord.Embed(title=":x: 곡 정보를 가져올 수 없습니다.", color=discord.Color.from_str("#ff6600")))
                return

            is_added = self.playlist_manager.add_song(playlist, player.title, player.webpage_url)

            if is_added:
                embed = discord.Embed(
                    title=f":inbox_tray: '{playlist}' 플리에 저장 완료!",
                    description=f"[{player.title}]({player.webpage_url})",
                    color=discord.Color.from_str("#00ff00")
                )
            else:
                embed = discord.Embed(
                    title=":warning: 이미 플리에 존재하는 곡입니다.",
                    color=discord.Color.from_str("#ffcc00")
                )

            await ctx.send(embed=embed)

    @commands.hybrid_command(name="플리복사", aliases=["plcopy", "복사"])
    @app_commands.describe(playlist="저장할 플리 이름", url="유튜브 플레이리스트 링크")
    async def copy_youtube_playlist(self, ctx, playlist: str, url: str):
        """유튜브 플레이리스트의 모든 곡을 한 번에 복사해옵니다."""
        await ctx.send(embed=discord.Embed(title=f":hourglass_flowing_sand: 유튜브에서 '{playlist}' 플리 불러오는 중...", color=discord.Color.from_str("#1a75ff")))

        async with ctx.typing():
            info = await self.bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
            
            entries = info.get('entries', [])
            
            added_count = 0
            skipped_count = 0
            
            for entry in entries:
                title = entry.get('title')
                webpage_url = entry.get('webpage_url')
                
                if title and webpage_url:
                    if self.playlist_manager.add_song(playlist, title, webpage_url):
                        added_count += 1
                    else:
                        skipped_count += 1

        embed = discord.Embed(
            title=f":inbox_tray: 유튜브 플리 복사 완료!",
            description=f"성공: {added_count}곡\n중복되어 건너뜀: {skipped_count}곡",
            color=discord.Color.from_str("#00ff00")
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="노래목록", aliases=["sl", "songlist"])
    @app_commands.describe(playlist="확인할 플리 이름 (전체는 '통합' 입력)")
    async def show_playlist(self, ctx, playlist: str):
        """플레이리스트의 곡 목록을 보여줍니다. (= /노래목록 [플리 이름])"""
        tracks = self.playlist_manager.get_tracks(playlist)
        
        if not tracks:
            await ctx.send(embed=discord.Embed(
                title=":x: 해당 이름의 플리가 비어있거나 존재하지 않습니다.", 
                color=discord.Color.from_str("#ff6600")
            ))
            return

        view = PlaylistPaginator(tracks, playlist)
        
        await ctx.send(embed=view.create_embed(), view=view)

    @commands.hybrid_command(name="노래삭제", aliases=["삭제", "pdel"])
    @app_commands.describe(playlist="플리 이름", index="삭제할 곡 번호")
    async def delete_from_playlist(self, ctx, playlist: str, index: int):
        """플리에서 특정 곡을 삭제합니다. (= /노래삭제 [플리 이름] [번호])"""
        deleted = self.playlist_manager.delete_song(playlist, index - 1)
        if deleted:
            embed = discord.Embed(title=f":wastebasket: 삭제 완료: {deleted['title']}", color=discord.Color.from_str("#ffcc00"))
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=discord.Embed(title=":warning: 번호가 잘못되었거나 플리가 없습니다.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="플리재생", aliases=["playlistplay", "pp", "ㅔㅔ"])
    @app_commands.describe(playlist="플리 이름", mode="재생 모드 (순서대로/셔플)")
    @app_commands.choices(mode=[
        app_commands.Choice(name="순서대로", value="순서대로"),
        app_commands.Choice(name="셔플", value="셔플")
    ])
    async def play_playlist(self, ctx, playlist: str, mode: str = "순서대로"):
        """플리의 노래들을 대기열에 일괄 추가하고 재생합니다. (= /플리재생 [플리 이름] [모드])"""
        tracks = self.playlist_manager.get_tracks(playlist, shuffle=(mode == "셔플"))
        if not tracks:
            await ctx.send(embed=discord.Embed(title=":x: 해당 플리가 비어있습니다.", color=discord.Color.from_str("#ff6600")))
            return

        state = self.get_state(ctx.guild.id)
        
        for track in tracks:
            await state.queue.put({'lazy': True, 'title': track['title'], 'url': track['url']})

        await ctx.send(embed=discord.Embed(
            title=f":white_check_mark: '{playlist}' 플리에서 {len(tracks)}곡 대기열 추가 완료! ({mode})", 
            color=discord.Color.from_str("#00ff00")
        ))

        if not state.is_playing and not ctx.voice_client.is_paused():
            await self.play_next(ctx)

    @commands.hybrid_command(name="플리목록", aliases=["pllist"])
    async def list_playlists(self, ctx):
        """현재 만들어진 모든 플레이리스트 목록과 곡 수를 보여줍니다. (= /플리목록)"""
        playlists = self.playlist_manager.get_all_playlists()
        
        if not playlists:
            await ctx.send(embed=discord.Embed(
                title=":x: 아직 생성된 플레이리스트가 없습니다.", 
                description="`/추가 [플리 이름] [노래]` 명령어로 새 플리를 만들어 보세요!",
                color=discord.Color.from_str("#ff6600")
            ))
            return

        message = ""
        for idx, (name, count) in enumerate(playlists.items(), start=1):
            message += f"**{idx}.** 📁 {name} (총 {count}곡)\n"

        embed = discord.Embed(
            title=f":file_folder: 전체 플레이리스트 목록 (총 {len(playlists)}개)",
            description=message,
            color=discord.Color.from_str("#1a75ff")
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="플리삭제", aliases=["pldelete"])
    @app_commands.describe(playlist="통째로 삭제할 플레이리스트 이름")
    async def delete_entire_playlist(self, ctx, playlist: str):
        """플레이리스트 폴더 자체를 통째로 삭제합니다. (= /플리삭제 [플리 이름])"""
        
        if playlist not in self.playlist_manager.playlists:
            embed = discord.Embed(
                title=":x: 해당 이름의 플레이리스트가 존재하지 않습니다.", 
                color=discord.Color.from_str("#ff6600")
            )
            return await ctx.send(embed=embed)

        warning_embed = discord.Embed(
            title=":warning: 플레이리스트 영구 삭제 경고",
            description=f"정말 **'{playlist}'** 플레이리스트를 통째로 삭제하시겠습니까?\n이 작업은 되돌릴 수 없으며, 저장된 모든 곡이 날아갑니다.\n\n삭제를 진행하려면 채팅창에 아래 이름을 정확히 타이핑해 주세요.\n\n`{playlist}`",
            color=discord.Color.red()
        )
        warning_embed.set_footer(text="⏳ 60초 이내에 입력하지 않으면 자동으로 취소됩니다.")
        await ctx.send(embed=warning_embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title=":timer: 시간이 초과되어 삭제가 취소되었습니다.", 
                color=discord.Color.green()
            )
            return await ctx.send(embed=timeout_embed)

        if msg.content == playlist:
            self.playlist_manager.delete_playlist(playlist)
            success_embed = discord.Embed(
                title=f":wastebasket: '{playlist}' 플레이리스트가 완전히 삭제되었습니다.", 
                color=discord.Color.from_str("#ffcc00")
            )
            await ctx.send(embed=success_embed)
        else:
            cancel_embed = discord.Embed(
                title=":x: 이름이 일치하지 않아 삭제가 안전하게 취소되었습니다.", 
                color=discord.Color.green()
            )
            await ctx.send(embed=cancel_embed)

    @play_playlist.before_invoke
    async def ensure_voice_playlist(self, ctx):
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

    @commands.hybrid_command(name="제외", aliases=["remove", "rm"])
    @app_commands.describe(index="대기열에서 제외할 노래 번호")
    async def remove(self, ctx, index: int):
        """대기열에 있는 곡 삭제. (= /제외 [번호]) [= !remove, rm]"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            temp_queue = list(state.queue._queue)
            if 0 < index <= len(temp_queue):
                removed = temp_queue.pop(index - 1)

                title = removed['title'] if isinstance(removed, dict) else removed.title

                embed=discord.Embed(
                    title=f':wastebasket: 삭제: {title} :wastebasket:',
                    color=discord.Color.from_str("#ffcc00")
                )
                await ctx.send(embed=embed)
                
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

    @commands.hybrid_command(name="초기화", aliases=["clearqueue", "대기열비우기", "cq", "clear"])
    async def clear_queue(self, ctx):
        """대기열에 있는 모든 곡을 한 번에 삭제합니다. (= /초기화) [= !cq, !clearqueue, !clear]"""
        state = self.get_state(ctx.guild.id)
        
        if state.queue.empty():
            embed = discord.Embed(
                title=":question: 대기열이 이미 비어 있습니다 :grey_question:",
                color=discord.Color.from_str("#ff6600")
            )
            return await ctx.send(embed=embed)

        cleared_count = state.queue.qsize()
        
        state.queue = asyncio.Queue()
        
        embed = discord.Embed(
            title=f":wastebasket: 대기열에 있던 {cleared_count}곡을 모두 삭제했습니다!",
            description="현재 재생 중인 곡은 계속 재생됩니다.",
            color=discord.Color.from_str("#ffcc00")
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