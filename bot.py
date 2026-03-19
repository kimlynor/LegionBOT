import os
import sys
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database import init_db

load_dotenv()

_token = os.getenv('DISCORD_TOKEN', '').strip()
if not _token:
    print('[오류] .env 파일에 DISCORD_TOKEN이 설정되지 않았습니다.')
    sys.exit(1)

_guild_env = os.getenv('GUILD_ID', '').strip()
if not _guild_env:
    print('[오류] .env 파일에 GUILD_ID가 설정되지 않았습니다.')
    sys.exit(1)

GUILD_IDS = [int(gid.strip()) for gid in _guild_env.split(',') if gid.strip()]

intents = discord.Intents.default()
intents.members = True


class LegionBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await init_db()
        await self.load_extension('cogs.registration')
        await self.load_extension('cogs.party')
        # 지정된 서버들에 슬래시 커맨드 동기화 (즉시 반영)
        for gid in GUILD_IDS:
            guild = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        print(f'[봇] 슬래시 커맨드 동기화 완료 ({len(GUILD_IDS)}개 서버)')

    async def on_ready(self):
        print(f'[봇] {self.user} 온라인!')
        print(f'[봇] 서버 수: {len(self.guilds)}')
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name='레기온 유저 관리'
            )
        )



bot = LegionBot()
bot.run(_token)
