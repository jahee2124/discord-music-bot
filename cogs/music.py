import asyncio
import discord
import yt_dlp
import json
import os
import random
import math
import time

from discord.ext import commands
from discord import app_commands

yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
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

def create_progress_bar(current_sec, total_sec, length=20):
    """재생 구간을 시각적 바(Bar)로 생성"""
    if total_sec == 0:
        return f"🔴 라이브 스트리밍 | {int(current_sec//60)}:{int(current_sec%60):02d}"
    
    progress = int((current_sec / total_sec) * length)
    progress = max(0, min(length, progress))
    bar = "▬" * progress + "🔘" + "▬" * (length - progress - 1)
    
    ch, crem = divmod(int(current_sec), 3600)
    cm, cs = divmod(crem, 60)
    curr_str = f"{ch}:{cm:02d}:{cs:02d}" if ch else f"{cm}:{cs:02d}"
    
    th, trem = divmod(int(total_sec), 3600)
    tm, ts = divmod(trem, 60)
    tot_str = f"{th}:{tm:02d}:{ts:02d}" if th else f"{tm}:{ts:02d}"
    
    return f"`{bar}`\n⏳ **{curr_str} / {tot_str}**"

# --- [PlaylistManager, Paginator 클래스는 기존과 동일] ---
class PlaylistManager:
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
        tracks = []
        if playlist_name == "통합":
            for pl_tracks in self.playlists.values():
                tracks.extend(pl_tracks)
            unique_tracks = {track['url']: track for track in tracks}
            tracks = list(unique_tracks.values())
        elif playlist_name in self.playlists:
            tracks = list(self.playlists[playlist_name])
        else:
            return []
        if shuffle: random.shuffle(tracks)
        return tracks
    
    def get_all_playlists(self):
        return {playlist: len(tracks) for playlist, tracks in self.playlists.items() if tracks}

    def delete_playlist(self, playlist):
        if playlist in self.playlists:
            del self.playlists[playlist]
            self.save_data()
            return True
        return False

class PlaylistPaginator(discord.ui.View):
    def __init__(self, tracks, playlist_name):
        super().__init__(timeout=120)
        self.tracks = tracks
        self.playlist_name = playlist_name
        self.current_page = 1
        self.per_page = 10
        self.total_pages = math.ceil(len(tracks) / self.per_page)

    def create_embed(self):
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
        if self.current_page == 1: self.current_page = self.total_pages
        else: self.current_page -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == self.total_pages: self.current_page = 1
        else: self.current_page += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

