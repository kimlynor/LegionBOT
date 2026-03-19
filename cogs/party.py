import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.excel import create_party_excel


async def _update_party_count(interaction: discord.Interaction, party, count: int):
    try:
        channel = interaction.client.get_channel(int(party['channel_id']))
        if channel:
            msg = await channel.fetch_message(int(party['message_id']))
            embed = msg.embeds[0]
            for i, field in enumerate(embed.fields):
                if '지원자' in field.name:
                    embed.set_field_at(i, name='👥 지원자', value=f'{count}명', inline=True)
                    break
            await msg.edit(embed=embed)
    except Exception:
        pass


async def _post_party(interaction: discord.Interaction, purpose: str, deadline_dt: datetime):
    embed = discord.Embed(
        title='⚔️ 파티 모집',
        description=purpose,
        color=discord.Color.gold(),
    )
    embed.add_field(
        name='⏰ 마감 일시',
        value=deadline_dt.strftime('%Y년 %m월 %d일 %H:%M'),
        inline=False,
    )
    embed.add_field(name='👥 지원자', value='0명', inline=True)
    embed.set_footer(text=f'모집자: {interaction.user.display_name}')

    temp_view = PartyApplyView(party_id=0)
    msg = await interaction.channel.send(embed=embed, view=temp_view)

    party_id = await db.create_party(
        guild_id=str(interaction.guild_id),
        channel_id=str(interaction.channel_id),
        message_id=str(msg.id),
        purpose=purpose,
        deadline=deadline_dt.strftime('%Y-%m-%d %H:%M'),
        creator_id=str(interaction.user.id),
    )

    real_view = PartyApplyView(party_id=party_id)
    interaction.client.add_view(real_view)
    await msg.edit(view=real_view)

    cog: Party = interaction.client.get_cog('Party')
    if cog:
        cog.schedule_close(party_id, deadline_dt, interaction.channel)


