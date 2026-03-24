"""
RoleDiffer — deterministic cross-role surface comparison.

Compares two ``RoleSurface`` snapshots and produces a typed
``RoleSurfaceDelta`` classifying every item by ``VisibilityCategory``.

This module is:
- Pure logic — no LLM, no I/O
- Deterministic — same inputs always produce same output
- Set-based — comparisons use set intersection/difference
"""

from __future__ import annotations

import structlog

from carto.domain.role_diff import (
    DiffEntry,
    RoleDiffInput,
    RoleDiffResult,
    RoleSurfaceDelta,
    VisibilityCategory,
)
from carto.domain.role_surface import RoleSurface

logger = structlog.get_logger(__name__)


class RoleDiffer:
    """
    Compares two role surfaces and produces a typed diff.

    All comparisons are set-based.  No LLM calls.
    """

    def diff(self, input: RoleDiffInput) -> RoleSurfaceDelta:
        """Compute the delta between two role surfaces."""
        a = input.role_a
        b = input.role_b

        logger.info(
            "role_differ.start",
            role_a=a.role_name,
            role_b=b.role_name,
            urls_a=len(a.urls),
            urls_b=len(b.urls),
        )

        delta = RoleSurfaceDelta(
            url_diff=self._diff_sets(a.urls, b.urls, "url"),
            action_diff=self._diff_sets(a.action_labels, b.action_labels, "action"),
            form_diff=self._diff_sets(a.form_urls, b.form_urls, "form_url"),
            endpoint_diff=self._diff_sets(a.api_endpoints, b.api_endpoints, "endpoint"),
            cluster_diff=self._diff_sets(a.page_clusters, b.page_clusters, "cluster"),
            auth_boundary=self._diff_auth(a, b),
            coverage_comparison=self._diff_coverage(a, b),
        )

        logger.info(
            "role_differ.complete",
            total_differences=delta.total_differences,
        )

        return delta

    def diff_with_result(
        self,
        input: RoleDiffInput,
        campaign_id: str,
    ) -> RoleDiffResult:
        """Compute diff and wrap in a RoleDiffResult with metadata."""
        delta = self.diff(input)
        summary = self._build_summary(input.role_a, input.role_b, delta)
        return RoleDiffResult(
            campaign_id=campaign_id,
            role_a_name=input.role_a.role_name,
            role_b_name=input.role_b.role_name,
            delta=delta,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Set comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_sets(
        set_a: set[str],
        set_b: set[str],
        item_type: str,
    ) -> list[DiffEntry]:
        """Compare two string sets and return classified diff entries."""
        entries: list[DiffEntry] = []

        # Only in A
        for item in sorted(set_a - set_b):
            entries.append(DiffEntry(
                item=item,
                category=VisibilityCategory.ONLY_A,
                detail=f"{item_type} visible only to role A",
            ))

        # Only in B
        for item in sorted(set_b - set_a):
            entries.append(DiffEntry(
                item=item,
                category=VisibilityCategory.ONLY_B,
                detail=f"{item_type} visible only to role B",
            ))

        # Shared
        for item in sorted(set_a & set_b):
            entries.append(DiffEntry(
                item=item,
                category=VisibilityCategory.SHARED,
            ))

        return entries

    # ------------------------------------------------------------------
    # Auth comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_auth(a: RoleSurface, b: RoleSurface) -> dict[str, str]:
        """Compare auth posture between two roles."""
        result: dict[str, str] = {
            "role_a_auth": a.auth_state,
            "role_b_auth": b.auth_state,
            "auth_states_match": str(a.auth_state == b.auth_state),
        }
        return result

    # ------------------------------------------------------------------
    # Coverage comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_coverage(a: RoleSurface, b: RoleSurface) -> dict[str, int | str]:
        """Compare coverage metrics between two roles."""
        return {
            "role_a_urls": len(a.urls),
            "role_b_urls": len(b.urls),
            "role_a_actions": len(a.action_labels),
            "role_b_actions": len(b.action_labels),
            "role_a_forms": len(a.form_urls),
            "role_b_forms": len(b.form_urls),
            "role_a_endpoints": len(a.api_endpoints),
            "role_b_endpoints": len(b.api_endpoints),
            "role_a_steps": a.step_count,
            "role_b_steps": b.step_count,
            "url_overlap": len(a.urls & b.urls),
            "url_only_a": len(a.urls - b.urls),
            "url_only_b": len(b.urls - a.urls),
        }

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        a: RoleSurface,
        b: RoleSurface,
        delta: RoleSurfaceDelta,
    ) -> str:
        """Generate a human-readable diff summary."""
        only_a_urls = len([d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_A])
        only_b_urls = len([d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_B])
        shared_urls = len([d for d in delta.url_diff if d.category == VisibilityCategory.SHARED])

        parts = [
            f"Compared {a.role_name} vs {b.role_name}.",
            f"URLs: {shared_urls} shared, {only_a_urls} only {a.role_name}, {only_b_urls} only {b.role_name}.",
            f"Total non-shared differences: {delta.total_differences}.",
        ]
        return " ".join(parts)
