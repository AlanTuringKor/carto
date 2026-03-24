"""Tests for RoleDiffer and role diff models."""

from carto.analysis.role_differ import RoleDiffer
from carto.domain.models import AuthState
from carto.domain.role_diff import (
    DiffEntry,
    RoleDiffInput,
    RoleDiffResult,
    RoleSurfaceDelta,
    VisibilityCategory,
)
from carto.domain.role_surface import RoleSurface


def _make_surface(
    name: str = "admin",
    urls: set[str] | None = None,
    actions: set[str] | None = None,
    forms: set[str] | None = None,
    endpoints: set[str] | None = None,
    clusters: set[str] | None = None,
    auth: AuthState = AuthState.AUTHENTICATED,
) -> RoleSurface:
    return RoleSurface(
        role_name=name,
        run_id=f"run-{name}",
        urls=urls or set(),
        action_labels=actions or set(),
        form_urls=forms or set(),
        api_endpoints=endpoints or set(),
        page_clusters=clusters or set(),
        auth_state=auth,
    )


class TestVisibilityCategory:
    def test_values(self):
        assert len(VisibilityCategory) == 4


class TestDiffEntry:
    def test_basic(self):
        d = DiffEntry(item="/admin", category=VisibilityCategory.ONLY_A)
        assert d.item == "/admin"
        assert d.category == VisibilityCategory.ONLY_A


class TestRoleSurfaceDelta:
    def test_total_differences(self):
        delta = RoleSurfaceDelta(
            url_diff=[
                DiffEntry(item="/admin", category=VisibilityCategory.ONLY_A),
                DiffEntry(item="/home", category=VisibilityCategory.SHARED),
                DiffEntry(item="/guest", category=VisibilityCategory.ONLY_B),
            ],
        )
        # Only non-shared count: /admin + /guest = 2
        assert delta.total_differences == 2

    def test_empty_delta(self):
        delta = RoleSurfaceDelta()
        assert delta.total_differences == 0


class TestRoleDiffer:
    def test_identical_surfaces(self):
        surface = _make_surface(
            urls={"https://example.com", "https://example.com/page"},
            actions={"Dashboard"},
        )
        differ = RoleDiffer()
        input_ = RoleDiffInput(role_a=surface, role_b=surface)
        delta = differ.diff(input_)
        assert delta.total_differences == 0
        assert len([d for d in delta.url_diff if d.category == VisibilityCategory.SHARED]) == 2

    def test_disjoint_surfaces(self):
        a = _make_surface(
            name="admin",
            urls={"https://example.com/admin", "https://example.com/settings"},
            actions={"Users", "Config"},
        )
        b = _make_surface(
            name="viewer",
            urls={"https://example.com/dashboard"},
            actions={"View"},
        )
        differ = RoleDiffer()
        input_ = RoleDiffInput(role_a=a, role_b=b)
        delta = differ.diff(input_)

        only_a_urls = [d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_A]
        only_b_urls = [d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_B]
        shared_urls = [d for d in delta.url_diff if d.category == VisibilityCategory.SHARED]

        assert len(only_a_urls) == 2
        assert len(only_b_urls) == 1
        assert len(shared_urls) == 0

    def test_overlapping_surfaces(self):
        a = _make_surface(
            name="admin",
            urls={"https://example.com", "https://example.com/admin"},
            actions={"Home", "Admin Panel"},
        )
        b = _make_surface(
            name="viewer",
            urls={"https://example.com", "https://example.com/viewer"},
            actions={"Home", "My Profile"},
        )
        differ = RoleDiffer()
        input_ = RoleDiffInput(role_a=a, role_b=b)
        delta = differ.diff(input_)

        # URLs: example.com shared, /admin only_a, /viewer only_b
        shared_urls = [d for d in delta.url_diff if d.category == VisibilityCategory.SHARED]
        only_a_urls = [d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_A]
        only_b_urls = [d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_B]
        assert len(shared_urls) == 1
        assert len(only_a_urls) == 1
        assert len(only_b_urls) == 1

        # Actions: Home shared, Admin Panel only_a, My Profile only_b
        shared_actions = [d for d in delta.action_diff if d.category == VisibilityCategory.SHARED]
        assert len(shared_actions) == 1
        assert shared_actions[0].item == "Home"

    def test_auth_boundary(self):
        a = _make_surface(name="admin", auth=AuthState.AUTHENTICATED)
        b = _make_surface(name="viewer", auth=AuthState.UNKNOWN)
        differ = RoleDiffer()
        input_ = RoleDiffInput(role_a=a, role_b=b)
        delta = differ.diff(input_)
        assert delta.auth_boundary["auth_states_match"] == "False"

    def test_coverage_comparison(self):
        a = _make_surface(name="admin", urls={"u1", "u2", "u3"}, actions={"a1", "a2"})
        b = _make_surface(name="viewer", urls={"u1"}, actions={"a1", "a2", "a3"})
        differ = RoleDiffer()
        input_ = RoleDiffInput(role_a=a, role_b=b)
        delta = differ.diff(input_)
        assert delta.coverage_comparison["role_a_urls"] == 3
        assert delta.coverage_comparison["role_b_urls"] == 1
        assert delta.coverage_comparison["url_overlap"] == 1

    def test_diff_with_result(self):
        a = _make_surface(name="admin", urls={"https://example.com"})
        b = _make_surface(name="viewer", urls={"https://example.com"})
        differ = RoleDiffer()
        input_ = RoleDiffInput(role_a=a, role_b=b)
        result = differ.diff_with_result(input_, "campaign-1")
        assert isinstance(result, RoleDiffResult)
        assert result.campaign_id == "campaign-1"
        assert result.role_a_name == "admin"
        assert result.role_b_name == "viewer"
        assert result.summary is not None
        assert "admin" in result.summary


class TestRoleDiffResult:
    def test_basic(self):
        r = RoleDiffResult(
            campaign_id="c1",
            role_a_name="admin",
            role_b_name="viewer",
            delta=RoleSurfaceDelta(),
        )
        assert r.result_id
        assert r.campaign_id == "c1"

    def test_with_summary(self):
        r = RoleDiffResult(
            campaign_id="c1",
            role_a_name="admin",
            role_b_name="viewer",
            delta=RoleSurfaceDelta(),
            summary="No differences found.",
        )
        assert r.summary == "No differences found."
