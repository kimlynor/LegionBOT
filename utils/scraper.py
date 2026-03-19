import asyncio
import re
from typing import Optional
from urllib.parse import unquote

import aiohttp

SERVER_ID = '2013'
RACE = '2'  # 마족

SEARCH_URL = 'https://aion2.plaync.com/ko-kr/api/search/aion2/search/v2/character'
INFO_URL   = 'https://aion2.plaync.com/api/character/info'

_semaphore = asyncio.Semaphore(5)
_session: Optional[aiohttp.ClientSession] = None

# HTTP 요청 타임아웃 (초)
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        _session = aiohttp.ClientSession(connector=connector, timeout=_TIMEOUT)
    return _session


async def scrape_character(char_name: str) -> Optional[dict]:
    """
    aion2.plaync.com 공식 API로 캐릭터 정보를 조회합니다.
    반환: {'char_name': str, 'job': str, 'combat_power': int, 'atool_score': int}
      - combat_power : 아이템레벨 (예: 3976)
      - atool_score  : 공식 전투력 combatPower (예: 508060)
    """
    async with _semaphore:
        try:
            session = await _get_session()

            # 1단계: 이름으로 검색 → characterId 획득
            async with session.get(SEARCH_URL, params={
                'keyword': char_name,
                'serverId': SERVER_ID,
                'race': RACE,
                'size': '5',
            }) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)

            char_list = data.get('list', [])
            if not char_list:
                return None

            # 이름 정확 매칭 (HTML 태그 제거)
            char_id = None
            found_name = None
            for item in char_list:
                clean = re.sub(r'<[^>]+>', '', item.get('name', ''))
                if clean.strip().lower() == char_name.strip().lower():
                    raw_id = item.get('characterId', '')
                    if not raw_id:
                        continue
                    char_id = unquote(raw_id)
                    found_name = clean.strip()
                    break

            if not char_id:
                # 정확 매칭 없으면 첫 번째 결과
                raw_id = char_list[0].get('characterId', '')
                if not raw_id:
                    return None
                char_id = unquote(raw_id)
                found_name = re.sub(r'<[^>]+>', '', char_list[0].get('name', '')).strip()

            # 2단계: characterId로 상세 정보 조회
            async with session.get(INFO_URL, params={
                'lang': 'ko',
                'characterId': char_id,
                'serverId': SERVER_ID,
            }) as resp:
                if resp.status != 200:
                    return None
                info = await resp.json(content_type=None)

            profile = info.get('profile', {})
            class_name    = profile.get('className', '알 수 없음')
            combat_power  = profile.get('combatPower', 0)   # 공식 전투력 (atool_score 자리)
            char_name_res = profile.get('characterName', found_name)

            # 아이템레벨 (combat_power 자리)
            item_level = 0
            for stat in info.get('stat', {}).get('statList', []):
                if stat.get('type') == 'ItemLevel':
                    item_level = int(stat.get('value', 0))
                    break

            return {
                'char_name':    char_name_res,
                'job':          class_name,
                'combat_power': item_level,    # 아이템레벨
                'atool_score':  int(combat_power),  # 공식 전투력
            }

        except asyncio.TimeoutError:
            print(f'[스크래퍼] 타임아웃: {char_name}')
            return None
        except Exception as e:
            print(f'[스크래퍼 오류] {type(e).__name__}: {char_name}')
            return None
