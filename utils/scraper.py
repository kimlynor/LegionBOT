import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Browser

# 무닌 서버 고정 (마족 2013)
RACE_BUTTON = '#race-asmodian'
SERVER_VALUE = '2013'

# 동시 검색 최대 5개 제한 (브라우저 과부하 방지)
_semaphore = asyncio.Semaphore(5)
_browser: Optional[Browser] = None
_playwright = None


async def _get_browser() -> Browser:
    """브라우저 인스턴스 재사용 (없으면 새로 생성)"""
    global _browser, _playwright
    if _browser is None or not _browser.is_connected():
        if _playwright is None:
            _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
    return _browser


async def scrape_character(char_name: str) -> Optional[dict]:
    """
    aion2tool.com 무닌 서버에서 캐릭터 정보를 스크래핑합니다.
    반환: {'char_name': str, 'job': str, 'combat_power': int, 'atool_score': int}
    동시 요청은 최대 5개로 제한 — 100명이 눌러도 순차 처리되어 안전합니다.
    """
    async with _semaphore:
        try:
            browser = await _get_browser()
            page = await browser.new_page()
            try:
                await page.goto('https://aion2tool.com', timeout=30000, wait_until='domcontentloaded')
                await page.wait_for_timeout(2000)

                await page.click(RACE_BUTTON)
                await page.wait_for_timeout(300)
                await page.select_option('#server-select', SERVER_VALUE)
                await page.wait_for_timeout(300)

                await page.fill('#character-keyword', char_name)
                await page.keyboard.press('Enter')

                try:
                    await page.wait_for_selector('#result-nickname', timeout=12000)
                except Exception:
                    return None

                result_name = await page.text_content('#result-nickname')
                if not result_name or not result_name.strip():
                    return None
                result_name = result_name.strip()

                job = '알 수 없음'
                combat_power = 0
                chips = await page.query_selector_all('.stat-chip')
                for chip in chips:
                    text = await chip.text_content()
                    if not text:
                        continue
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    if len(lines) >= 2:
                        label, value = lines[0], lines[-1]
                        if label == '직업':
                            job = value
                        elif label == '전투력':
                            digits = ''.join(c for c in value.replace(',', '') if c.isdigit())
                            if digits:
                                combat_power = int(digits)

                atool_score = 0
                score_el = await page.query_selector('#dps-score-value')
                if score_el:
                    score_text = await score_el.text_content()
                    if score_text:
                        digits = ''.join(c for c in score_text.replace(',', '') if c.isdigit())
                        if digits:
                            atool_score = int(digits)

                return {
                    'char_name': result_name,
                    'job': job,
                    'combat_power': combat_power,
                    'atool_score': atool_score,
                }

            finally:
                await page.close()

        except Exception as e:
            print(f'[스크래퍼 오류] {e}')
            return None