class QueuePaginator(discord.ui.View):
    def __init__(self, queue_list):
        super().__init__(timeout=120)
        self.queue_list = queue_list
        self.current_page = 1
        self.per_page = 10
        self.total_pages = math.ceil(len(queue_list) / max(1, self.per_page))

    def create_embed(self):
        start_idx = (self.current_page - 1) * self.per_page
        end_idx = start_idx + self.per_page
        page_tracks = self.queue_list[start_idx:end_idx]
        message = ""
        for idx, item in enumerate(page_tracks, start=start_idx + 1):
            title = item['title'] if isinstance(item, dict) else item.title
            message += f"**{idx}.** {title}\n"
        embed = discord.Embed(
            title=f":scroll: PLAYING NEXT (총 {len(self.queue_list)}곡) :scroll:",
            description=message,
            color=discord.Color.from_str("#1a75ff")
        )
        embed.set_footer(text=f"페이지 {self.current_page} / {self.total_pages}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == 1: self.current_page = max(1, self.total_pages)
        else: self.current_page -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page == self.total_pages: self.current_page = 1
        else: self.current_page += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


# --- [새로운 관리 상태 모델 및 UI 컨트롤러] ---
class GuildMusicState:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.is_playing = False
        
        # 신규 추가 변수들
        self.history = [] # 최대 10개 이전 곡 저장
        self.loop_mode = 0 # 0: 끔, 1: 한곡 반복, 2: 전체 대기열 반복
        self.volume = 0.3
        self.skip_request = False # 버튼/명령어로 스킵했는지 여부
        
        # 시간 추적용
        self.start_time = 0
        self.pause_time = 0
        self.total_paused_time = 0
        self.seek_offset = 0 # 앞/뒤로 가기 시 보정시간
        
        self.np_message = None # 현재 재생중 메시지 객체
        self.update_task = None # 상태 업데이트 비동기 태스크

    def get_current_time(self):
        if not self.is_playing or self.start_time == 0:
            return self.seek_offset
        if self.pause_time > 0:
            return (self.pause_time - self.start_time - self.total_paused_time) + self.seek_offset
        return (time.time() - self.start_time - self.total_paused_time) + self.seek_offset

    def clear(self):
        self.queue = asyncio.Queue()
        self.history.clear()
        self.current = None
        self.is_playing = False
        self.skip_request = False
        if self.update_task:
            self.update_task.cancel()


class MusicController(discord.ui.View):
    """Now Playing 메시지 하단에 부착될 리모컨 UI"""
    def __init__(self, cog, ctx):
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="mc_prev", row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state = self.cog.get_state(self.ctx.guild.id)
        if not state.history:
            return await interaction.followup.send("이전 곡 기록이 없습니다.", ephemeral=True)
        
        # 히스토리에서 마지막 곡 빼오기
        prev_song = state.history.pop()
        
        # 현재 곡이 있으면 현재 곡을 큐 맨 앞에 임시로 밀어넣음 (이전곡 듣고 원래 곡 듣도록)
        if state.current:
            temp_list = [{'lazy': True, 'title': state.current.title, 'url': state.current.webpage_url}] + list(state.queue._queue)
            state.queue = asyncio.Queue()
            for item in temp_list: await state.queue.put(item)
            
        # 이전 곡을 현재 재생 곡으로 세팅하기 위해 맨 앞에 넣고 강제 스킵
        temp_list = [prev_song] + list(state.queue._queue)
        state.queue = asyncio.Queue()
        for item in temp_list: await state.queue.put(item)
        
        state.skip_request = True
        self.ctx.voice_client.stop()

    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.secondary, custom_id="mc_rw", row=0)
    async def rw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.seek_music(self.ctx, -10)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="mc_playpause", row=0)
    async def playpause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = self.ctx.voice_client
        state = self.cog.get_state(self.ctx.guild.id)
        if vc:
            if vc.is_playing():
                vc.pause()
                state.pause_time = time.time()
            elif vc.is_paused():
                vc.resume()
                if state.pause_time > 0:
                    state.total_paused_time += (time.time() - state.pause_time)
                    state.pause_time = 0

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="mc_ff", row=0)
    async def ff_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.seek_music(self.ctx, 10)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="mc_next", row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state = self.cog.get_state(self.ctx.guild.id)
        if self.ctx.voice_client and self.ctx.voice_client.is_playing():
            state.skip_request = True
            self.ctx.voice_client.stop()

    @discord.ui.button(label="반복: 끔", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="mc_loop", row=1)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.ctx.guild.id)
        state.loop_mode = (state.loop_mode + 1) % 3
        
        if state.loop_mode == 0:
            button.label = "반복: 끔"
            button.style = discord.ButtonStyle.secondary
        elif state.loop_mode == 1:
            button.label = "반복: 현재 곡"
            button.style = discord.ButtonStyle.success
        elif state.loop_mode == 2:
            button.label = "반복: 대기열"
            button.style = discord.ButtonStyle.primary
            
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="mc_voldown", row=1)
    async def voldown_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state = self.cog.get_state(self.ctx.guild.id)
        if self.ctx.voice_client and self.ctx.voice_client.source:
            state.volume = max(0.0, state.volume - 0.1)
            self.ctx.voice_client.source.volume = state.volume

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="mc_volup", row=1)
    async def volup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state = self.cog.get_state(self.ctx.guild.id)
        if self.ctx.voice_client and self.ctx.voice_client.source:
            state.volume = min(1.0, state.volume + 0.1)
            self.ctx.voice_client.source.volume = state.volume


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.3):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url') or data.get('original_url') or self.url

    @classmethod
    async def from_url(cls, query, *, loop=None, stream=False, seek=0, volume=0.3):
        loop = loop or asyncio.get_event_loop()
        is_url = query.startswith(('http://', 'https://'))
        search_query = query if is_url else f"ytsearch:{query}"
        
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=not stream))

        if 'entries' in data:
            if len(data['entries']) > 0 and data['entries'][0] is not None:
                data = data['entries'][0]
            else:
                return None

        if data is None: return None
        url = data.get('url')
        if not url: return None
        url = url if stream else ytdl.prepare_filename(data)
        
        b_opts = ffmpeg_options['before_options']
        if seek > 0:
            b_opts = f"-ss {seek} " + b_opts
            
        return cls(discord.FFmpegPCMAudio(url, before_options=b_opts, options=ffmpeg_options['options']), data=data, volume=volume)

    @classmethod
    def create_direct(cls, data, seek=0, volume=0.3):
        """yt_dlp 추출 없이 오디오 다이렉트 URL로 바로 스트림 생성 (앞/뒤로 가기 속도 최적화)"""
        b_opts = ffmpeg_options['before_options']
        if seek > 0:
            b_opts = f"-ss {seek} " + b_opts
        return cls(discord.FFmpegPCMAudio(data['url'], before_options=b_opts, options=ffmpeg_options['options']), data=data, volume=volume)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_states: dict[int, GuildMusicState] = {}
        self.playlist_manager = PlaylistManager()

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id]

    # --- 백그라운드 태스크: 5초마다 재생바 갱신 ---
    async def progress_update_task(self, ctx):
        state = self.get_state(ctx.guild.id)
        while state.is_playing and state.current and state.np_message:
            await asyncio.sleep(5)  # 디스코드 API 제한 우회 (5초 권장)
            try:
                if ctx.voice_client and not ctx.voice_client.is_paused():
                    current_time = state.get_current_time()
                    total_time = state.current.data.get('duration') or 0
                    
                    embed = state.np_message.embeds[0]
                    # Description만 재생바 형식으로 교체
                    embed.description = create_progress_bar(current_time, total_time)
                    await state.np_message.edit(embed=embed)
            except Exception:
                break # 메시지 삭제됨 등의 에러 처리

    async def seek_music(self, ctx, offset):
        """음악 탐색 (앞/뒤로 가기)"""
        state = self.get_state(ctx.guild.id)
        if not state.current or not ctx.voice_client or not ctx.voice_client.is_playing():
            return
            
        current_time = state.get_current_time()
        new_time = max(0, current_time + offset)
        
        # 새 오디오 소스 생성 (yt-dlp 재추출 없이 다이렉트로 빠르게 생성)
        try:
            new_source = YTDLSource.create_direct(state.current.data, seek=new_time, volume=state.volume)
        except Exception:
            # 다이렉트 실패 시 재추출
            new_source = await YTDLSource.from_url(state.current.webpage_url, loop=self.bot.loop, stream=True, seek=new_time, volume=state.volume)
            
        # 스킵 처리되지 않게 플래그 세팅 후 스트림 교체
        state.skip_request = True 
        ctx.voice_client.stop()
        
        state.current = new_source
        state.start_time = time.time()
        state.pause_time = 0
        state.total_paused_time = 0
        state.seek_offset = new_time
        state.skip_request = False
        
        ctx.voice_client.play(state.current, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_check(ctx, e), self.bot.loop))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
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
        if channel is None and ctx.author.voice:
            channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)
        if channel:
            await channel.connect()
        else:
            await ctx.send(embed=discord.Embed(title=":warning: 음성 채널에 먼저 들어가주세요.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="재생", aliases=["play", "p", "ㅔ", "P", "ㅖ"])
    @app_commands.describe(query="제목 또는 링크")
    async def play(self, ctx, *, query):
        state = self.get_state(ctx.guild.id)
        async with ctx.typing():
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True, volume=state.volume)
            if player is None:
                return await ctx.send(embed=discord.Embed(title=":question: 노래를 가져오지 못했습니다.", color=discord.Color.from_str("#ff6600")))

            await state.queue.put(player)
            position = state.queue.qsize()

            embed = discord.Embed(
                title=':mag_right: 대기열 추가 완료 :cd:',
                description=f'[{player.title}]({player.webpage_url})\n> `#{position}번째 대기중`',
                color=discord.Color.from_str("#1a75ff")
            )
            await ctx.send(embed=embed)

            if not state.is_playing and not ctx.voice_client.is_paused():
                await self.play_next(ctx)

    async def play_next(self, ctx):
        state = self.get_state(ctx.guild.id)
        
        # 기존 갱신 태스크 취소
        if state.update_task:
            state.update_task.cancel()
            
        if not state.queue.empty():
            item = await state.queue.get()
            
            if isinstance(item, dict) and item.get('lazy'):
                try:
                    state.current = await YTDLSource.from_url(item['url'], loop=self.bot.loop, stream=True, volume=state.volume)
                except Exception as e:
                    await ctx.send(embed=discord.Embed(title=f":warning: 재생 불가: {item['title']}", color=discord.Color.red()))
                    return self.bot.loop.create_task(self.play_check(ctx, e))
            else:
                state.current = item
            
            if state.current is None:
                 return self.bot.loop.create_task(self.play_check(ctx, Exception("곡 정보를 불러올 수 없습니다.")))

            state.is_playing = True
            state.skip_request = False
            state.start_time = time.time()
            state.pause_time = 0
            state.total_paused_time = 0
            state.seek_offset = 0
            
            ctx.voice_client.play(state.current, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_check(ctx, e), self.bot.loop))

            # 컨트롤러 UI 및 임베드 생성
            view = MusicController(self, ctx)
            total_sec = state.current.data.get("duration") or 0
            
            embed=discord.Embed(
                title=f':musical_note: NOW PLAYING',
                description=create_progress_bar(0, total_sec),
                color=discord.Color.from_str("#00ff00")
            )
            embed.set_author(name=state.current.title, url=state.current.webpage_url)
            
            thumbnail = state.current.data.get("thumbnail")
            if not thumbnail:
                thumbnails = state.current.data.get("thumbnails") or []
                thumbnail = thumbnails[-1]["url"] if thumbnails else None
            if thumbnail: embed.set_thumbnail(url=thumbnail)
            
            state.np_message = await ctx.send(embed=embed, view=view)
            
            # 진행바 업데이트 백그라운드 작업 시작
            state.update_task = self.bot.loop.create_task(self.progress_update_task(ctx))
        else:
            state.current = None
            state.is_playing = False

    async def play_check(self, ctx, error):
        state = self.get_state(ctx.guild.id)
        if error: print(f'에러: {error}')
        
        # 1. 자연스럽게 끝났고(스킵 안됨) 재생하던 곡이 존재할 때 루프 처리
        if not state.skip_request and state.current:
            lazy_item = {'lazy': True, 'title': state.current.title, 'url': state.current.webpage_url}
            
            if state.loop_mode == 1: # 한곡 반복 (제일 앞으로)
                temp_list = [lazy_item] + list(state.queue._queue)
                state.queue = asyncio.Queue()
                for i in temp_list: await state.queue.put(i)
            elif state.loop_mode == 2: # 전체 반복 (제일 뒤로)
                await state.queue.put(lazy_item)

        # 2. 히스토리 기록 (루프모드가 한곡 반복이 아닐 때만 쌓임)
        if state.current and state.loop_mode != 1:
            state.history.append({'lazy': True, 'title': state.current.title, 'url': state.current.webpage_url})
            if len(state.history) > 10: # 히스토리 10개 유지
                state.history.pop(0)

        state.is_playing = False
        state.skip_request = False
        await self.play_next(ctx)

    @commands.hybrid_command(name="스킵", aliases=["skip", "s"])
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            state = self.get_state(ctx.guild.id)
            state.skip_request = True
            ctx.voice_client.stop()
            await ctx.send(embed=discord.Embed(title=":track_next: 노래를 건너뜁니다.", color=discord.Color.from_str("#ffcc00")))
        else:
            await ctx.send(embed=discord.Embed(title=":question: 재생 중인 노래가 없습니다.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="정지", aliases=["pause", "일시정지"])
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            state = self.get_state(ctx.guild.id)
            state.pause_time = time.time()
            await ctx.send(embed=discord.Embed(title=":pause_button: 일시 정지되었습니다.", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="재개", aliases=["resume"])
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            state = self.get_state(ctx.guild.id)
            if state.pause_time > 0:
                state.total_paused_time += (time.time() - state.pause_time)
                state.pause_time = 0
            await ctx.send(embed=discord.Embed(title=":arrow_forward: 다시 재생합니다.", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="대기열", aliases=["playingnext", "pn"])
    async def show_queue(self, ctx):
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            temp_queue = list(state.queue._queue)
            view = QueuePaginator(temp_queue)
            await ctx.send(embed=view.create_embed(), view=view)
        else:
            await ctx.send(embed=discord.Embed(title=":question: 대기열이 비어 있습니다.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="셔플", aliases=["shuffle", "섞기", "ㅅㅍ"])
    async def shuffle_queue(self, ctx):
        state = self.get_state(ctx.guild.id)
        if state.queue.empty():
            return await ctx.send(embed=discord.Embed(title=":question: 섞을 곡이 없습니다.", color=discord.Color.from_str("#ff6600")))
        temp_queue = list(state.queue._queue)
        random.shuffle(temp_queue)
        state.queue = asyncio.Queue()
        for item in temp_queue: await state.queue.put(item)
        await ctx.send(embed=discord.Embed(title=":twisted_rightwards_arrows: 대기열을 무작위로 섞었습니다!", color=discord.Color.from_str("#1a75ff")))

    @commands.hybrid_command(name="초기화", aliases=["clearqueue", "대기열비우기", "cq", "clear"])
    async def clear_queue(self, ctx):
        state = self.get_state(ctx.guild.id)
        if state.queue.empty():
            return await ctx.send(embed=discord.Embed(title=":question: 대기열이 이미 비어 있습니다.", color=discord.Color.from_str("#ff6600")))
        cleared_count = state.queue.qsize()
        state.queue = asyncio.Queue()
        state.history.clear() # 초기화 시 이전 곡 기록도 날림
        await ctx.send(embed=discord.Embed(title=f":wastebasket: {cleared_count}곡을 삭제하고 히스토리를 초기화했습니다.", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="음량", aliases=["volume", "볼륨", "vol"])
    @app_commands.describe(volume="(옵션) 0 - 100%")
    async def volume(self, ctx, volume: int = None):
        state = self.get_state(ctx.guild.id)
        if ctx.voice_client is None or ctx.voice_client.source is None:
            return await ctx.send(embed=discord.Embed(title=":warning: 설정할 대상이 없습니다.", color=discord.Color.from_str("#ff6600")))
        
        if volume is not None:
            state.volume = max(0, min(100, volume)) / 100
            ctx.voice_client.source.volume = state.volume
            await ctx.send(embed=discord.Embed(title=f":sound: 음량을 {volume}%로 변경했습니다.", color=discord.Color.from_str("#ffcc00")))
        else:
            await ctx.send(embed=discord.Embed(title=f":sound: 현재 음량: {int(state.volume * 100)}%", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="퇴장", aliases=["quit"])
    async def stop(self, ctx):
        if ctx.voice_client:
            state = self.get_state(ctx.guild.id)
            state.clear()
            await ctx.voice_client.disconnect()
            await ctx.send(embed=discord.Embed(title=":door: 퇴장했습니다.", color=discord.Color.from_str("#ffcc00")))

    # --- [이하 플리 관리 관련 코드는 동일] ---
    @commands.hybrid_command(name="추가", aliases=["add", "pladd", "ㅁㅇㅇ"])
    async def save_to_playlist(self, ctx, playlist: str, *, query: str):
        async with ctx.typing():
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            if not player: return await ctx.send(embed=discord.Embed(title=":x: 가져올 수 없음", color=discord.Color.red()))
            if self.playlist_manager.add_song(playlist, player.title, player.webpage_url):
                await ctx.send(embed=discord.Embed(title=f":inbox_tray: '{playlist}'에 추가됨", description=f"[{player.title}]({player.webpage_url})", color=discord.Color.green()))
            else:
                await ctx.send(embed=discord.Embed(title=":warning: 이미 존재하는 곡", color=discord.Color.gold()))

    @commands.hybrid_command(name="플리복사", aliases=["plcopy", "복사"])
    async def copy_youtube_playlist(self, ctx, url: str, *, playlist: str):
        if "list=" in url:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                if 'list' in qs: url = f"https://www.youtube.com/playlist?list={qs['list'][0]}"
            except Exception: pass

        await ctx.send(embed=discord.Embed(title=f":hourglass_flowing_sand: '{playlist}' 불러오는 중...", color=discord.Color.blue()))
        async with ctx.typing():
            pl_options = ytdl_format_options.copy()
            pl_options['noplaylist'] = False
            pl_options['extract_flat'] = True  
            pl_ytdl = yt_dlp.YoutubeDL(pl_options)

            try: info = await self.bot.loop.run_in_executor(None, lambda: pl_ytdl.extract_info(url, download=False))
            except Exception as e: return await ctx.send(embed=discord.Embed(title=":x: 오류", description=str(e), color=discord.Color.red()))
            
            if not info: return await ctx.send(embed=discord.Embed(title=":x: 없음", color=discord.Color.red()))
            
            entries = list(info['entries']) if 'entries' in info else ([] if info.get('_type') == 'playlist' else [info])
            added_count = 0; skipped_count = 0
            
            for entry in entries:
                if not entry: skipped_count += 1; continue
                try:
                    title = entry.get('title')
                    webpage_url = entry.get('url') or entry.get('webpage_url')
                    if not webpage_url and entry.get('id'): webpage_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                    
                    if title and webpage_url and title not in ["[Private video]", "[Deleted video]"]:
                        if self.playlist_manager.add_song(playlist, title, webpage_url): added_count += 1
                        else: skipped_count += 1
                    else: skipped_count += 1
                except Exception: skipped_count += 1
        await ctx.send(embed=discord.Embed(title=":inbox_tray: 복사 완료!", description=f"성공: {added_count}곡\n건너뜀: {skipped_count}곡", color=discord.Color.green()))

    @commands.hybrid_command(name="노래목록", aliases=["sl", "songlist"])
    async def show_playlist(self, ctx, playlist: str):
        tracks = self.playlist_manager.get_tracks(playlist)
        if not tracks: return await ctx.send(embed=discord.Embed(title=":x: 없음", color=discord.Color.red()))
        view = PlaylistPaginator(tracks, playlist)
        await ctx.send(embed=view.create_embed(), view=view)

    @commands.hybrid_command(name="노래삭제", aliases=["삭제", "pdel"])
    async def delete_from_playlist(self, ctx, playlist: str, index: int):
        deleted = self.playlist_manager.delete_song(playlist, index - 1)
        if deleted: await ctx.send(embed=discord.Embed(title=f":wastebasket: 삭제 완료: {deleted['title']}", color=discord.Color.gold()))
        else: await ctx.send(embed=discord.Embed(title=":warning: 잘못된 입력", color=discord.Color.red()))

    @commands.hybrid_command(name="플리재생", aliases=["playlistplay", "pp", "ㅔㅔ"])
    @app_commands.choices(mode=[app_commands.Choice(name="순서대로", value="순서대로"), app_commands.Choice(name="셔플", value="셔플")])
    async def play_playlist(self, ctx, playlist: str, mode: str = "순서대로"):
        tracks = self.playlist_manager.get_tracks(playlist, shuffle=(mode == "셔플"))
        if not tracks: return await ctx.send(embed=discord.Embed(title=":x: 비어있음", color=discord.Color.red()))
        state = self.get_state(ctx.guild.id)
        for track in tracks: await state.queue.put({'lazy': True, 'title': track['title'], 'url': track['url']})
        await ctx.send(embed=discord.Embed(title=f":white_check_mark: {len(tracks)}곡 추가 ({mode})", color=discord.Color.green()))
        if not state.is_playing and not ctx.voice_client.is_paused(): await self.play_next(ctx)

    @commands.hybrid_command(name="플리목록", aliases=["pllist"])
    async def list_playlists(self, ctx):
        playlists = self.playlist_manager.get_all_playlists()
        if not playlists: return await ctx.send(embed=discord.Embed(title=":x: 없음", color=discord.Color.red()))
        msg = "".join([f"**{i}.** 📁 {n} ({c}곡)\n" for i, (n, c) in enumerate(playlists.items(), 1)])
        await ctx.send(embed=discord.Embed(title=f":file_folder: 전체 (총 {len(playlists)}개)", description=msg, color=discord.Color.blue()))

    @commands.hybrid_command(name="플리삭제", aliases=["pldelete"])
    async def delete_entire_playlist(self, ctx, playlist: str):
        if playlist not in self.playlist_manager.playlists: return await ctx.send(embed=discord.Embed(title=":x: 없음", color=discord.Color.red()))
        await ctx.send(embed=discord.Embed(title=":warning: 영구 삭제", description=f"`{playlist}` 입력 시 삭제", color=discord.Color.red()))
        try:
            msg = await self.bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
            if msg.content == playlist:
                self.playlist_manager.delete_playlist(playlist)
                await ctx.send(embed=discord.Embed(title=":wastebasket: 삭제 완료", color=discord.Color.gold()))
            else: await ctx.send(embed=discord.Embed(title=":x: 취소됨", color=discord.Color.green()))
        except asyncio.TimeoutError: await ctx.send(embed=discord.Embed(title=":timer: 취소됨", color=discord.Color.green()))

    @play.before_invoke
    @play_playlist.before_invoke
    async def ensure_voice(self, ctx):
        if not (ctx.author.voice and ctx.author.voice.channel):
            await ctx.send(embed=discord.Embed(title=":warning: 음성채널 연결 필요", color=discord.Color.red()))
            raise commands.CommandError("No Voice")
        elif not ctx.voice_client: await ctx.author.voice.channel.connect()

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))