# ── 1단계: 모집 목적 입력 모달 ─────────────────────────────────────────────────
class PartyModal(discord.ui.Modal, title='파티 모집 등록'):
    purpose = discord.ui.TextInput(
        label='모집 목적',
        placeholder='예: 군단전, 레이드, 필드보스 등',
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        view = DateTimeSelectView(purpose=self.purpose.value, creator=interaction.user)
        embed = discord.Embed(
            title='📅 마감 일시 선택',
            description=f'**모집 목적:** {self.purpose.value}\n\n① 월 / 시 / 분을 선택하고\n② **다음** 버튼을 누르면 날짜(일)를 입력하는 창이 열립니다.',
            color=discord.Color.blue(),
        )
        embed.set_footer(text='5분 안에 선택하지 않으면 취소됩니다.')
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ── 3단계: 날짜(일) 직접 입력 모달 ────────────────────────────────────────────
class DayInputModal(discord.ui.Modal, title='마감 날짜 확정'):
    day = discord.ui.TextInput(
        label='마감 날짜 (일)',
        placeholder='1 ~ 31 사이의 숫자를 입력하세요',
        min_length=1,
        max_length=2,
    )

    def __init__(self, purpose: str, month: int, hour: int, minute: int):
        super().__init__()
        self.purpose = purpose
        self.sel_month = month
        self.sel_hour = hour
        self.sel_minute = minute

    async def on_submit(self, interaction: discord.Interaction):
        try:
            d = int(self.day.value.strip())
            if not 1 <= d <= 31:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message('❌ 1~31 사이의 숫자를 입력해주세요.', ephemeral=True)
            return

        now = datetime.now()
        year = now.year
        try:
            deadline_dt = datetime(year, self.sel_month, d, self.sel_hour, self.sel_minute)
        except ValueError:
            await interaction.response.send_message('❌ 올바르지 않은 날짜입니다. (예: 2월 31일 등)', ephemeral=True)
            return

        if deadline_dt <= now:
            try:
                deadline_dt = deadline_dt.replace(year=year + 1)
            except ValueError:
                await interaction.response.send_message('❌ 마감 시간은 현재보다 이후여야 합니다.', ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)
        await _post_party(interaction, self.purpose, deadline_dt)
        await interaction.edit_original_response(
            embed=discord.Embed(
                title='✅ 파티 모집 등록 완료',
                description=(
                    f'**{self.purpose}**\n'
                    f'마감: {deadline_dt.strftime("%Y년 %m월 %d일 %H:%M")}'
                ),
                color=discord.Color.green(),
            ),
            view=None,
        )


# ── 2단계: 월/시/분 드롭다운 뷰 ────────────────────────────────────────────────
class DateTimeSelectView(discord.ui.View):
    def __init__(self, purpose: str, creator: discord.Member):
        super().__init__(timeout=300)
        self.purpose = purpose
        self.creator = creator
        self.sel_month: int | None = None
        self.sel_hour: int | None = None
        self.sel_minute: int | None = None

        now = datetime.now()

        month_opts = []
        for i in range(4):
            m = ((now.month - 1 + i) % 12) + 1
            month_opts.append(discord.SelectOption(label=f'{m}월', value=str(m)))

        month_sel = discord.ui.Select(placeholder='📅 월 선택', options=month_opts, row=0)
        month_sel.callback = self._month_cb
        self.add_item(month_sel)

        hour_sel = discord.ui.Select(
            placeholder='🕐 시 선택',
            options=[discord.SelectOption(label=f'{h:02d}시', value=str(h)) for h in range(24)],
            row=1,
        )
        hour_sel.callback = self._hour_cb
        self.add_item(hour_sel)

        minute_sel = discord.ui.Select(
            placeholder='⏱ 분 선택',
            options=[discord.SelectOption(label=f'{m:02d}분', value=str(m)) for m in range(0, 60, 10)],
            row=2,
        )
        minute_sel.callback = self._minute_cb
        self.add_item(minute_sel)

    async def _month_cb(self, interaction: discord.Interaction):
        self.sel_month = int(interaction.data['values'][0])
        await interaction.response.defer()

    async def _hour_cb(self, interaction: discord.Interaction):
        self.sel_hour = int(interaction.data['values'][0])
        await interaction.response.defer()

    async def _minute_cb(self, interaction: discord.Interaction):
        self.sel_minute = int(interaction.data['values'][0])
        await interaction.response.defer()

    @discord.ui.button(label='다음 (날짜 입력)', style=discord.ButtonStyle.success, emoji='📅', row=3)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if any(v is None for v in [self.sel_month, self.sel_hour, self.sel_minute]):
            await interaction.response.send_message('❌ 월/시/분을 모두 선택해주세요!', ephemeral=True)
            return
        await interaction.response.send_modal(
            DayInputModal(self.purpose, self.sel_month, self.sel_hour, self.sel_minute)
        )
        self.stop()

    @discord.ui.button(label='취소', style=discord.ButtonStyle.secondary, emoji='✖️', row=3)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title='취소됨', color=discord.Color.greyple()),
            view=None,
        )
        self.stop()


DAY_OPTIONS = [
    discord.SelectOption(label='월요일',           value='월요일'),
    discord.SelectOption(label='화요일',           value='화요일'),
    discord.SelectOption(label='수요일',           value='수요일'),
    discord.SelectOption(label='목요일',           value='목요일'),
    discord.SelectOption(label='금요일',           value='금요일'),
    discord.SelectOption(label='토요일',           value='토요일'),
    discord.SelectOption(label='일요일',           value='일요일'),
    discord.SelectOption(label='평일 전체 (월~금)', value='평일 전체 (월~금)'),
    discord.SelectOption(label='주말 (토~일)',      value='주말 (토~일)'),
    discord.SelectOption(label='수~일 무관',        value='수~일 무관'),
    discord.SelectOption(label='월~화 무관',        value='월~화 무관'),
    discord.SelectOption(label='전체 무관',         value='전체 무관'),
]


