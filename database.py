import aiosqlite

DB_PATH = 'legion.db'


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                discord_name TEXT,
                char_name TEXT,
                job TEXT,
                combat_power INTEGER DEFAULT 0,
                atool_score INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS parties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                channel_id TEXT,
                message_id TEXT,
                purpose TEXT,
                deadline TEXT,
                creator_id TEXT,
                closed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS sub_characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT,
                char_name TEXT,
                job TEXT,
                combat_power INTEGER DEFAULT 0,
                atool_score INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(discord_id, char_name)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS party_applicants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                party_id INTEGER,
                discord_id TEXT,
                char_name TEXT DEFAULT '',
                job TEXT DEFAULT '',
                combat_power INTEGER DEFAULT 0,
                atool_score INTEGER DEFAULT 0,
                is_sub INTEGER DEFAULT 0,
                memo TEXT DEFAULT '',
                available_time TEXT DEFAULT '',
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (party_id) REFERENCES parties(id),
                UNIQUE(party_id, discord_id, char_name)
            )
        ''')

        # available_days 컬럼 마이그레이션
        try:
            await db.execute('SELECT available_days FROM party_applicants LIMIT 1')
        except Exception:
            await db.execute("ALTER TABLE party_applicants ADD COLUMN available_days TEXT DEFAULT ''")

        # 기존 DB 마이그레이션: char_name 컬럼 없으면 테이블 재생성
        try:
            await db.execute('SELECT char_name FROM party_applicants LIMIT 1')
        except Exception:
            await db.execute('''
                CREATE TABLE party_applicants_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    party_id INTEGER,
                    discord_id TEXT,
                    char_name TEXT DEFAULT '',
                    job TEXT DEFAULT '',
                    combat_power INTEGER DEFAULT 0,
                    atool_score INTEGER DEFAULT 0,
                    is_sub INTEGER DEFAULT 0,
                    memo TEXT DEFAULT '',
                    available_time TEXT DEFAULT '',
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (party_id) REFERENCES parties(id),
                    UNIQUE(party_id, discord_id, char_name)
                )
            ''')
            await db.execute('''
                INSERT INTO party_applicants_new
                    (id, party_id, discord_id, memo, available_time, applied_at)
                SELECT id, party_id, discord_id, memo, available_time, applied_at
                FROM party_applicants
            ''')
            await db.execute('DROP TABLE party_applicants')
            await db.execute('ALTER TABLE party_applicants_new RENAME TO party_applicants')

        await db.commit()


# ── users ─────────────────────────────────────────────────────────────────────

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users') as cursor:
            return await cursor.fetchall()


async def get_user(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users WHERE discord_id = ?', (discord_id,)) as cursor:
            return await cursor.fetchone()


async def upsert_user(discord_id: str, discord_name: str, char_name: str, job: str, combat_power: int, atool_score: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO users (discord_id, discord_name, char_name, job, combat_power, atool_score)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                discord_name = excluded.discord_name,
                char_name = excluded.char_name,
                job = excluded.job,
                combat_power = excluded.combat_power,
                atool_score = excluded.atool_score
        ''', (discord_id, discord_name, char_name, job, combat_power, atool_score))
        await db.commit()


# ── sub_characters ────────────────────────────────────────────────────────────

async def get_sub_characters(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT * FROM sub_characters WHERE discord_id = ? ORDER BY atool_score DESC',
            (discord_id,)
        ) as cursor:
            return await cursor.fetchall()


async def add_sub_character(discord_id: str, char_name: str, job: str, combat_power: int, atool_score: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO sub_characters (discord_id, char_name, job, combat_power, atool_score)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_id, char_name) DO UPDATE SET
                job = excluded.job,
                combat_power = excluded.combat_power,
                atool_score = excluded.atool_score
        ''', (discord_id, char_name, job, combat_power, atool_score))
        await db.commit()


async def delete_sub_character(discord_id: str, char_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM sub_characters WHERE discord_id = ? AND char_name = ?',
            (discord_id, char_name)
        )
        await db.commit()


async def upsert_sub_character(discord_id: str, char_name: str, job: str, combat_power: int, atool_score: int):
    await add_sub_character(discord_id, char_name, job, combat_power, atool_score)


# ── parties ───────────────────────────────────────────────────────────────────

async def get_party(party_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM parties WHERE id = ?', (party_id,)) as cursor:
            return await cursor.fetchone()


async def create_party(guild_id: str, channel_id: str, message_id: str, purpose: str, deadline: str, creator_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            INSERT INTO parties (guild_id, channel_id, message_id, purpose, deadline, creator_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (guild_id, channel_id, message_id, purpose, deadline, creator_id))
        await db.commit()
        return cursor.lastrowid


async def update_party_message(party_id: int, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE parties SET message_id = ? WHERE id = ?', (message_id, party_id))
        await db.commit()


async def close_party(party_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE parties SET closed = 1 WHERE id = ?', (party_id,))
        await db.commit()


async def get_open_parties():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM parties WHERE closed = 0') as cursor:
            return await cursor.fetchall()


# ── party_applicants ──────────────────────────────────────────────────────────

async def add_applicant(
    party_id: int,
    discord_id: str,
    char_name: str,
    job: str,
    combat_power: int,
    atool_score: int,
    is_sub: int = 0,
    memo: str = '',
    available_time: str = '',
    available_days: str = '',
) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                '''INSERT INTO party_applicants
                   (party_id, discord_id, char_name, job, combat_power, atool_score, is_sub, memo, available_time, available_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (party_id, discord_id, char_name, job, combat_power, atool_score, is_sub, memo, available_time, available_days)
            )
            await db.commit()
            return True
        except Exception:
            return False


async def get_party_applicants(party_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT char_name, job, combat_power, atool_score, discord_id, memo, available_time, available_days, is_sub
            FROM party_applicants
            WHERE party_id = ?
            ORDER BY is_sub, job, atool_score DESC
        ''', (party_id,)) as cursor:
            return await cursor.fetchall()


async def get_party_applicants_by_discord(party_id: int, discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT * FROM party_applicants WHERE party_id = ? AND discord_id = ?',
            (party_id, discord_id)
        ) as cursor:
            return await cursor.fetchall()


async def remove_applicant(party_id: int, discord_id: str, char_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM party_applicants WHERE party_id = ? AND discord_id = ? AND char_name = ?',
            (party_id, discord_id, char_name)
        )
        await db.commit()


async def remove_all_applicants_by_discord(party_id: int, discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM party_applicants WHERE party_id = ? AND discord_id = ?',
            (party_id, discord_id)
        )
        await db.commit()
