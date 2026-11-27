"""Playwright(헤드리스 크롬) 공통 도우미. 화면을 실제 브라우저로 열어 읽을 때 사용."""
from __future__ import annotations

import contextlib
import time

from playwright.sync_api import sync_playwright

from scrapers.base import USER_AGENT, MIN_INTERVAL


@contextlib.contextmanager
def open_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=USER_AGENT, locale="ko-KR", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(45_000)
        try:
            yield page
        finally:
            ctx.close()
            browser.close()


def pause(seconds: float = MIN_INTERVAL) -> None:
    time.sleep(seconds)
