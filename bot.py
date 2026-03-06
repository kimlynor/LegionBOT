import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database import init_db

load_dotenv()

GUILD_IDS = [int(gid.strip()) for gid in os.getenv('GUILD_ID', '').split(',') if gid.strip()]

intents = discord.Intents.default()
intents.members = True
intents.message_content = True


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

    async def on_interaction(self, interaction: discord.Interaction):
        # 지정된 서버 외에서는 모든 인터랙션 차단
        if interaction.guild_id not in GUILD_IDS:
            await interaction.response.send_message('이 봇은 지정된 서버에서만 사용할 수 있습니다.', ephemeral=True)
            return
        await super().on_interaction(interaction)


bot = LegionBot()
bot.run(os.getenv('DISCORD_TOKEN'))
