import os
import re
import time
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import time as dtime
import database as db
from utils.scraper import scrape_character

GUILD_IDS = [int(gid.strip()) for gid in os.getenv('GUILD_ID', '').split(',') if gid.strip()]

# 쿨다운: discord_id → 마지막 등록 시각 (초)
_register_cooldown: dict[str, float] = {}
_subchar_cooldown: dict[str, float] = {}
COOLDOWN_SECONDS = 60

# /갱신 중복 실행 방지
_refresh_running = False

_CHAR_NAME_RE = re.compile(r'^[가-힣a-zA-Z0-9\s]{1,30}$')


def _validate_char_name(name: str) -> bool:
    return bool(_CHAR_NAME_RE.match(name))


def _check_cooldown(store: dict, discord_id: str) -> int:
    """남은 쿨다운 초 반환. 0이면 사용 가능."""
    last = store.get(discord_id, 0)
    remaining = int(COOLDOWN_SECONDS - (time.time() - last))
    return max(remaining, 0)


# ── 메인 캐릭터 등록 ──────────────────────────────────────────────────────────

class CharNameModal(discord.ui.Modal, title='캐릭터 등록 / 수정'):
    char_name = discord.ui.TextInput(
        label='캐릭터명',
        placeholder='아이온2 캐릭터 이름을 정확히 입력하세요',
        min_length=1,
        max_length=30,
    )

    def __init__(self, current_char: str | None = None):
        super().__init__()
        if current_char:
            self.char_name.default = current_char

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.char_name.value.strip()

        if not _validate_char_name(name):
            await interaction.followup.send(
                '❌ 캐릭터명에 허용되지 않는 문자가 포함되어 있습니다.\n한글, 영문, 숫자만 입력해주세요.',
                ephemeral=True,
            )
            return

        is_update = (await db.get_user(str(interaction.user.id))) is not None

        await interaction.followup.send(
            f'🔍 **{name}** 캐릭터를 검색 중입니다... (10~20초 소요)',
            ephemeral=True,
        )

        data = await scrape_character(name)

        if not data:
            await interaction.followup.send(
                f'❌ **{name}** 캐릭터를 찾을 수 없습니다.\n'
                '캐릭터명을 다시 확인해주세요.',
                ephemeral=True,
            )
            return

        await db.upsert_user(
            discord_id=str(interaction.user.id),
            discord_name=str(interaction.user),
            char_name=data['char_name'],
            job=data['job'],
            combat_power=data['combat_power'],
            atool_score=data['atool_score'],
        )

        nickname = _build_nickname(data['char_name'], data['job'], data['combat_power'])

        nick_changed = False
        try:
            await interaction.user.edit(nick=nickname)
            nick_changed = True
        except discord.Forbidden:
            pass

        title = '✅ 정보 수정 완료' if is_update else '✅ 유저 등록 완료'
        embed = discord.Embed(title=title, color=discord.Color.green())
        embed.add_field(name='캐릭터명', value=data['char_name'], inline=True)
        embed.add_field(name='직업', value=data['job'], inline=True)
        embed.add_field(name='전투력', value=f"{data['combat_power']:,}", inline=True)
        embed.add_field(name='아툴점수', value=f"{data['atool_score']:,}", inline=True)
        if nick_changed:
            embed.add_field(name='닉네임', value=f'`{nickname}`', inline=False)
        else:
            embed.set_footer(text='⚠️ 닉네임 변경 권한이 없어 닉네임은 변경되지 않았습니다.')

        await interaction.followup.send(embed=embed, ephemeral=True)


class RegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='유저 등록 / 수정',
        style=discord.ButtonStyle.primary,
        custom_id='legion_register_button',
        emoji='📝',
    )
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        remaining = _check_cooldown(_register_cooldown, str(interaction.user.id))
        if remaining > 0:
            await interaction.response.send_message(
                f'⏳ {remaining}초 후에 다시 시도해주세요.', ephemeral=True
            )
            return
        _register_cooldown[str(interaction.user.id)] = time.time()
        existing = await db.get_user(str(interaction.user.id))
        current_char = existing['char_name'] if existing else None
        await interaction.response.send_modal(CharNameModal(current_char=current_char))