# ── 캐릭터 + 요일 선택 뷰 ─────────────────────────────────────────────────────
class ApplySetupView(discord.ui.View):
    def __init__(self, party_id: int, main_char, sub_chars: list):
        super().__init__(timeout=60)
        self.party_id = party_id
        self._main = main_char
        self._subs = {sc['char_name']: sc for sc in sub_chars}
        self.selected_char = main_char
        self.is_sub = False
        self.selected_days = None

        row = 0

        # 캐릭터 선택 (부캐 있는 경우만)
        if sub_chars:
            char_options = [
                discord.SelectOption(
                    label=f'[메인] {main_char["char_name"]} ({main_char["job"]})',
                    value='main',
                    description=f'아툴점수: {main_char["atool_score"]:,}',
                    default=True,
                )
            ]
            for sc in sub_chars:
                char_options.append(discord.SelectOption(
                    label=f'[부캐] {sc["char_name"]} ({sc["job"]})',
                    value=f'sub_{sc["char_name"]}',
                    description=f'아툴점수: {sc["atool_score"]:,}',
                ))
            char_sel = discord.ui.Select(placeholder='지원할 캐릭터를 선택하세요', options=char_options, row=row)
            char_sel.callback = self._char_cb
            self.add_item(char_sel)
            row += 1

        # 요일 선택
        day_sel = discord.ui.Select(placeholder='가능 요일을 선택하세요', options=DAY_OPTIONS, row=row)
        day_sel.callback = self._day_cb
        self.add_item(day_sel)
        row += 1

        # 다음 버튼
        next_btn = discord.ui.Button(label='다음', style=discord.ButtonStyle.success, emoji='➡️', row=row)
        next_btn.callback = self._next_cb
        self.add_item(next_btn)

    async def _char_cb(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        if value == 'main':
            self.selected_char = self._main
            self.is_sub = False
        else:
            self.selected_char = self._subs[value[4:]]
            self.is_sub = True
        await interaction.response.defer()

    async def _day_cb(self, interaction: discord.Interaction):
        self.selected_days = interaction.data['values'][0]
        await interaction.response.defer()

    async def _next_cb(self, interaction: discord.Interaction):
        if self.selected_days is None:
            await interaction.response.send_message('❌ 가능 요일을 선택해주세요!', ephemeral=True)
            return
        await interaction.response.send_modal(
            ApplyMemoModal(
                party_id=self.party_id,
                char_name=self.selected_char['char_name'],
                job=self.selected_char['job'],
                combat_power=self.selected_char['combat_power'],
                atool_score=self.selected_char['atool_score'],
                is_sub=self.is_sub,
                available_days=self.selected_days,
            )
        )
        self.stop()


# ── 지원 취소 선택 뷰 (부캐 복수 지원 시) ─────────────────────────────────────
class CancelSelectView(discord.ui.View):
    def __init__(self, party_id: int, my_apps: list):
        super().__init__(timeout=60)
        self.party_id = party_id

        options = [
            discord.SelectOption(
                label=f'{"[부캐] " if ap["is_sub"] else "[메인] "}{ap["char_name"]} ({ap["job"]})',
                value=ap['char_name'],
            )
            for ap in my_apps
        ]
        options.append(discord.SelectOption(label='전체 취소', value='__ALL__', emoji='🗑️'))

        sel = discord.ui.Select(placeholder='취소할 캐릭터를 선택하세요', options=options)
        sel.callback = self._select_cb
        self.add_item(sel)

    async def _select_cb(self, interaction: discord.Interaction):
        value = interaction.data['values'][0]
        discord_id = str(interaction.user.id)

        if value == '__ALL__':
            await db.remove_all_applicants_by_discord(self.party_id, discord_id)
            msg = '✅ 모든 지원이 취소되었습니다.'
        else:
            await db.remove_applicant(self.party_id, discord_id, value)
            msg = f'✅ **{value}** 지원이 취소되었습니다.'

        applicants = await db.get_party_applicants(self.party_id)
        party = await db.get_party(self.party_id)

        await interaction.response.send_message(msg, ephemeral=True)
        if party:
            await _update_party_count(interaction, party, len(applicants))
        self.stop()


# ── 파티 지원 모달 ─────────────────────────────────────────────────────────────
class ApplyMemoModal(discord.ui.Modal, title='파티 지원'):
    available_time = discord.ui.TextInput(
        label='가능 시간',
        placeholder='예: 9시 이후, 오후 6시~, 저녁만 가능',
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )
    memo = discord.ui.TextInput(
        label='메모 (선택)',
        placeholder='예: 1넴, 1,2넴 다 가능, 힐 가능 등 (비워도 됩니다)',
        style=discord.TextStyle.short,
        required=False,
        max_length=100,
    )

    def __init__(self, party_id: int, char_name: str, job: str, combat_power: int, atool_score: int, is_sub: bool = False, available_days: str = ''):
        super().__init__()
        self.party_id = party_id
        self.char_name = char_name
        self.job = job
        self.combat_power = combat_power
        self.atool_score = atool_score
        self.is_sub = is_sub
        self.available_days = available_days

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        party = await db.get_party(self.party_id)
        if not party or party['closed']:
            await interaction.followup.send('❌ 이미 마감된 모집입니다.', ephemeral=True)
            return

        memo_text = self.memo.value.strip() if self.memo.value else ''
        available_time_text = self.available_time.value.strip()

        success = await db.add_applicant(
            party_id=self.party_id,
            discord_id=str(interaction.user.id),
            char_name=self.char_name,
            job=self.job,
            combat_power=self.combat_power,
            atool_score=self.atool_score,
            is_sub=1 if self.is_sub else 0,
            memo=memo_text,
            available_time=available_time_text,
            available_days=self.available_days,
        )
        if not success:
            await interaction.followup.send('이미 이 캐릭터로 지원하셨습니다! ✅', ephemeral=True)
            return

        applicants = await db.get_party_applicants(self.party_id)
        char_type = '부캐' if self.is_sub else '메인캐'

        msg_text = (
            f'✅ 파티 지원 완료!\n'
            f'캐릭터: **{self.char_name}** ({self.job}) [{char_type}]\n'
            f'가능 요일: `{self.available_days}`\n'
            f'가능 시간: `{available_time_text}`\n'
        )
        if memo_text:
            msg_text += f'메모: `{memo_text}`\n'
        msg_text += f'현재 지원자: **{len(applicants)}명**'

        await interaction.followup.send(msg_text, ephemeral=True)
        await _update_party_count(interaction, party, len(applicants))


# ── 파티 지원/취소 버튼 뷰 ────────────────────────────────────────────────────
class PartyApplyView(discord.ui.View):
    def __init__(self, party_id: int):
        super().__init__(timeout=None)
        self.party_id = party_id

        apply_btn = discord.ui.Button(
            label='파티 지원',
            style=discord.ButtonStyle.success,
            emoji='⚔️',
            custom_id=f'party_apply_{party_id}',
        )
        apply_btn.callback = self._apply_callback
        self.add_item(apply_btn)

        cancel_btn = discord.ui.Button(
            label='지원 취소',
            style=discord.ButtonStyle.secondary,
            emoji='❌',
            custom_id=f'party_cancel_{party_id}',
        )
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

        close_btn = discord.ui.Button(
            label='즉시 마감',
            style=discord.ButtonStyle.danger,
            emoji='🔒',
            custom_id=f'party_force_close_{party_id}',
        )
        close_btn.callback = self._force_close_callback
        self.add_item(close_btn)

    async def _apply_callback(self, interaction: discord.Interaction):
        party = await db.get_party(self.party_id)
        if not party or party['closed']:
            await interaction.response.send_message('❌ 이미 마감된 모집입니다.', ephemeral=True)
            return

        user = await db.get_user(str(interaction.user.id))
        if not user:
            await interaction.response.send_message('❌ 먼저 **유저 등록**을 해주세요!', ephemeral=True)
            return

        sub_chars = list(await db.get_sub_characters(str(interaction.user.id)))
        view = ApplySetupView(self.party_id, user, sub_chars)
        embed = discord.Embed(
            title='파티 지원',
            description='가능 요일을 선택하고 [다음]을 눌러주세요.',
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _cancel_callback(self, interaction: discord.Interaction):
        party = await db.get_party(self.party_id)
        if not party or party['closed']:
            await interaction.response.send_message('❌ 이미 마감된 모집입니다.', ephemeral=True)
            return

        my_apps = list(await db.get_party_applicants_by_discord(self.party_id, str(interaction.user.id)))
        if not my_apps:
            await interaction.response.send_message('❌ 지원 내역이 없습니다.', ephemeral=True)
            return

        if len(my_apps) == 1:
            char_name = my_apps[0]['char_name']
            await db.remove_applicant(self.party_id, str(interaction.user.id), char_name)
            applicants = await db.get_party_applicants(self.party_id)
            await interaction.response.send_message(
                f'✅ **{char_name}** 지원이 취소되었습니다.',
                ephemeral=True,
            )
            await _update_party_count(interaction, party, len(applicants))
        else:
            view = CancelSelectView(self.party_id, my_apps)
            await interaction.response.send_message(
                '취소할 캐릭터를 선택하세요:',
                view=view,
                ephemeral=True,
            )

    async def _force_close_callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ 관리자만 즉시 마감할 수 있습니다.', ephemeral=True)
            return

        party = await db.get_party(self.party_id)
        if not party or party['closed']:
            await interaction.response.send_message('❌ 이미 마감된 모집입니다.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        cog: 'Party' = interaction.client.get_cog('Party')
        if not cog:
            await interaction.followup.send('❌ 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요.', ephemeral=True)
            return

        if self.party_id in cog._tasks:
            cog._tasks[self.party_id].cancel()

        await interaction.followup.send('🔒 즉시 마감 처리 중...', ephemeral=True)
        await cog._close_party(self.party_id, interaction.channel)


class PartySetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='파티 모집 등록',
        style=discord.ButtonStyle.primary,
        custom_id='legion_party_setup_button',
        emoji='📋',
    )
    async def setup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                '❌ 관리자만 파티를 등록할 수 있습니다.',
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(PartyModal())


class Party(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks: dict[int, asyncio.Task] = {}

    async def cog_load(self):
        asyncio.create_task(self._restore_parties())

    async def _restore_parties(self):
        await self.bot.wait_until_ready()
        open_parties = await db.get_open_parties()
        for party in open_parties:
            self.bot.add_view(PartyApplyView(party_id=party['id']))
            deadline_dt = datetime.strptime(party['deadline'], '%Y-%m-%d %H:%M')
            channel = self.bot.get_channel(int(party['channel_id']))
            if channel:
                if deadline_dt > datetime.now():
                    self.schedule_close(party['id'], deadline_dt, channel)
                else:
                    asyncio.create_task(self._close_party(party['id'], channel))

    def schedule_close(self, party_id: int, deadline_dt: datetime, channel):
        if party_id in self._tasks:
            self._tasks[party_id].cancel()
        task = asyncio.create_task(self._wait_and_close(party_id, deadline_dt, channel))
        self._tasks[party_id] = task

    async def _wait_and_close(self, party_id: int, deadline_dt: datetime, channel):
        wait_sec = (deadline_dt - datetime.now()).total_seconds()
        if wait_sec > 0:
            await asyncio.sleep(wait_sec)
        await self._close_party(party_id, channel)

    async def _close_party(self, party_id: int, channel):
        party = await db.get_party(party_id)
        if not party or party['closed']:
            return

        await db.close_party(party_id)
        applicants = await db.get_party_applicants(party_id)

        embed = discord.Embed(
            title='🔔 파티 모집 마감',
            description=f'**{party["purpose"]}** 모집이 마감되었습니다!',
            color=discord.Color.red(),
        )
        embed.add_field(name='총 지원자', value=f'{len(applicants)}명', inline=True)

        if applicants:
            from utils.scraper import scrape_character

            notify_embed = discord.Embed(
                title='🔄 마감 시점 데이터 갱신 중...',
                description=f'지원자 {len(applicants)}명의 최신 점수를 조회하고 있습니다.',
                color=discord.Color.orange(),
            )
            notify_msg = await channel.send(embed=notify_embed)

            refreshed = []
            for ap in applicants:
                try:
                    fresh = await scrape_character(ap['char_name'])
                except Exception:
                    fresh = None

                if fresh:
                    try:
                        if ap['is_sub']:
                            await db.upsert_sub_character(
                                discord_id=ap['discord_id'],
                                char_name=fresh['char_name'],
                                job=fresh['job'],
                                combat_power=fresh['combat_power'],
                                atool_score=fresh['atool_score'],
                            )
                        else:
                            await db.upsert_user(
                                discord_id=ap['discord_id'],
                                discord_name='',
                                char_name=fresh['char_name'],
                                job=fresh['job'],
                                combat_power=fresh['combat_power'],
                                atool_score=fresh['atool_score'],
                            )
                    except Exception:
                        pass  # DB 갱신 실패해도 엑셀 출력은 계속 진행
                    refreshed.append({
                        'char_name': fresh['char_name'],
                        'job': fresh['job'],
                        'combat_power': fresh['combat_power'],
                        'atool_score': fresh['atool_score'],
                        'memo': ap['memo'],
                        'available_time': ap['available_time'],
                        'available_days': ap['available_days'],
                        'is_sub': ap['is_sub'],
                    })
                else:
                    refreshed.append({
                        'char_name': ap['char_name'],
                        'job': ap['job'],
                        'combat_power': ap['combat_power'],
                        'atool_score': ap['atool_score'],
                        'memo': ap['memo'],
                        'available_time': ap['available_time'],
                        'available_days': ap['available_days'],
                        'is_sub': ap['is_sub'],
                    })

            refreshed.sort(key=lambda x: (x['is_sub'], x['job'], -x['atool_score']))

            await notify_msg.delete()

            excel_bytes = create_party_excel(refreshed, party['purpose'])
            file = discord.File(excel_bytes, filename=f'파티지원자_{party_id}.xlsx')
            await channel.send(embed=embed, file=file)
        else:
            embed.add_field(name='', value='지원자가 없습니다.', inline=False)
            await channel.send(embed=embed)

        # 원본 메시지 버튼 비활성화
        try:
            msg = await channel.fetch_message(int(party['message_id']))
            closed_embed = msg.embeds[0]
            closed_embed.color = discord.Color.dark_red()
            closed_embed.set_footer(text='모집 마감됨')

            closed_view = discord.ui.View()
            closed_btn = discord.ui.Button(
                label='모집 마감',
                style=discord.ButtonStyle.danger,
                disabled=True,
                emoji='🔒',
            )
            closed_view.add_item(closed_btn)
            await msg.edit(embed=closed_embed, view=closed_view)
        except Exception:
            pass

        self._tasks.pop(party_id, None)

    @app_commands.command(name='파티설정', description='파티 모집 버튼을 이 채널에 생성합니다 (관리자 전용)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_party(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title='⚔️ 파티 모집',
            description=(
                '아래 버튼을 클릭하여 파티 모집을 등록하세요.\n'
                '*(관리자 전용)*\n\n'
                '모집 등록 후 유저들이 지원 버튼을 클릭하면 자동으로 데이터가 수집됩니다.\n'
                '마감 시간이 되면 자동으로 지원자 명단이 엑셀 파일로 전송됩니다.'
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, view=PartySetupView())

    @setup_party.error
    async def setup_party_error(self, interaction: discord.Interaction, error):
        await interaction.response.send_message('❌ 관리자만 사용할 수 있습니다.', ephemeral=True)


async def setup(bot: commands.Bot):
    bot.add_view(PartySetupView())
    await bot.add_cog(Party(bot))
