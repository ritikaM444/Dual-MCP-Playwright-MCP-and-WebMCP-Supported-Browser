"""
Phase 2 standalone test -- NO LLM: capability check must return
supported=True plus schemas on all 8 demo apps, and supported=False on a
real site with no WebMCP.

Demo server must be running in another terminal:
    python packages/engine_webmcp/demo_pages/server.py

Run: python -m engine_webmcp.test_client
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from playwright.async_api import async_playwright

from .capability_check import check_webmcp_capability
from .native_bridge import call_webmcp_tool

DEMO_BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:4173")

DEMO_PAGES: list[dict[str, Any]] = [
    {"path": "todo-app", "tool": "add-todo", "args": {"text": "Buy milk"}},
    {"path": "product-search", "tool": "search-products", "args": {"category": "electronics"}},
    {"path": "shopping-cart", "tool": "add-to-cart", "args": {"productId": 1, "quantity": 2}},
    {"path": "booking", "tool": "check-availability", "args": {"date": "2026-10-01"}},
    {"path": "directory-search", "tool": "search-directory", "args": {"category": "cafe"}},
    {"path": "dashboard", "tool": "get-metric", "args": {"metric": "revenue"}},
    {"path": "contact-form", "tool": "submit-feedback",
     "args": {"name": "Test User", "email": "test@example.com", "message": "Great app!"}},
    {"path": "calendar", "tool": "create-event",
     "args": {"title": "Team sync", "date": "2026-10-01", "time": "10:00 AM"}},
]


async def main() -> None:
    headless = os.environ.get("HEADLESS", "true").lower() != "false"
    failures = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        for demo in DEMO_PAGES:
            url = f"{DEMO_BASE}/{demo['path']}/"
            print(f"--- {url} ---")
            await page.goto(url, wait_until="domcontentloaded")
            cap = await check_webmcp_capability(page)
            if not cap["supported"]:
                print(f"FAIL: {demo['path']} reported supported=False")
                failures += 1
                continue
            print(f"  tools: {[t['name'] for t in cap['tools']]}")
            result = await call_webmcp_tool(page, demo["tool"], demo["args"])
            print(f"  {demo['tool']}: {result}")
            if not result.get("ok"):
                print(f"FAIL: {demo['path']}.{demo['tool']} did not succeed")
                failures += 1

        print("\n--- Real site, no WebMCP -- must report supported=False ---")
        await page.goto("https://example.com", wait_until="domcontentloaded")
        cap = await check_webmcp_capability(page)
        print("capability check on example.com:", cap)
        if cap["supported"]:
            print("FAIL: expected supported=False")
            failures += 1
        else:
            print("OK: correctly reported no WebMCP support")

        await browser.close()

    if failures:
        print(f"\n{failures} check(s) failed")
        sys.exit(1)
    print(f"\nAll {len(DEMO_PAGES)} demo apps + the real-site check passed")


if __name__ == "__main__":
    asyncio.run(main())
