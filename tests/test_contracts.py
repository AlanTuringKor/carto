"""Tests for MessageEnvelope and Command union."""

from __future__ import annotations

from carto.contracts.commands import (
    BackCommand,
    ClickCommand,
    CommandKind,
    EvaluateCommand,
    FillCommand,
    NavigateCommand,
    ScreenshotCommand,
    ScrollCommand,
    SelectCommand,
    WaitCommand,
)
from carto.contracts.envelope import MessageEnvelope
from carto.domain.models import Session


class TestMessageEnvelope:
    def test_basic_creation(self) -> None:
        session = Session(target_url="https://example.com")
        env = MessageEnvelope[Session](
            source="orchestrator",
            target="page_agent",
            correlation_id="run-1",
            payload=session,
        )
        assert env.source == "orchestrator"
        assert env.target == "page_agent"
        assert env.schema_version == "1.0"
        assert env.payload.target_url == "https://example.com"

    def test_json_roundtrip(self) -> None:
        session = Session(target_url="https://example.com")
        env = MessageEnvelope[Session](
            source="a",
            target="b",
            correlation_id="corr-1",
            payload=session,
        )
        json_str = env.model_dump_json()
        env2 = MessageEnvelope[Session].model_validate_json(json_str)
        assert env2.envelope_id == env.envelope_id
        assert env2.payload.target_url == "https://example.com"

    def test_envelope_ids_are_unique(self) -> None:
        session = Session(target_url="https://example.com")
        env1 = MessageEnvelope[Session](
            source="a", target="b", correlation_id="c", payload=session
        )
        env2 = MessageEnvelope[Session](
            source="a", target="b", correlation_id="c", payload=session
        )
        assert env1.envelope_id != env2.envelope_id


class TestCommands:
    def test_navigate_command(self) -> None:
        cmd = NavigateCommand(url="https://example.com")
        assert cmd.kind == CommandKind.NAVIGATE
        assert cmd.wait_until == "networkidle"
        assert cmd.timeout_ms == 30_000

    def test_click_command(self) -> None:
        cmd = ClickCommand(css_selector="button[type='submit']")
        assert cmd.kind == CommandKind.CLICK
        assert not cmd.wait_for_navigation

    def test_fill_command(self) -> None:
        cmd = FillCommand(css_selector="input#username", value="admin")
        assert cmd.kind == CommandKind.FILL
        assert cmd.value == "admin"

    def test_select_command(self) -> None:
        cmd = SelectCommand(css_selector="select#role", value="admin")
        assert cmd.kind == CommandKind.SELECT

    def test_screenshot_command(self) -> None:
        cmd = ScreenshotCommand()
        assert cmd.full_page is True
        assert cmd.path is None

    def test_wait_with_selector(self) -> None:
        cmd = WaitCommand(css_selector=".loaded")
        assert cmd.css_selector == ".loaded"

    def test_wait_with_duration(self) -> None:
        cmd = WaitCommand(duration_ms=500)
        assert cmd.duration_ms == 500

    def test_scroll_command(self) -> None:
        cmd = ScrollCommand(y=1000)
        assert cmd.y == 1000

    def test_back_command(self) -> None:
        cmd = BackCommand()
        assert cmd.kind == CommandKind.BACK

    def test_evaluate_command(self) -> None:
        cmd = EvaluateCommand(expression="document.title")
        assert cmd.expression == "document.title"

    def test_command_ids_are_unique(self) -> None:
        cmd1 = NavigateCommand(url="https://a.com")
        cmd2 = NavigateCommand(url="https://a.com")
        assert cmd1.command_id != cmd2.command_id