# ── 부캐릭터 등록 ─────────────────────────────────────────────────────────────

class SubCharModal(discord.ui.Modal, title='부캐 등록'):
    char_name = discord.ui.TextInput(
        label='부캐릭터명',
        placeholder='아이온2 부캐릭터 이름을 정확히 입력하세요',
        min_length=1,
        max_length=30,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.char_name.value.strip()

        if not _validate_char_name(name):
            await interaction.followup.send(
                '❌ 캐릭터명에 허용되지 않는 문자가 포함되어 있습니다.\n한글, 영문, 숫자만 입력해주세요.',
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f'🔍 **{name}** 캐릭터를 검색 중입니다... (10~20초 소요)',
            ephemeral=True,
        )

        data = await scrape_character(name)
        if not data:
            await interaction.followup.send(
                f'❌ **{name}** 캐릭터를 찾을 수 없습니다.\n'
                '캐릭터명을 다시 확인해주세요.',
                ephemeral=True,
            )
            return

        existing_subs = await db.get_sub_characters(str(interaction.user.id))
        existing_names = [sc['char_name'] for sc in existing_subs]
        if data['char_name'] not in existing_names and len(existing_subs) >= 5:
            await interaction.followup.send(
                '❌ 부캐릭터는 최대 5개까지 등록 가능합니다.\n'
                '기존 부캐를 삭제 후 다시 시도해주세요.',
                ephemeral=True,
            )
            return

        await db.add_sub_character(
            discord_id=str(interaction.user.id),
            char_name=data['char_name'],
            job=data['job'],
            combat_power=data['combat_power'],
            atool_score=data['atool_score'],
        )

        action = '수정' if data['char_name'] in existing_names else '등록'
        embed = discord.Embed(title=f'✅ 부캐 {action} 완료', color=discord.Color.purple())
        embed.add_field(name='캐릭터명', value=data['char_name'], inline=True)
        embed.add_field(name='직업', value=data['job'], inline=True)
        embed.add_field(name='전투력', value=f"{data['combat_power']:,}", inline=True)
        embed.add_field(name='아툴점수', value=f"{data['atool_score']:,}", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


class SubCharManageView(discord.ui.View):
    def __init__(self, subs: list):
        super().__init__(timeout=120)

        add_btn = discord.ui.Button(
            label='부캐 추가',
            style=discord.ButtonStyle.success,
            emoji='➕',
            row=0,
        )
        add_btn.callback = self._add_callback
        self.add_item(add_btn)

        if subs:
            options = [
                discord.SelectOption(
                    label=f'{sc["char_name"]} ({sc["job"]})',
                    value=sc['char_name'],
                    description=f'아툴점수: {sc["atool_score"]:,}',
                )
                for sc in subs
            ]
            del_sel = discord.ui.Select(
                placeholder='🗑️ 삭제할 부캐를 선택하세요',
                options=options,
                row=1,
            )
            del_sel.callback = self._delete_callback
            self.add_item(del_sel)

    async def _add_callback(self, interaction: discord.Interaction):
        remaining = _check_cooldown(_subchar_cooldown, str(interaction.user.id))
        if remaining > 0:
            await interaction.response.send_message(
                f'⏳ {remaining}초 후에 다시 시도해주세요.', ephemeral=True
            )
            return
        _subchar_cooldown[str(interaction.user.id)] = time.time()
        await interaction.response.send_modal(SubCharModal())

    async def _delete_callback(self, interaction: discord.Interaction):
        char_name = interaction.data['values'][0]
        await db.delete_sub_character(str(interaction.user.id), char_name)
        await interaction.response.send_message(
            f'✅ **{char_name}** 부캐가 삭제되었습니다.',
            ephemeral=True,
        )


class SubCharView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='부캐 등록 / 관리',
        style=discord.ButtonStyle.primary,
        custom_id='legion_subchar_button',
        emoji='🎭',
    )
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        subs = list(await db.get_sub_characters(str(interaction.user.id)))

        embed = discord.Embed(title='🎭 내 부캐릭터 목록', color=discord.Color.purple())
        if subs:
            for sc in subs:
                embed.add_field(
                    name=f'{sc["char_name"]} ({sc["job"]})',
                    value=f'전투력: {sc["combat_power"]:,} | 아툴점수: {sc["atool_score"]:,}',
                    inline=False,
                )
            embed.set_footer(text=f'등록된 부캐: {len(subs)}/5')
        else:
            embed.description = '등록된 부캐릭터가 없습니다.\n아래 버튼으로 추가하세요.'

        await interaction.response.send_message(embed=embed, view=SubCharManageView(subs=subs), ephemeral=True)


# ── 닉네임 빌더 ───────────────────────────────────────────────────────────────

def _build_nickname(char_name: str, job: str, combat_power: int) -> str:
    nick = f'{char_name}/{job}/{combat_power:,}'
    if len(nick) > 32:
        nick = f'{char_name}/{job}'
    if len(nick) > 32:
        nick = char_name[:32]
    return nick


# ── Registration Cog ──────────────────────────────────────────────────────────

class Registration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_nickname_update.start()

    def cog_unload(self):
        self.daily_nickname_update.cancel()

    @tasks.loop(time=dtime(hour=0, minute=0))
    async def daily_nickname_update(self):
        guilds = [self.bot.get_guild(gid) for gid in GUILD_IDS]
        guilds = [g for g in guilds if g]
        if not guilds:
            return
        print('[자동갱신] 전체 유저 닉네임 업데이트 시작...')
        users = await db.get_all_users()
        updated = 0
        for row in users:
            fresh = await scrape_character(row['char_name'])
            if not fresh:
                continue
            await db.upsert_user(
                discord_id=row['discord_id'],
                discord_name=row['discord_name'] or '',
                char_name=fresh['char_name'],
                job=fresh['job'],
                combat_power=fresh['combat_power'],
                atool_score=fresh['atool_score'],
            )
            for guild in guilds:
                member = guild.get_member(int(row['discord_id']))
                if member:
                    try:
                        await member.edit(nick=_build_nickname(fresh['char_name'], fresh['job'], fresh['combat_power']))
                        updated += 1
                    except discord.Forbidden:
                        pass
        print(f'[자동갱신] 완료 — {updated}명 닉네임 업데이트')

    @daily_nickname_update.before_loop
    async def before_daily_update(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='갱신', description='전체 유저 데이터를 최신화합니다 (관리자 전용)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def refresh_all(self, interaction: discord.Interaction):
        global _refresh_running
        if _refresh_running:
            await interaction.response.send_message('⏳ 이미 갱신이 진행 중입니다. 잠시 후 다시 시도해주세요.', ephemeral=True)
            return

        _refresh_running = True
        await interaction.response.defer(ephemeral=True)

        users = await db.get_all_users()
        total = len(users)

        if total == 0:
            _refresh_running = False
            await interaction.followup.send('❌ 등록된 유저가 없습니다.', ephemeral=True)
            return

        await interaction.followup.send(
            f'🔄 전체 유저 **{total}명** 데이터 갱신 시작...\n(완료 시 결과를 알려드립니다)',
            ephemeral=True,
        )

        guilds = [self.bot.get_guild(gid) for gid in GUILD_IDS]
        guilds = [g for g in guilds if g]

        main_ok = main_fail = 0
        sub_ok = sub_fail = 0
        nick_updated = 0

        try:
            # 메인캐 갱신
            for row in users:
                fresh = await scrape_character(row['char_name'])
                if fresh:
                    await db.upsert_user(
                        discord_id=row['discord_id'],
                        discord_name=row['discord_name'] or '',
                        char_name=fresh['char_name'],
                        job=fresh['job'],
                        combat_power=fresh['combat_power'],
                        atool_score=fresh['atool_score'],
                    )
                    for guild in guilds:
                        member = guild.get_member(int(row['discord_id']))
                        if member:
                            try:
                                await member.edit(nick=_build_nickname(fresh['char_name'], fresh['job'], fresh['combat_power']))
                                nick_updated += 1
                            except discord.Forbidden:
                                pass
                    main_ok += 1
                else:
                    main_fail += 1

            # 부캐 갱신
            all_subs = await db.get_all_sub_characters()
            for sc in all_subs:
                fresh = await scrape_character(sc['char_name'])
                if fresh:
                    await db.upsert_sub_character(
                        discord_id=sc['discord_id'],
                        char_name=fresh['char_name'],
                        job=fresh['job'],
                        combat_power=fresh['combat_power'],
                        atool_score=fresh['atool_score'],
                    )
                    sub_ok += 1
                else:
                    sub_fail += 1

            lines = [
                f'✅ **갱신 완료!**',
                f'',
                f'**메인캐** — 성공: {main_ok}명 / 실패: {main_fail}명',
                f'**부캐** — 성공: {sub_ok}개 / 실패: {sub_fail}개',
                f'**닉네임 변경** — {nick_updated}명',
            ]
            if main_fail or sub_fail:
                lines.append(f'\n⚠️ 실패 항목은 캐릭터명이 변경됐거나 API 오류일 수 있습니다.')

            await interaction.followup.send('\n'.join(lines), ephemeral=True)

        except Exception:
            await interaction.followup.send('❌ 갱신 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.', ephemeral=True)

        finally:
            _refresh_running = False

    @refresh_all.error
    async def refresh_all_error(self, interaction: discord.Interaction, error):
        global _refresh_running
        _refresh_running = False
        await interaction.response.send_message('❌ 관리자만 사용할 수 있습니다.', ephemeral=True)

    @app_commands.command(name='등록설정', description='유저 등록 버튼을 이 채널에 생성합니다 (관리자 전용)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_register(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='📋 레기온 유저 등록',
            description=(
                '아래 버튼을 클릭하여 캐릭터를 등록하세요!\n\n'
                '등록 후 닉네임이 **캐릭명/직업/전투력** 형식으로 자동 변경됩니다.\n'
                '이미 등록된 분도 버튼을 누르면 정보가 최신화됩니다.'
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=RegisterView())

    @setup_register.error
    async def setup_register_error(self, interaction: discord.Interaction, error):
        await interaction.response.send_message('❌ 관리자만 사용할 수 있습니다.', ephemeral=True)

    @app_commands.command(name='부캐설정', description='부캐 등록 버튼을 이 채널에 생성합니다 (관리자 전용)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_subchar(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='🎭 부캐릭터 등록',
            description=(
                '아래 버튼을 클릭하여 부캐릭터를 등록/관리하세요!\n\n'
                '부캐릭터는 최대 **5개**까지 등록 가능합니다.\n'
                '파티 지원 시 메인캐 또는 부캐를 선택하여 지원할 수 있습니다.'
            ),
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, view=SubCharView())

    @setup_subchar.error
    async def setup_subchar_error(self, interaction: discord.Interaction, error):
        await interaction.response.send_message('❌ 관리자만 사용할 수 있습니다.', ephemeral=True)

    @app_commands.command(name='내정보', description='내 등록 정보를 확인합니다')
    async def my_info(self, interaction: discord.Interaction):
        user = await db.get_user(str(interaction.user.id))
        if not user:
            await interaction.response.send_message(
                '❌ 아직 등록되지 않았습니다. 유저 등록 버튼을 눌러 먼저 등록해주세요!',
                ephemeral=True,
            )
            return

        embed = discord.Embed(title='📋 내 등록 정보', color=discord.Color.blue())
        embed.add_field(name='캐릭터명', value=user['char_name'], inline=True)
        embed.add_field(name='직업', value=user['job'], inline=True)
        embed.add_field(name='전투력', value=f"{user['combat_power']:,}", inline=True)
        embed.add_field(name='아툴점수', value=f"{user['atool_score']:,}", inline=True)

        subs = await db.get_sub_characters(str(interaction.user.id))
        if subs:
            sub_list = '\n'.join(
                f'• {sc["char_name"]} ({sc["job"]}) — 아툴 {sc["atool_score"]:,}'
                for sc in subs
            )
            embed.add_field(name=f'부캐릭터 ({len(subs)}개)', value=sub_list, inline=False)

        embed.set_footer(text='정보를 수정하려면 유저 등록 버튼을 다시 눌러주세요.')
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    bot.add_view(RegisterView())
    bot.add_view(SubCharView())
    await bot.add_cog(Registration(bot))
