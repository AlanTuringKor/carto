"""Tests for CampaignRunner._build_surface (unit tests without browser)."""

from carto.domain.events import (
    EventKind,
    decision_made_event,
    inference_produced_event,
    page_observed_event,
)
from carto.orchestrator.campaign_runner import CampaignRunner
from carto.storage.event_log import InMemoryEventLog


class TestBuildSurface:
    def test_empty_log_produces_empty_surface(self):
        log = InMemoryEventLog()
        surface = CampaignRunner._build_surface("admin", "r1", log)
        assert surface.role_name == "admin"
        assert surface.run_id == "r1"
        assert surface.urls == set()

    def test_extracts_urls_from_observations(self):
        log = InMemoryEventLog()
        log.emit(page_observed_event(
            "r1", 1, "o1", "https://example.com", "Home", 200, 5, 0,
        ))
        log.emit(page_observed_event(
            "r1", 2, "o2", "https://example.com/admin", "Admin", 200, 3, 2,
        ))

        surface = CampaignRunner._build_surface("admin", "r1", log)
        assert surface.urls == {"https://example.com", "https://example.com/admin"}

    def test_extracts_form_urls(self):
        log = InMemoryEventLog()
        log.emit(page_observed_event(
            "r1", 1, "o1", "https://example.com/login", "Login", 200, 2, 1,
        ))
        log.emit(page_observed_event(
            "r1", 2, "o2", "https://example.com/home", "Home", 200, 5, 0,
        ))

        surface = CampaignRunner._build_surface("admin", "r1", log)
        assert "https://example.com/login" in surface.form_urls
        assert "https://example.com/home" not in surface.form_urls

    def test_extracts_action_labels_from_decisions(self):
        log = InMemoryEventLog()
        log.emit(decision_made_event(
            "r1", 1, "click", "Dashboard", "explore dashboard",
        ))
        log.emit(decision_made_event(
            "r1", 2, "click", "Settings", "check settings",
        ))

        surface = CampaignRunner._build_surface("admin", "r1", log)
        assert surface.action_labels == {"Dashboard", "Settings"}

    def test_extracts_page_clusters_from_inferences(self):
        log = InMemoryEventLog()
        log.emit(inference_produced_event(
            "r1", 1, "action_inventory", "page_agent", "i1",
            summary={"page_cluster": "login"},
        ))
        log.emit(inference_produced_event(
            "r1", 2, "action_inventory", "page_agent", "i2",
            summary={"page_cluster": "admin"},
        ))

        surface = CampaignRunner._build_surface("admin", "r1", log)
        assert surface.page_clusters == {"login", "admin"}

    def test_ignores_events_from_other_runs(self):
        log = InMemoryEventLog()
        log.emit(page_observed_event(
            "r1", 1, "o1", "https://example.com", "Home", 200, 5, 0,
        ))
        log.emit(page_observed_event(
            "r2", 1, "o2", "https://other.com", "Other", 200, 3, 0,
        ))

        surface = CampaignRunner._build_surface("admin", "r1", log)
        assert len(surface.urls) == 1
        assert "https://example.com" in surface.urls
