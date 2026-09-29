"""
Phase 3: the Agent Controller Layer itself -- BUILD_STEPS.md calls this
"your original contribution," the piece with no reference implementation.

Owns one shared BrowserSession (same pattern Engine 2 uses standalone),
and exposes exactly two entry points for the future Phase 4 agent:

  navigate(url)        -- always goes through Playwright (this is DOM-level
                           browser navigation, needed regardless of which
                           engine ends up handling the page's own tools --
                           see BUILD_STEPS.md's "Handshake" step), then
                           re-runs the Phase 2 capability check and updates
                           which engine governs the next call.
  execute(name, args)  -- dispatches to whichever engine is currently
                           selected for the page, and returns one
                           NormalizedResult either way.

This is deliberately engine-agnostic from the caller's side: Phase 4's
agent will call these two methods without ever checking which engine is
active -- that is the whole point of Phase 3.
"""
from __future__ import annotations

from typing import Any, Optional

from engine_playwright import actions as pw_actions
from engine_playwright.browser_session import BrowserSession
from engine_webmcp.native_bridge import call_webmcp_tool

from .normalizer import normalize_playwright, normalize_webmcp
from .router import select_engine
from .schema import ActionSchema, NormalizedResult, TaskState


class Controller:
    def __init__(self) -> None:
        self._session = BrowserSession()
        self.state = TaskState()
        self._actions: list[ActionSchema] = []

    @property
    def available_actions(self) -> list[ActionSchema]:
        """The action menu for whichever page is currently loaded -- WebMCP
        tool schemas if the last navigate landed on a WebMCP-enabled page,
        or the fixed Playwright action set otherwise."""
        return self._actions

    async def navigate(self, url: str) -> NormalizedResult:
        page = await self._session.get_page()
        try:
            text = await pw_actions.navigate(page, url)
        except Exception as exc:  # noqa: BLE001 -- surfaced via NormalizedResult, never raised to the caller
            result = normalize_playwright(None, error=str(exc))
            self.state.record(result)
            return result

        # Re-run the capability check on every new page (BUILD_STEPS.md
        # Phase 3 step 1) -- never assume the engine chosen for the LAST
        # page still applies to this one.
        engine, actions_menu = await select_engine(page)
        self.state.current_url = url
        self.state.current_engine = engine
        self._actions = actions_menu

        result = normalize_playwright(text)
        self.state.record(result)
        return result

    async def execute(self, name: str, args: Optional[dict[str, Any]] = None) -> NormalizedResult:
        """Runs one action by name against whichever engine is currently
        selected. `name` and `args` should come from `available_actions`."""
        args = args or {}
        page = await self._session.get_page()

        if self.state.current_engine == "webmcp":
            raw = await call_webmcp_tool(page, name, args)
            result = normalize_webmcp(raw)
        else:
            result = await self._execute_playwright(page, name, args)

        self.state.record(result)
        return result

    async def _execute_playwright(self, page, name: str, args: dict[str, Any]) -> NormalizedResult:
        try:
            if name == "click":
                data: Any = await pw_actions.click(page, args["selector"])
            elif name == "type":
                data = await pw_actions.type_text(page, args["selector"], args["text"])
            elif name == "extract_text":
                data = await pw_actions.extract_text(page, args.get("selector"))
            elif name == "screenshot":
                data = await pw_actions.screenshot(page)  # raw PNG bytes
            else:
                return normalize_playwright(None, error=f'Unknown Playwright action "{name}"')
        except Exception as exc:  # noqa: BLE001
            return normalize_playwright(None, error=str(exc))
        return normalize_playwright(data)

    async def close(self) -> None:
        await self._session.close()
