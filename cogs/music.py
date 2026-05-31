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
        if playlist not in self.playlists: self.playlists[playlist] = []
        if any(track['url'] == url for track in self.playlists[playlist]): return False
        self.playlists[playlist].append({"title": title, "url": url})
        self.save_data()
        return True

    def delete_song(self, playlist, index):
        if playlist in self.playlists and 0 <= index < len(self.playlists[playlist]):
            deleted = self.playlists[playlist].pop(index)
            if not self.playlists[playlist]: del self.playlists[playlist]
            self.save_data()
            return deleted
        return None

    def get_tracks(self, playlist_name, shuffle=False):
        tracks = []
        if playlist_name == "전체":
            for pl_tracks in self.playlists.values(): tracks.extend(pl_tracks)
            unique_tracks = {track['url']: track for track in tracks}
            tracks = list(unique_tracks.values())
        elif playlist_name in self.playlists:
            tracks = list(self.playlists[playlist_name])
        else: return []
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
        message = "".join([f"**{idx}.** {track['title']}\n" for idx, track in enumerate(page_tracks, start=start_idx + 1)])
        embed = discord.Embed(
            title=f":folder: '{self.playlist_name}' 노래 목록 ({len(self.tracks)}곡)",
            description=message, color=discord.Color.from_str("#1a75ff")
        )
        embed.set_footer(text=f"페이지 {self.current_page} / {self.total_pages}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = self.total_pages if self.current_page == 1 else self.current_page - 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 1 if self.current_page == self.total_pages else self.current_page + 1
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
        message = "".join([f"**{idx}.** {item['title'] if isinstance(item, dict) else item.title}\n" for idx, item in enumerate(page_tracks, start=start_idx + 1)])
        embed = discord.Embed(
            title=f":scroll: PLAYING NEXT (총 {len(self.queue_list)}곡)",
            description=message, color=discord.Color.from_str("#1a75ff")
        )
        embed.set_footer(text=f"페이지 {self.current_page} / {self.total_pages}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(1, self.total_pages) if self.current_page == 1 else self.current_page - 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 1 if self.current_page == self.total_pages else self.current_page + 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

class GuildMusicState:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.is_playing = False
        
        self.history = []
        self.loop_mode = 0
        self.volume = 0.3
        
        self.force_skip_count = 0
        self.force_prev_count = 0
        self.ignore_play_check = 0 
        
        self.start_time = 0
        self.pause_time = 0
        self.total_paused_time = 0
        self.seek_offset = 0
        
        self.np_message = None
        self.update_task = None
        self.autoplay = False
        self.autoplay_next = None

    def get_current_time(self):
        if not self.is_playing or self.start_time == 0: return self.seek_offset
        if self.pause_time > 0: return (self.pause_time - self.start_time - self.total_paused_time) + self.seek_offset
        return (time.time() - self.start_time - self.total_paused_time) + self.seek_offset

    def clear(self):
        self.queue = asyncio.Queue()
        self.history.clear()
        self.current = None
        self.is_playing = False
        self.autoplay = False
        self.autoplay_next = None
        self.force_skip_count = 0
        self.force_prev_count = 0
        self.ignore_play_check = 0
        if self.update_task: self.update_task.cancel()


class MusicController(discord.ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx
        self._sync_button_states()

    def _sync_button_states(self):
        state = self.cog.get_state(self.ctx.guild.id)
        for child in self.children:
            if getattr(child, "custom_id", None) == "mc_loop":
                if state.loop_mode == 0:
                    child.label = "반복: 끔"; child.style = discord.ButtonStyle.secondary
                elif state.loop_mode == 1:
                    child.label = "반복: 현재 곡"; child.style = discord.ButtonStyle.success
                elif state.loop_mode == 2:
                    child.label = "반복: 대기열"; child.style = discord.ButtonStyle.primary

            elif getattr(child, "custom_id", None) == "mc_autoplay":
                if getattr(state, "autoplay", False):
                    child.label = "자동재생: 켬"; child.style = discord.ButtonStyle.success
                else:
                    child.label = "자동재생: 끔"; child.style = discord.ButtonStyle.secondary

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="mc_prev", row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        state = self.cog.get_state(self.ctx.guild.id)
        if not state.history: return await interaction.followup.send("이전 곡 기록이 없습니다.", ephemeral=True)
        prev_song = state.history.pop()
        
        if state.current:
            temp_list = [{'lazy': True, 'title': state.current.title, 'url': state.current.webpage_url}] + list(state.queue._queue)
            state.queue = asyncio.Queue()
            for item in temp_list: await state.queue.put(item)
            
        temp_list = [prev_song] + list(state.queue._queue)
        state.queue = asyncio.Queue()
        for item in temp_list: await state.queue.put(item)
        
        state.force_prev_count += 1
        if self.ctx.voice_client and self.ctx.voice_client.is_playing(): self.ctx.voice_client.stop()
        else: await self.cog.play_next(self.ctx)

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
        state.force_skip_count += 1
        if self.ctx.voice_client and self.ctx.voice_client.is_playing(): self.ctx.voice_client.stop()
        else: await self.cog.play_next(self.ctx)

    @discord.ui.button(label="반복: 끔", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="mc_loop", row=1)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.ctx.guild.id)
        state.loop_mode = (state.loop_mode + 1) % 3
        if state.loop_mode == 0:
            button.label = "반복: 끔"; button.style = discord.ButtonStyle.secondary
        elif state.loop_mode == 1:
            button.label = "반복: 현재 곡"; button.style = discord.ButtonStyle.success
        elif state.loop_mode == 2:
            button.label = "반복: 대기열"; button.style = discord.ButtonStyle.primary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="mc_voldown", row=1)
    async def voldown_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.ctx.guild.id)
        if self.ctx.voice_client and self.ctx.voice_client.source:
            state.volume = max(0.0, state.volume - 0.1)
            self.ctx.voice_client.source.volume = state.volume
            embed = interaction.message.embeds[0]
            for i, field in enumerate(embed.fields):
                if "볼륨" in field.name:
                    embed.set_field_at(i, name=field.name, value=f"**{int(state.volume * 100)}%**", inline=True)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="mc_volup", row=1)
    async def volup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.ctx.guild.id)
        if self.ctx.voice_client and self.ctx.voice_client.source:
            state.volume = min(1.0, state.volume + 0.1)
            self.ctx.voice_client.source.volume = state.volume
            embed = interaction.message.embeds[0]
            for i, field in enumerate(embed.fields):
                if "볼륨" in field.name:
                    embed.set_field_at(i, name=field.name, value=f"**{int(state.volume * 100)}%**", inline=True)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="자동재생: 끔", emoji="♾️", style=discord.ButtonStyle.secondary, custom_id="mc_autoplay", row=1)
    async def autoplay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.get_state(self.ctx.guild.id)
        state.autoplay = not getattr(state, 'autoplay', False)
        
        if state.autoplay:
            button.label = "자동재생: 켬"
            button.style = discord.ButtonStyle.success

            if state.queue.empty() and state.is_playing:
                self.cog.bot.loop.create_task(self.cog._process_autoplay(self.ctx))
        else:
            button.label = "자동재생: 끔"
            button.style = discord.ButtonStyle.secondary
            
        await interaction.response.edit_message(view=self)


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
            if len(data['entries']) > 0 and data['entries'][0] is not None: data = data['entries'][0]
            else: return None
        if data is None: return None
        url = data.get('url')
        if not url: return None
        url = url if stream else ytdl.prepare_filename(data)
        b_opts = ffmpeg_options['before_options']
        if seek > 0: b_opts = f"-ss {seek} " + b_opts
        return cls(discord.FFmpegPCMAudio(url, before_options=b_opts, options=ffmpeg_options['options']), data=data, volume=volume)

    @classmethod
    def create_direct(cls, data, seek=0, volume=0.3):
        b_opts = ffmpeg_options['before_options']
        if seek > 0: b_opts = f"-ss {seek} " + b_opts
        return cls(discord.FFmpegPCMAudio(data['url'], before_options=b_opts, options=ffmpeg_options['options']), data=data, volume=volume)


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_states: dict[int, GuildMusicState] = {}
        self.playlist_manager = PlaylistManager()

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.guild_states: self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id]

    async def progress_update_task(self, ctx):
        state = self.get_state(ctx.guild.id)
        while state.is_playing and state.current and state.np_message:
            await asyncio.sleep(2)
            try:
                if ctx.voice_client and not ctx.voice_client.is_paused():
                    current_time = state.get_current_time()
                    total_time = state.current.data.get('duration') or 0
                    embed = state.np_message.embeds[0]
                    embed.description = create_progress_bar(current_time, total_time)
                    await state.np_message.edit(embed=embed)
            except Exception: break

    async def seek_music(self, ctx, offset):
        state = self.get_state(ctx.guild.id)
        if not state.current or not ctx.voice_client or not ctx.voice_client.is_playing(): return
        current_time = state.get_current_time()
        new_time = max(0, current_time + offset)
        
        try: new_source = YTDLSource.create_direct(state.current.data, seek=new_time, volume=state.volume)
        except Exception: new_source = await YTDLSource.from_url(state.current.webpage_url, loop=self.bot.loop, stream=True, seek=new_time, volume=state.volume)
            
        state.ignore_play_check += 1 
        ctx.voice_client.stop()
        
        state.current = new_source
        state.start_time = time.time()
        state.pause_time = 0
        state.total_paused_time = 0
        state.seek_offset = new_time
        
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
        """입력한 음성채널 또는 사용자가 있는 채널 입장 (= /입장) [= !join]"""
        if channel is None and ctx.author.voice: channel = ctx.author.voice.channel
        if ctx.voice_client is not None: return await ctx.voice_client.move_to(channel)
        if channel: await channel.connect()
        else: await ctx.send(embed=discord.Embed(title=":warning: 음성 채널에 먼저 들어가주세요.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="재생", aliases=["play", "p", "ㅔ", "P", "ㅖ"])
    async def play(self, ctx, *, query):
        """대기열에 음악 추가 (= /재생 [검색어]) [= !play, !p]"""
        state = self.get_state(ctx.guild.id)
        async with ctx.typing():
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True, volume=state.volume)
            if player is None: return await ctx.send(embed=discord.Embed(title=":question: 노래를 가져오지 못했습니다.", color=discord.Color.from_str("#ff6600")))
            await state.queue.put(player)
            position = state.queue.qsize()
            embed = discord.Embed(title=':mag_right: 대기열 추가 완료 :cd:', description=f'[{player.title}]({player.webpage_url})\n> `#{position}번째 대기중`', color=discord.Color.from_str("#1a75ff"))
            await ctx.send(embed=embed)
            if not state.is_playing and not ctx.voice_client.is_paused(): await self.play_next(ctx)

    @commands.hybrid_command(name="우선재생", aliases=["playfirst", "pf", "ㅔㄹ"])
    async def play_top(self, ctx, *, query):
        """대기열 맨 앞에 음악을 추가합니다. (= /우선재생 [검색어]) [= !playfirst, !pf, !ㅔㄹ]"""
        state = self.get_state(ctx.guild.id)
        async with ctx.typing():
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True, volume=state.volume)
            if player is None: return await ctx.send(embed=discord.Embed(title=":question: 노래를 가져오지 못했습니다.", color=discord.Color.from_str("#ff6600")))
            
            temp_list = [player] + list(state.queue._queue)
            state.queue = asyncio.Queue()
            for item in temp_list: 
                await state.queue.put(item)
            
            embed = discord.Embed(
                title=':arrow_up: 우선 재생 추가 완료 :cd:', 
                description=f'[{player.title}]({player.webpage_url})\n> `다음 곡으로 바로 재생됩니다.`', 
                color=discord.Color.from_str("#ff00ff")
            )
            await ctx.send(embed=embed)
            
            if not state.is_playing and not ctx.voice_client.is_paused(): 
                await self.play_next(ctx)

    async def play_next(self, ctx):
        state = self.get_state(ctx.guild.id)
        if state.update_task: state.update_task.cancel()
        
        item = None
        
        if not state.queue.empty():
            item = await state.queue.get()
            state.autoplay_next = None 
            
        elif getattr(state, 'autoplay', False) and getattr(state, 'autoplay_next', None):
            item = state.autoplay_next
            state.autoplay_next = None

        if item:
            if isinstance(item, dict) and item.get('lazy'):
                try: state.current = await YTDLSource.from_url(item['url'], loop=self.bot.loop, stream=True, volume=state.volume)
                except Exception as e:
                    await ctx.send(embed=discord.Embed(title=f":warning: 재생 불가: {item['title']}", color=discord.Color.red()))
                    return self.bot.loop.create_task(self.play_check(ctx, e))
            else: state.current = item
            
            if state.current is None: return self.bot.loop.create_task(self.play_check(ctx, Exception("곡 정보를 불러올 수 없습니다.")))

            state.is_playing = True
            state.start_time = time.time()
            state.pause_time = 0
            state.total_paused_time = 0
            state.seek_offset = 0
            
            ctx.voice_client.play(state.current, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_check(ctx, e), self.bot.loop))

            view = MusicController(self, ctx)
            total_sec = state.current.data.get("duration") or 0
            embed = discord.Embed(title=f':musical_note: NOW PLAYING', description=create_progress_bar(0, total_sec), color=discord.Color.from_str("#00ff00"))
            embed.set_author(name=state.current.title, url=state.current.webpage_url)
            
            queue_text = f"**{state.queue.qsize()}곡** 대기중"
            if state.queue.empty() and getattr(state, 'autoplay', False):
                queue_text = "♾️ 자동재생 대기중"
            embed.add_field(name=":scroll: 대기열", value=queue_text, inline=True)
            embed.add_field(name=":sound: 볼륨", value=f"**{int(state.volume * 100)}%**", inline=True)
            
            thumbnail = state.current.data.get("thumbnail")
            if not thumbnail:
                thumbnails = state.current.data.get("thumbnails") or []
                thumbnail = thumbnails[-1]["url"] if thumbnails else None
            if thumbnail: embed.set_thumbnail(url=thumbnail)
            
            state.np_message = await ctx.send(embed=embed, view=view)
            state.update_task = self.bot.loop.create_task(self.progress_update_task(ctx))

            if state.queue.empty() and getattr(state, 'autoplay', False):
                self.bot.loop.create_task(self._process_autoplay(ctx))
        else:
            state.current = None
            state.is_playing = False

    async def play_check(self, ctx, error):
        state = self.get_state(ctx.guild.id)
        if error: print(f'에러: {error}')
        if state.ignore_play_check > 0:
            state.ignore_play_check -= 1
            return
            
        is_prev = False
        if state.force_prev_count > 0:
            state.force_prev_count -= 1; is_prev = True
            
        is_skip = False
        if state.force_skip_count > 0:
            state.force_skip_count -= 1; is_skip = True

        if state.current and state.loop_mode != 1 and not is_prev:
            state.history.append({'lazy': True, 'title': state.current.title, 'url': state.current.webpage_url})
            if len(state.history) > 10: state.history.pop(0)

        if not is_skip and not is_prev and state.current:
            lazy_item = {'lazy': True, 'title': state.current.title, 'url': state.current.webpage_url}
            if state.loop_mode == 1:
                temp_list = [lazy_item] + list(state.queue._queue)
                state.queue = asyncio.Queue()
                for i in temp_list: await state.queue.put(i)
            elif state.loop_mode == 2:
                await state.queue.put(lazy_item)

        if state.queue.empty() and getattr(state, 'autoplay', False) and not is_prev and state.current:
            await self._process_autoplay(ctx)

    async def _process_autoplay(self, ctx):
        state = self.get_state(ctx.guild.id)
        if not state.current: return
        
        video_id = state.current.data.get('id')
        if not video_id: return
        
        mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        
        pl_options = ytdl_format_options.copy()
        pl_options.update({'extract_flat': True, 'noplaylist': False})
        
        try:
            info = await self.bot.loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(pl_options).extract_info(mix_url, download=False))
            if not info or 'entries' not in info: return
                
            entries = list(info['entries'])
            
            history_urls = {h.get('url') for h in state.history if h.get('url')}
            history_urls.add(state.current.webpage_url)
            
            for entry in entries:
                if not entry: continue
                url = entry.get('url') or entry.get('webpage_url')
                if not url and entry.get('id'): url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                
                if url and url not in history_urls and entry.get('title') not in ["[Private video]", "[Deleted video]"]:
                    state.autoplay_next = {'lazy': True, 'title': entry.get('title'), 'url': url}
                    break
        except Exception as e:
            print(f"자동재생 로드 오류: {e}")

    @commands.hybrid_command(name="스킵", aliases=["skip", "s"])
    async def skip(self, ctx):
        """현재 재생중인 노래 스킵 (= /스킵) [= !skip, !s]"""
        state = self.get_state(ctx.guild.id)
        if ctx.voice_client and ctx.voice_client.is_playing():
            state.force_skip_count += 1
            ctx.voice_client.stop()
            await ctx.send(embed=discord.Embed(title=":track_next: 노래를 건너뜁니다.", color=discord.Color.from_str("#ffcc00")))
        else:
            await ctx.send(embed=discord.Embed(title=":question: 재생 중인 노래가 없습니다.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="정지", aliases=["pause", "일시정지"])
    async def pause(self, ctx):
        """재생중인 음악 일시정지 (= /정지) [= !pause, !일시정지]"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            self.get_state(ctx.guild.id).pause_time = time.time()
            await ctx.send(embed=discord.Embed(title=":pause_button: 일시 정지되었습니다.", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="재개", aliases=["resume"])
    async def resume(self, ctx):
        """일시정지된 음악 다시 재생 (= /재개) [= !resume]"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            state = self.get_state(ctx.guild.id)
            if state.pause_time > 0:
                state.total_paused_time += (time.time() - state.pause_time)
                state.pause_time = 0
            await ctx.send(embed=discord.Embed(title=":arrow_forward: 다시 재생합니다.", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="대기열", aliases=["playingnext", "pn"])
    async def show_queue(self, ctx):
        """대기열 목록 출력 (= /대기열) [= !playingnext, !pn]"""
        state = self.get_state(ctx.guild.id)
        if not state.queue.empty():
            view = QueuePaginator(list(state.queue._queue))
            await ctx.send(embed=view.create_embed(), view=view)
        else:
            await ctx.send(embed=discord.Embed(title=":question: 대기열이 비어 있습니다.", color=discord.Color.from_str("#ff6600")))

    @commands.hybrid_command(name="셔플", aliases=["shuffle", "섞기", "ㅅㅍ"])
    async def shuffle_queue(self, ctx):
        """현재 대기열에 있는 곡들의 순서를 무작위로 섞습니다. (= /셔플) [= !shuffle, !ㅅㅍ]"""
        state = self.get_state(ctx.guild.id)
        if state.queue.empty(): return await ctx.send(embed=discord.Embed(title=":question: 섞을 곡이 없습니다.", color=discord.Color.from_str("#ff6600")))
        temp_queue = list(state.queue._queue)
        random.shuffle(temp_queue)
        state.queue = asyncio.Queue()
        for item in temp_queue: await state.queue.put(item)
        await ctx.send(embed=discord.Embed(title=":twisted_rightwards_arrows: 대기열을 섞었습니다!", color=discord.Color.from_str("#1a75ff")))

    @commands.hybrid_command(name="초기화", aliases=["clearqueue", "대기열비우기", "cq", "clear"])
    async def clear_queue(self, ctx):
        """대기열에 있는 모든 곡을 한 번에 삭제합니다. (= /초기화) [= !cq, !clearqueue, !clear]"""
        state = self.get_state(ctx.guild.id)
        cleared_count = state.queue.qsize()
        history_count = len(state.history)
        if cleared_count == 0 and history_count == 0:
            return await ctx.send(embed=discord.Embed(title=":question: 대기열과 이전 곡 기록이 이미 비어 있습니다.", color=discord.Color.from_str("#ff6600")))
        state.queue = asyncio.Queue()
        state.history.clear()
        await ctx.send(embed=discord.Embed(title=f":wastebasket: 대기열 {cleared_count}곡 삭제 및 이전 곡 기록 초기화 완료!", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="음량", aliases=["volume", "볼륨", "vol"])
    async def volume(self, ctx, volume: int = None):
        """음량 조절 또는 현재 음량 확인(= /음량 [(선택사항)1 ~ 100 (기본값 30)]) [= !volume, !볼륨]"""
        state = self.get_state(ctx.guild.id)
        if ctx.voice_client is None or ctx.voice_client.source is None: return await ctx.send(embed=discord.Embed(title=":warning: 설정 대상 없음", color=discord.Color.from_str("#ff6600")))
        if volume is not None:
            state.volume = max(0, min(100, volume)) / 100
            ctx.voice_client.source.volume = state.volume
            if state.np_message:
                try:
                    embed = state.np_message.embeds[0]
                    for i, field in enumerate(embed.fields):
                        if "볼륨" in field.name:
                            embed.set_field_at(i, name=field.name, value=f"**{int(state.volume * 100)}%**", inline=True)
                    await state.np_message.edit(embed=embed)
                except Exception: pass
            await ctx.send(embed=discord.Embed(title=f":sound: 음량을 {volume}%로 변경했습니다.", color=discord.Color.from_str("#ffcc00")))
        else: await ctx.send(embed=discord.Embed(title=f":sound: 현재 음량: {int(state.volume * 100)}%", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="퇴장", aliases=["quit"])
    async def stop(self, ctx):
        """재생을 중단하고 음성채널 퇴장 (= /퇴장) [= !quit]"""
        if ctx.voice_client:
            self.get_state(ctx.guild.id).clear()
            await ctx.voice_client.disconnect()
            await ctx.send(embed=discord.Embed(title=":door: 퇴장했습니다.", color=discord.Color.from_str("#ffcc00")))

    @commands.hybrid_command(name="자동재생", aliases=["autoplay", "ap", "ㅈㄷㅈㅅ"])
    async def toggle_autoplay(self, ctx):
        """대기열이 끝났을 때 유튜브 믹스를 기반으로 자동 재생합니다. (= /자동재생) [= !ap]"""
        state = self.get_state(ctx.guild.id)
        state.autoplay = not getattr(state, 'autoplay', False)
        
        status = "켜짐 🟢" if state.autoplay else "꺼짐 🔴"
        color = discord.Color.green() if state.autoplay else discord.Color.red()
        
        embed = discord.Embed(
            title=f":infinity: 자동 재생이 {status}", 
            description="대기열의 마지막 곡이 끝나면 유사한 곡을 찾아 재생합니다." if state.autoplay else "더 이상 곡을 자동으로 추가하지 않습니다.",
            color=color
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="추가", aliases=["add", "pladd", "ㅁㅇㅇ"])
    async def save_to_playlist(self, ctx, playlist: str, *, query: str):
        """원하는 플레이리스트에 노래를 영구 저장합니다. (= /추가 [플리 이름] [검색어])"""
        async with ctx.typing():
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            if not player: return await ctx.send(embed=discord.Embed(title=":x: 가져올 수 없음", color=discord.Color.red()))
            if self.playlist_manager.add_song(playlist, player.title, player.webpage_url):
                pos = len(self.playlist_manager.playlists[playlist])
                await ctx.send(embed=discord.Embed(title=f":inbox_tray: '{playlist}'에 추가됨", description=f"[{player.title}]({player.webpage_url})\n> `#{pos}번째 곡으로 저장 완료`", color=discord.Color.green()))
            else: await ctx.send(embed=discord.Embed(title=":warning: 이미 존재하는 곡", color=discord.Color.gold()))

    @commands.hybrid_command(name="플리복사", aliases=["plcopy", "복사"])
    async def copy_youtube_playlist(self, ctx, url: str, *, playlist: str):
        """유튜브 플레이리스트의 모든 곡을 한 번에 복사해옵니다."""
        if "list=" in url:
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(url).query)
                if 'list' in qs: url = f"https://www.youtube.com/playlist?list={qs['list'][0]}"
            except Exception: pass
        await ctx.send(embed=discord.Embed(title=f":hourglass_flowing_sand: '{playlist}' 불러오는 중...", color=discord.Color.blue()))
        async with ctx.typing():
            pl_options = ytdl_format_options.copy(); pl_options['noplaylist'] = False; pl_options['extract_flat'] = True  
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
        """플레이리스트의 곡 목록을 보여줍니다. (= /노래목록 [플리 이름])"""
        tracks = self.playlist_manager.get_tracks(playlist)
        if not tracks: return await ctx.send(embed=discord.Embed(title=":x: 없음", color=discord.Color.red()))
        view = PlaylistPaginator(tracks, playlist)
        await ctx.send(embed=view.create_embed(), view=view)

    @commands.hybrid_command(name="노래삭제", aliases=["삭제", "pdel"])
    async def delete_from_playlist(self, ctx, playlist: str, index: int):
        """플레이리스트에서 특정 곡을 삭제합니다. (= /노래삭제 [플리 이름] [번호])"""
        deleted = self.playlist_manager.delete_song(playlist, index - 1)
        if deleted: await ctx.send(embed=discord.Embed(title=f":wastebasket: 삭제 완료: {deleted['title']}", color=discord.Color.gold()))
        else: await ctx.send(embed=discord.Embed(title=":warning: 잘못된 입력", color=discord.Color.red()))

    @commands.hybrid_command(name="플리재생", aliases=["playlistplay", "pp", "ㅔㅔ"])
    @app_commands.choices(mode=[app_commands.Choice(name="순서대로", value="순서대로"), app_commands.Choice(name="셔플", value="셔플")])
    async def play_playlist(self, ctx, playlist: str, mode: str = "순서대로"):
        """플레이리스트의 노래들을 대기열에 일괄 추가하고 재생합니다. (= /플리재생 [플리 이름] [모드])"""
        tracks = self.playlist_manager.get_tracks(playlist, shuffle=(mode == "셔플"))
        if not tracks: return await ctx.send(embed=discord.Embed(title=":x: 비어있음", color=discord.Color.red()))
        state = self.get_state(ctx.guild.id)
        for track in tracks: await state.queue.put({'lazy': True, 'title': track['title'], 'url': track['url']})
        await ctx.send(embed=discord.Embed(title=f":white_check_mark: {len(tracks)}곡 추가 ({mode})", color=discord.Color.green()))
        if not state.is_playing and not ctx.voice_client.is_paused(): await self.play_next(ctx)

    @commands.hybrid_command(name="플리목록", aliases=["pllist"])
    async def list_playlists(self, ctx):
        """현재 만들어진 모든 플레이리스트 목록과 곡 수를 보여줍니다. (= /플리목록)"""
        playlists = self.playlist_manager.get_all_playlists()
        if not playlists: return await ctx.send(embed=discord.Embed(title=":x: 없음", color=discord.Color.red()))
        msg = "".join([f"**{i}.** 📁 {n} ({c}곡)\n" for i, (n, c) in enumerate(playlists.items(), 1)])
        await ctx.send(embed=discord.Embed(title=f":file_folder: 전체 (총 {len(playlists)}개)", description=msg, color=discord.Color.blue()))

    @commands.hybrid_command(name="플리삭제", aliases=["pldelete"])
    async def delete_entire_playlist(self, ctx, playlist: str):
        """플레이리스트 폴더 자체를 통째로 삭제합니다. (= /플리삭제 [플리 이름])"""
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
    @play_top.before_invoke
    async def ensure_voice(self, ctx):
        if not (ctx.author.voice and ctx.author.voice.channel):
            await ctx.send(embed=discord.Embed(title=":warning: 음성채널 연결 필요", color=discord.Color.red()))
            raise commands.CommandError("No Voice")
        elif not ctx.voice_client: await ctx.author.voice.channel.connect()

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))