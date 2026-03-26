"""
BrowserExecutor — Playwright-backed implementation of BaseExecutor.

This is the only component in Carto that drives a real browser.
It translates typed Command objects into Playwright API calls and
returns typed Observation objects.

Architecture notes:
- A single persistent browser context is used per executor instance.
- Network traffic is intercepted via Playwright's request/response events
  and stored in a temporary buffer that is flushed into each PageObservation.
- Screenshots are saved to an artefact directory and referenced by path.
- The executor does NOT parse the DOM into high-level models — that is
  the PageUnderstandingAgent's job.  The executor returns raw HTML,
  accessible text, and a snapshot of interactive elements.

Usage:
    async with BrowserExecutor(config) as executor:
        obs = await executor.execute(NavigateCommand(url="https://example.com"))
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Request,
    Response,
    async_playwright,
)
from pydantic import BaseModel

from carto.contracts.commands import (
    BackCommand,
    ClickCommand,
    Command,
    CommandKind,
    EvaluateCommand,
    FillCommand,
    NavigateCommand,
    ScreenshotCommand,
    ScrollCommand,
    SelectCommand,
    WaitCommand,
)
from carto.domain.observations import (
    ElementSnapshot,
    ErrorObservation,
    FormSnapshot,
    NetworkRequest,
    NetworkResponse,
    Observation,
    ObservationKind,
    PageObservation,
)
from carto.executor.base import BaseExecutor, ExecutorError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class BrowserExecutorConfig(BaseModel):
    """Runtime configuration for BrowserExecutor."""

    headless: bool = True
    slow_mo_ms: int = 0
    viewport_width: int = 1280
    viewport_height: int = 900
    default_timeout_ms: int = 30_000
    screenshot_dir: str = "/tmp/carto/screenshots"
    capture_network: bool = True
    capture_html: bool = True
    capture_accessible_text: bool = True
    user_agent: str | None = None
    extra_http_headers: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Network buffer — collects requests/responses between actions
# ---------------------------------------------------------------------------


class _NetworkBuffer:
    def __init__(self, observation_id: str) -> None:
        self.observation_id = observation_id
        self.requests: list[NetworkRequest] = []
        self.responses: list[NetworkResponse] = []
        self._req_map: dict[str, str] = {}  # playwright request id → our request_id

    def on_request(self, request: Request) -> None:
        req_id = str(uuid.uuid4())
        self._req_map[id(request)] = req_id
        self.requests.append(
            NetworkRequest(
                request_id=req_id,
                observation_id=self.observation_id,
                url=request.url,
                method=request.method,
                headers=dict(request.headers),
                post_data=request.post_data,
                resource_type=request.resource_type,
            )
        )

    def on_response(self, response: Response) -> None:
        req_id = self._req_map.get(id(response.request), "unknown")
        self.responses.append(
            NetworkResponse(
                request_id=req_id,
                observation_id=self.observation_id,
                url=response.url,
                status=response.status,
                headers=dict(response.headers),
            )
        )


# ---------------------------------------------------------------------------
# BrowserExecutor
# ---------------------------------------------------------------------------


class BrowserExecutor(BaseExecutor):
    """
    Playwright-backed browser executor.

    Lifecycle:
        Use as an async context manager (``async with BrowserExecutor(config)``
        as executor) or call ``start()`` / ``stop()`` explicitly.
    """

    def __init__(self, config: BrowserExecutorConfig | None = None) -> None:
        self._config = config or BrowserExecutorConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._run_id: str = "unset"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch Playwright, browser, and a fresh browser context."""
        logger.info("executor.start", headless=self._config.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.headless,
            slow_mo=self._config.slow_mo_ms,
        )
        context_opts: dict[str, Any] = {
            "viewport": {
                "width": self._config.viewport_width,
                "height": self._config.viewport_height,
            },
        }
        if self._config.user_agent:
            context_opts["user_agent"] = self._config.user_agent
        if self._config.extra_http_headers:
            context_opts["extra_http_headers"] = self._config.extra_http_headers

        self._context = await self._browser.new_context(**context_opts)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self._config.default_timeout_ms)
        logger.info("executor.ready")

    async def stop(self) -> None:
        """Close browser and Playwright."""
        logger.info("executor.stop")
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def set_run_id(self, run_id: str) -> None:
        """Associate this executor with a Run for observation tagging."""
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    async def execute(self, command: Command) -> Observation:
        """Dispatch a Command to the appropriate handler."""
        if self._page is None:
            raise ExecutorError(command.command_id, "Executor not started.")

        logger.info(
            "executor.execute",
            kind=command.kind,
            command_id=command.command_id,
        )

        try:
            match command.kind:
                case CommandKind.NAVIGATE:
                    assert isinstance(command, NavigateCommand)
                    return await self._handle_navigate(command)
                case CommandKind.CLICK:
                    assert isinstance(command, ClickCommand)
                    return await self._handle_click(command)
                case CommandKind.FILL:
                    assert isinstance(command, FillCommand)
                    return await self._handle_fill(command)
                case CommandKind.SELECT:
                    assert isinstance(command, SelectCommand)
                    return await self._handle_select(command)
                case CommandKind.SCREENSHOT:
                    assert isinstance(command, ScreenshotCommand)
                    return await self._handle_screenshot(command)
                case CommandKind.WAIT:
                    assert isinstance(command, WaitCommand)
                    return await self._handle_wait(command)
                case CommandKind.SCROLL:
                    assert isinstance(command, ScrollCommand)
                    return await self._handle_scroll(command)
                case CommandKind.BACK:
                    assert isinstance(command, BackCommand)
                    return await self._handle_back(command)
                case CommandKind.EVALUATE:
                    assert isinstance(command, EvaluateCommand)
                    return await self._handle_evaluate(command)
                case _:
                    raise ExecutorError(
                        command.command_id,
                        f"Unknown command kind: {command.kind}",
                    )
        except ExecutorError:
            raise
        except Exception as exc:
            logger.exception("executor.error", command_id=command.command_id)
            return ErrorObservation(
                kind=ObservationKind.ERROR,
                run_id=self._run_id,
                triggering_action_id=command.command_id,
                error_type=type(exc).__name__,
                message=str(exc),
            )

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_navigate(self, command: NavigateCommand) -> PageObservation:
        assert self._page is not None
        observation_id = str(uuid.uuid4())
        buffer = _NetworkBuffer(observation_id)

        if self._config.capture_network:
            self._page.on("request", buffer.on_request)
            self._page.on("response", buffer.on_response)

        try:
            response = await self._page.goto(
                command.url,
                timeout=command.timeout_ms,
                wait_until=command.wait_until,  # type: ignore[arg-type]
            )
            status_code = response.status if response else None
        finally:
            if self._config.capture_network:
                self._page.remove_listener("request", buffer.on_request)
                self._page.remove_listener("response", buffer.on_response)

        return await self._build_page_observation(
            observation_id=observation_id,
            command_id=command.command_id,
            buffer=buffer,
            status_code=status_code,
        )

    async def _handle_click(self, command: ClickCommand) -> PageObservation:
        assert self._page is not None
        observation_id = str(uuid.uuid4())
        buffer = _NetworkBuffer(observation_id)

        if self._config.capture_network:
            self._page.on("request", buffer.on_request)
            self._page.on("response", buffer.on_response)

        try:
            if command.wait_for_navigation:
                async with self._page.expect_navigation(timeout=command.timeout_ms):
                    await self._page.click(command.css_selector, timeout=command.timeout_ms)
            else:
                await self._page.click(command.css_selector, timeout=command.timeout_ms)
        finally:
            if self._config.capture_network:
                self._page.remove_listener("request", buffer.on_request)
                self._page.remove_listener("response", buffer.on_response)

        return await self._build_page_observation(
            observation_id=observation_id,
            command_id=command.command_id,
            buffer=buffer,
        )

    async def _handle_fill(self, command: FillCommand) -> PageObservation:
        assert self._page is not None
        try:
            await self._page.fill(
                command.css_selector,
                command.value,
                timeout=command.timeout_ms,
            )
        except Exception as exc:
            if "checkbox" in str(exc).lower() or "radio" in str(exc).lower():
                locator = self._page.locator(command.css_selector).first
                if command.value.lower() in ("true", "1", "yes", "on", "checked"):
                    await locator.check(timeout=command.timeout_ms)
                else:
                    await locator.uncheck(timeout=command.timeout_ms)
            else:
                raise
        if command.press_enter:
            await self._page.press(command.css_selector, "Enter")

        return await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )

    async def _handle_select(self, command: SelectCommand) -> PageObservation:
        assert self._page is not None
        await self._page.select_option(
            command.css_selector,
            value=command.value,
            timeout=command.timeout_ms,
        )
        return await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )

    async def _handle_screenshot(self, command: ScreenshotCommand) -> PageObservation:
        assert self._page is not None
        path = command.path or self._screenshot_path()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=path, full_page=command.full_page)
        logger.info("executor.screenshot", path=path)

        obs = await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )
        obs.screenshot_path = path
        return obs

    async def _handle_wait(self, command: WaitCommand) -> PageObservation:
        assert self._page is not None
        if command.css_selector:
            await self._page.wait_for_selector(
                command.css_selector,
                timeout=command.timeout_ms,
            )
        elif command.duration_ms:
            await self._page.wait_for_timeout(command.duration_ms)

        return await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )

    async def _handle_scroll(self, command: ScrollCommand) -> PageObservation:
        assert self._page is not None
        if command.css_selector:
            await self._page.locator(command.css_selector).scroll_into_view_if_needed()
        else:
            await self._page.evaluate(f"window.scrollBy({command.x}, {command.y})")

        return await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )

    async def _handle_back(self, command: BackCommand) -> PageObservation:
        assert self._page is not None
        await self._page.go_back(timeout=command.timeout_ms)
        return await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )

    async def _handle_evaluate(self, command: EvaluateCommand) -> PageObservation:
        assert self._page is not None
        await self._page.evaluate(command.expression)
        return await self._build_page_observation(
            observation_id=str(uuid.uuid4()),
            command_id=command.command_id,
            buffer=_NetworkBuffer(""),
        )

    # ------------------------------------------------------------------
    # Observation builder
    # ------------------------------------------------------------------

    async def _build_page_observation(
        self,
        observation_id: str,
        command_id: str,
        buffer: _NetworkBuffer,
        status_code: int | None = None,
    ) -> PageObservation:
        """Collect all page data into a PageObservation."""
        assert self._page is not None
        page = self._page

        url = page.url
        title = await page.title()

        html_content: str | None = None
        if self._config.capture_html:
            html_content = await page.content()

        accessible_text: str | None = None
        if self._config.capture_accessible_text:
            accessible_text = await page.evaluate(
                "document.body ? document.body.innerText : ''"
            )

        interactive_elements = await self._extract_interactive_elements(page)
        forms_raw = await self._extract_forms(page)
        cookies = await self._extract_cookies()
        local_storage, session_storage = await self._extract_storage(page)

        return PageObservation(
            observation_id=observation_id,
            kind=ObservationKind.PAGE,
            run_id=self._run_id,
            triggering_action_id=command_id,
            url=url,
            final_url=url,
            title=title,
            status_code=status_code,
            html_content=html_content,
            accessible_text=accessible_text,
            interactive_elements=interactive_elements,
            forms_raw=forms_raw,
            requests=buffer.requests,
            responses=buffer.responses,
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
        )

    async def _extract_interactive_elements(self, page: Page) -> list[ElementSnapshot]:
        """Extract links, buttons, inputs from the live DOM."""
        raw: list[dict[str, Any]] = await page.evaluate("""
            () => {
                const selectors = 'a[href], button, input, select, textarea, [role="button"], [role="link"]';
                return Array.from(document.querySelectorAll(selectors)).slice(0, 200).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.value || el.placeholder || '').slice(0, 200),
                    href: el.href || null,
                    aria_label: el.getAttribute('aria-label'),
                    type: el.getAttribute('type'),
                    name: el.getAttribute('name'),
                    id: el.getAttribute('id'),
                }));
            }
        """)
        return [
            ElementSnapshot(
                tag=el.get("tag", ""),
                text=el.get("text") or None,
                href=el.get("href") or None,
                aria_label=el.get("aria_label") or None,
                attributes={
                    k: v
                    for k in ("type", "name", "id")
                    if (v := el.get(k)) is not None
                },
            )
            for el in raw
        ]

    async def _extract_forms(self, page: Page) -> list[FormSnapshot]:
        """Extract raw form data from the live DOM."""
        raw: list[dict[str, Any]] = await page.evaluate("""
            () => Array.from(document.forms).map(form => ({
                action: form.action || null,
                method: form.method || 'get',
                fields: Array.from(form.elements).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || null,
                    name: el.getAttribute('name') || null,
                    id: el.getAttribute('id') || null,
                    placeholder: el.getAttribute('placeholder') || null,
                    required: el.required || false,
                })),
            }))
        """)
        return [
            FormSnapshot(
                action=f.get("action"),
                method=f.get("method", "get"),
                fields_raw=f.get("fields", []),
            )
            for f in raw
        ]

    async def _extract_cookies(self) -> dict[str, str]:
        if not self._context:
            return {}
        cookies = await self._context.cookies()
        return {c["name"]: c["value"] for c in cookies}

    async def _extract_storage(self, page: Page) -> tuple[dict[str, str], dict[str, str]]:
        try:
            local: dict[str, str] = await page.evaluate(
                "Object.fromEntries(Object.entries(localStorage))"
            )
            session: dict[str, str] = await page.evaluate(
                "Object.fromEntries(Object.entries(sessionStorage))"
            )
        except Exception:
            local, session = {}, {}
        return local, session

    def _screenshot_path(self) -> str:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%f")
        return str(Path(self._config.screenshot_dir) / f"{ts}.png")

    @staticmethod
    def _normalise_url(url: str) -> str:
        """Strip query/fragment for deduplication purposes."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
