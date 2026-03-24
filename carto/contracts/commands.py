"""
Command models for the Browser Executor.

Commands are the *only* way for the orchestrator to instruct the executor
to perform side effects.  Every command is a typed Pydantic model — the
executor never receives raw strings or dicts.

The ``Command`` union at the bottom is used in type annotations and
pattern-matched inside ``BrowserExecutor.execute``.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Command kinds
# ---------------------------------------------------------------------------


class CommandKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    SCREENSHOT = "screenshot"
    WAIT = "wait"
    SCROLL = "scroll"
    BACK = "back"
    EVALUATE = "evaluate"


# ---------------------------------------------------------------------------
# Base command
# ---------------------------------------------------------------------------


class BaseCommand(BaseModel):
    """Common fields for all commands."""

    command_id: str = Field(default_factory=_uuid)
    kind: CommandKind
    timeout_ms: int = 30_000  # default 30 s per action


# ---------------------------------------------------------------------------
# Concrete commands
# ---------------------------------------------------------------------------


class NavigateCommand(BaseCommand):
    """Navigate the browser to a URL."""

    kind: CommandKind = CommandKind.NAVIGATE
    url: str
    wait_until: str = "networkidle"  # Playwright wait_until value


class ClickCommand(BaseCommand):
    """Click a DOM element identified by a CSS selector."""

    kind: CommandKind = CommandKind.CLICK
    css_selector: str
    wait_for_navigation: bool = False


class FillCommand(BaseCommand):
    """Fill a form field identified by a CSS selector."""

    kind: CommandKind = CommandKind.FILL
    css_selector: str
    value: str
    press_enter: bool = False   # submit via Enter after fill


class SelectCommand(BaseCommand):
    """Select an option in a <select> element."""

    kind: CommandKind = CommandKind.SELECT
    css_selector: str
    value: str                  # the option value attribute


class ScreenshotCommand(BaseCommand):
    """Capture a screenshot of the current page."""

    kind: CommandKind = CommandKind.SCREENSHOT
    full_page: bool = True
    path: str | None = None     # None → auto-generated path


class WaitCommand(BaseCommand):
    """Wait for a fixed duration or a CSS selector to appear."""

    kind: CommandKind = CommandKind.WAIT
    duration_ms: int | None = None
    css_selector: str | None = None   # wait for element to appear


class ScrollCommand(BaseCommand):
    """Scroll the page by a given amount or to an element."""

    kind: CommandKind = CommandKind.SCROLL
    x: int = 0
    y: int = 500
    css_selector: str | None = None   # scroll element into view


class BackCommand(BaseCommand):
    """Navigate back in browser history."""

    kind: CommandKind = CommandKind.BACK


class EvaluateCommand(BaseCommand):
    """
    Evaluate a JavaScript expression in the page context.

    Use sparingly — prefer explicit commands.  Useful for reading
    localStorage / sessionStorage or triggering actions that have
    no DOM-accessible anchor.
    """

    kind: CommandKind = CommandKind.EVALUATE
    expression: str


# ---------------------------------------------------------------------------
# Union type — used in executor signatures and pattern-match dispatch
# ---------------------------------------------------------------------------

Command = Annotated[
    NavigateCommand | ClickCommand | FillCommand | SelectCommand | ScreenshotCommand | WaitCommand | ScrollCommand | BackCommand | EvaluateCommand,
    Field(discriminator="kind"),
]
