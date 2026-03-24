"""Tests for RoleSurface model."""

from carto.domain.models import AuthState
from carto.domain.role_surface import RoleSurface


class TestRoleSurface:
    def test_basic_construction(self):
        s = RoleSurface(role_name="admin", run_id="r1")
        assert s.surface_id
        assert s.role_name == "admin"
        assert s.urls == set()
        assert s.auth_state == AuthState.UNKNOWN

    def test_with_data(self):
        s = RoleSurface(
            role_name="admin",
            run_id="r1",
            urls={"https://example.com", "https://example.com/admin"},
            action_labels={"Dashboard", "Settings", "Users"},
            form_urls={"https://example.com/login"},
            api_endpoints={"/api/users", "/api/settings"},
            page_clusters={"login", "admin", "settings"},
            auth_state=AuthState.AUTHENTICATED,
            risk_signal_count=2,
            step_count=15,
        )
        assert len(s.urls) == 2
        assert len(s.action_labels) == 3
        assert len(s.api_endpoints) == 2
        assert s.auth_state == AuthState.AUTHENTICATED

    def test_serialization(self):
        s = RoleSurface(
            role_name="viewer",
            run_id="r2",
            urls={"https://example.com"},
        )
        data = s.model_dump(mode="json")
        assert isinstance(data["urls"], list)  # sets serialised as lists
        assert "https://example.com" in data["urls"]

    def test_deserialization(self):
        data = {
            "role_name": "editor",
            "run_id": "r3",
            "urls": ["https://example.com"],
            "action_labels": ["Edit", "Save"],
        }
        s = RoleSurface.model_validate(data)
        assert s.role_name == "editor"
        assert "https://example.com" in s.urls
        assert "Edit" in s.action_labels
