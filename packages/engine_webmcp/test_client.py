"""
Phase 2 standalone test -- NO LLM, no Engine 2 involved (BUILD_STEPS.md
checkpoint): capability check must return supported=True + schemas on
our demo pages, and supported=False on a real site that doesn't support
WebMCP.

Requires the demo server running first, in another terminal:
    python packages/engine_webmcp/demo_pages/server.py

Run with: python -m engine_webmcp.test_client
"""
from __future__ import annotations

import asyncio
import os
import sys

from playwright.async_api import async_playwright

from .capability_check import check_webmcp_capability
from .native_bridge import call_webmcp_tool

DEMO_BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:4173")


async def main() -> None:
    headless = os.environ.get("HEADLESS", "true").lower() != "false"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        print(f"--- Todo demo page ({DEMO_BASE}/todo-app/) ---")
        await page.goto(f"{DEMO_BASE}/todo-app/", wait_until="domcontentloaded")
        cap = await check_webmcp_capability(page)
        print("capability check:", cap)
        print("add-todo:", await call_webmcp_tool(page, "add-todo", {"text": "Buy milk"}))
        print("list-todos:", await call_webmcp_tool(page, "list-todos"))

        print(f"\n--- Product search demo page ({DEMO_BASE}/product-search/) ---")
        await page.goto(f"{DEMO_BASE}/product-search/", wait_until="domcontentloaded")
        cap = await check_webmcp_capability(page)
        print("capability check:", cap)
        print(
            "search-products:",
            await call_webmcp_tool(page, "search-products", {"category": "electronics"}),
        )

        print("\n--- Real site, no WebMCP -- must report supported=False ---")
        await page.goto("https://example.com", wait_until="domcontentloaded")
        cap = await check_webmcp_capability(page)
        print("capability check on example.com:", cap)
        if cap["supported"]:
            print("FAIL: expected supported=False on a page with no WebMCP registry")
            sys.exit(1)
        print("OK: correctly reported no WebMCP support")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
