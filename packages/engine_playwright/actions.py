"""
Plain async action functions for Engine 2.

Extracted from server.py so the Phase 3 controller can call the exact
same logic directly against its own shared Page, instead of spawning a
second MCP-over-stdio subprocess just to click a button on the browser
tab it already has open (that would also mean a second, disconnected
BrowserSession -- exactly the "controller loses context on an engine
switch" risk BUILD_STEPS.md flags for Phase 3).

server.py wraps each of these as an @mcp.tool() for the Phase 1
standalone test; the controller (packages/controller) calls them
directly. Behavior/return values are identical either way -- this is a
pure extraction, not a rewrite, so the already-passing Phase 1 test
stays valid.
"""
from __future__ import annotations

from typing import Optional

from playwright.async_api import Page


async def navigate(page: Page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    title = await page.title()
    return f'Navigated to {url}. Page title: "{title}"'


async def click(page: Page, selector: str) -> str:
    await page.click(selector, timeout=10000)
    return f'Clicked element matching "{selector}"'


async def type_text(page: Page, selector: str, text: str) -> str:
    await page.fill(selector, text, timeout=10000)
    return f'Typed "{text}" into "{selector}"'


async def extract_text(page: Page, selector: Optional[str] = None) -> str:
    if selector:
        raw = await page.locator(selector).first.inner_text(timeout=10000)
    else:
        raw = await page.locator("body").inner_text()
    # Cap length so one call on a huge page can't blow the agent's context
    # budget -- the agent can re-scope with a selector.
    return raw.strip()[:8000]


async def screenshot(page: Page) -> bytes:
    return await page.screenshot(type="png")
