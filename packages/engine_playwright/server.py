#!/usr/bin/env python3
"""
Engine 2: Playwright MCP server -- the universal fallback engine.

Exposes exactly five tools (BUILD_STEPS Phase 1 step 2 -- keep the tool
count small and reliable rather than broad): navigate, click, type,
extract_text, screenshot. All five share one BrowserSession (see
browser_session.py) so a multi-step task keeps its page state. The
actual logic for each lives in actions.py, shared with the Phase 3
controller -- this file is just the MCP registration wrapper around it.

Run standalone with `python -m engine_playwright.server` (stdio
transport) or exercised via `python -m engine_playwright.test_client`,
which spawns this file and calls each tool directly through an MCP
client -- no LLM involved, per the Phase 1 checkpoint in BUILD_STEPS.md.

Tool name note: the "type" tool is named type_text() here only because
`type` shadows a Python builtin -- the MCP tool name it's registered
under is still plain "type" (see @mcp.tool(name="type") below), matching
BUILD_STEPS.md and the proposal.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from mcp.server.fastmcp import FastMCP, Image

from . import actions
from .browser_session import session

mcp = FastMCP("engine-playwright")


@mcp.tool()
async def navigate(url: str) -> str:
    """Navigate the current browser page to the given URL. Opens the session's page if none is open yet."""
    page = await session.get_page()
    return await actions.navigate(page, url)


@mcp.tool()
async def click(selector: str) -> str:
    """Click the first element on the current page matching a CSS selector."""
    page = await session.get_page()
    return await actions.click(page, selector)


@mcp.tool(name="type")
async def type_text(selector: str, text: str) -> str:
    """Type text into the first element on the current page matching a CSS selector (input, textarea, or any editable field)."""
    page = await session.get_page()
    return await actions.type_text(page, selector, text)


@mcp.tool()
async def extract_text(selector: Optional[str] = None) -> str:
    """Extract visible text from the current page. Omit selector to get the whole page's text; pass one to scope extraction to a section."""
    page = await session.get_page()
    return await actions.extract_text(page, selector)


@mcp.tool()
async def screenshot() -> Image:
    """Take a PNG screenshot of the current page's visible viewport."""
    page = await session.get_page()
    data = await actions.screenshot(page)
    return Image(data=data, format="png")


def main() -> None:
    try:
        mcp.run()  # blocks; stdio transport by default
    finally:
        asyncio.run(session.close())


if __name__ == "__main__":
    main()
