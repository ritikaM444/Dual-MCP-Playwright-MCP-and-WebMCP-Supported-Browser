"""
Single long-lived Playwright browser/context for the whole process.
A fresh browser per tool call would break multi-step tasks, since state
(cookies, current page, navigation history) has to persist across
separate tool calls arriving one at a time.

Uses Playwright's ASYNC API deliberately -- the sync API refuses to run
inside an existing asyncio event loop, and FastMCP runs under asyncio.

Two env vars control the "Jarvis mode" visible demo:
  HEADLESS=false  -> opens a real Chromium window you can watch
  SLOW_MO=500     -> pauses 500ms between actions so a human can follow
                     along (0 = full speed; ~300-800 reads well on stage)
Both default to the fast, invisible setting so automated test runs and
the Phase 5 logging runs aren't slowed down.

Note on the browser itself: Playwright downloads and drives its OWN
Chromium build -- not your installed Chrome/Firefox/Edge, and with its
own separate profile and data. Nothing touches your personal browser.
"""
from __future__ import annotations

import os

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


class BrowserSession:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def get_page(self) -> Page:
        """Returns the single live Page, creating browser/context/page on first call."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        if self._browser is None:
            headless = os.environ.get("HEADLESS", "true").lower() != "false"
            slow_mo = int(os.environ.get("SLOW_MO", "0"))
            self._browser = await self._playwright.chromium.launch(
                headless=headless, slow_mo=slow_mo
            )
        if self._context is None:
            self._context = await self._browser.new_context()
        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()
        return self._page

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._page = None
        self._playwright = None


# Process-wide singleton -- every tool call shares this instance.
session = BrowserSession()
