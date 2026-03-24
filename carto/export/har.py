"""
HAR (HTTP Archive 1.2) export for Carto.

Builds a HAR file from captured ``PageObservation`` network data with
configurable redaction of auth-sensitive headers, cookies, and bodies.

Usage:
    builder = HarBuilder(config=HarExportConfig())
    builder.add_observation(page_obs)
    builder.export_json("/tmp/carto/run.har")

Redaction policies:
    - ``exclude``:     Remove header/cookie entirely
    - ``redact``:      Replace value with ``[REDACTED]``
    - ``fingerprint``: Replace value with SHA-256 fingerprint
    - ``include``:     Keep raw value (use only when explicitly allowed)
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from carto.domain.observations import NetworkRequest, NetworkResponse, PageObservation
from carto.utils.redaction import is_sensitive_key

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Redaction policy
# ---------------------------------------------------------------------------


class HarRedactionPolicy(StrEnum):
    """How to handle sensitive values in HAR output."""

    EXCLUDE = "exclude"          # omit the header/cookie entirely
    REDACT = "redact"            # replace value with [REDACTED]
    FINGERPRINT = "fingerprint"  # replace value with SHA-256 hash
    INCLUDE = "include"          # keep raw value


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class HarExportConfig(BaseModel):
    """Controls what is redacted in the HAR export."""

    header_policy: HarRedactionPolicy = HarRedactionPolicy.REDACT
    cookie_policy: HarRedactionPolicy = HarRedactionPolicy.REDACT
    body_policy: HarRedactionPolicy = HarRedactionPolicy.EXCLUDE
    sensitive_header_names: set[str] = Field(
        default_factory=lambda: {
            "authorization",
            "cookie",
            "set-cookie",
            "x-csrf-token",
            "x-xsrf-token",
        }
    )
    creator_name: str = "carto"
    creator_version: str = "0.1.0"


# ---------------------------------------------------------------------------
# HarBuilder
# ---------------------------------------------------------------------------


class HarBuilder:
    """
    Builds a HAR 1.2 JSON structure from PageObservation network data.

    Call ``add_observation`` for each page, then ``build()`` or
    ``export_json()`` to produce the HAR output.
    """

    def __init__(self, config: HarExportConfig | None = None) -> None:
        self._config = config or HarExportConfig()
        self._entries: list[dict[str, Any]] = []
        self._pages: list[dict[str, Any]] = []

    def add_observation(self, obs: PageObservation) -> None:
        """Convert a PageObservation's network traffic into HAR entries."""
        # Add page record
        page_id = obs.observation_id
        self._pages.append({
            "startedDateTime": obs.observed_at.isoformat(),
            "id": page_id,
            "title": obs.title or obs.url,
        })

        # Build response lookup: request_id → NetworkResponse
        response_map: dict[str, NetworkResponse] = {}
        for resp in obs.responses:
            response_map[resp.request_id] = resp

        # Convert each request/response pair to a HAR entry
        for req in obs.requests:
            resp = response_map.get(req.request_id)
            entry = self._build_entry(req, resp, page_id)
            self._entries.append(entry)

    def build(self) -> dict[str, Any]:
        """Return the complete HAR 1.2 JSON structure."""
        return {
            "log": {
                "version": "1.2",
                "creator": {
                    "name": self._config.creator_name,
                    "version": self._config.creator_version,
                },
                "pages": self._pages,
                "entries": self._entries,
            }
        }

    def export_json(self, path: str) -> None:
        """Write the HAR to a JSON file."""
        har = self.build()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(har, indent=2, default=str))
        logger.info("har.exported", path=path, entries=len(self._entries))

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_entry(
        self,
        req: NetworkRequest,
        resp: NetworkResponse | None,
        page_id: str,
    ) -> dict[str, Any]:
        """Build a single HAR entry from a request/response pair."""
        entry: dict[str, Any] = {
            "pageref": page_id,
            "startedDateTime": req.timestamp.isoformat(),
            "time": 0,
            "request": {
                "method": req.method,
                "url": req.url,
                "httpVersion": "HTTP/1.1",
                "headers": self._apply_header_redaction(req.headers),
                "queryString": [],
                "cookies": [],
                "headersSize": -1,
                "bodySize": len(req.post_data) if req.post_data else 0,
            },
            "response": self._build_response_entry(resp),
            "cache": {},
            "timings": {"send": 0, "wait": 0, "receive": 0},
        }

        # Add post data if present
        if req.post_data:
            entry["request"]["postData"] = self._apply_body_redaction(
                req.post_data
            )

        # Redact cookies from Cookie header → structured cookies list
        cookie_header = req.headers.get("cookie") or req.headers.get("Cookie")
        if cookie_header:
            entry["request"]["cookies"] = self._parse_and_redact_cookies(
                cookie_header
            )

        return entry

    def _build_response_entry(
        self, resp: NetworkResponse | None
    ) -> dict[str, Any]:
        if resp is None:
            return {
                "status": 0,
                "statusText": "",
                "httpVersion": "HTTP/1.1",
                "headers": [],
                "cookies": [],
                "content": {"size": 0, "mimeType": ""},
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": 0,
            }

        result: dict[str, Any] = {
            "status": resp.status,
            "statusText": "",
            "httpVersion": "HTTP/1.1",
            "headers": self._apply_header_redaction(resp.headers),
            "cookies": [],
            "content": {"size": 0, "mimeType": ""},
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": 0,
        }

        # Extract Set-Cookie from response headers
        set_cookie = resp.headers.get("set-cookie") or resp.headers.get("Set-Cookie")
        if set_cookie:
            result["cookies"] = self._parse_and_redact_set_cookies(set_cookie)

        return result

    def _apply_header_redaction(
        self, headers: dict[str, str]
    ) -> list[dict[str, str]]:
        """Apply redaction policy to request/response headers."""
        result: list[dict[str, str]] = []
        for name, value in headers.items():
            lower_name = name.lower()
            is_sensitive = (
                lower_name in self._config.sensitive_header_names
                or is_sensitive_key(name)
            )

            if is_sensitive:
                match self._config.header_policy:
                    case HarRedactionPolicy.EXCLUDE:
                        continue
                    case HarRedactionPolicy.REDACT:
                        result.append({"name": name, "value": "[REDACTED]"})
                    case HarRedactionPolicy.FINGERPRINT:
                        fp = hashlib.sha256(value.encode()).hexdigest()[:16]
                        result.append({"name": name, "value": f"[FP:{fp}]"})
                    case HarRedactionPolicy.INCLUDE:
                        result.append({"name": name, "value": value})
            else:
                result.append({"name": name, "value": value})

        return result

    def _parse_and_redact_cookies(
        self, cookie_header: str
    ) -> list[dict[str, str]]:
        """Parse a Cookie header and apply cookie redaction policy."""
        cookies: list[dict[str, str]] = []
        for pair in cookie_header.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            cookies.append({
                "name": name.strip(),
                "value": self._redact_cookie_value(value.strip()),
            })
        return cookies

    def _parse_and_redact_set_cookies(
        self, set_cookie_header: str
    ) -> list[dict[str, str]]:
        """Parse Set-Cookie header(s) and apply cookie redaction policy."""
        cookies: list[dict[str, str]] = []
        # Simple split — doesn't handle all edge cases but covers common ones
        for part in set_cookie_header.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            name, _, rest = part.partition("=")
            value = rest.split(";")[0].strip()
            cookies.append({
                "name": name.strip(),
                "value": self._redact_cookie_value(value),
            })
        return cookies

    def _redact_cookie_value(self, value: str) -> str:
        """Apply cookie redaction policy to a single value."""
        match self._config.cookie_policy:
            case HarRedactionPolicy.EXCLUDE:
                return ""
            case HarRedactionPolicy.REDACT:
                return "[REDACTED]"
            case HarRedactionPolicy.FINGERPRINT:
                fp = hashlib.sha256(value.encode()).hexdigest()[:16]
                return f"[FP:{fp}]"
            case HarRedactionPolicy.INCLUDE:
                return value

    def _apply_body_redaction(self, body: str) -> dict[str, str]:
        """Apply body redaction policy to POST data."""
        match self._config.body_policy:
            case HarRedactionPolicy.EXCLUDE:
                return {"mimeType": "application/x-www-form-urlencoded", "text": "[EXCLUDED]"}
            case HarRedactionPolicy.REDACT:
                return {"mimeType": "application/x-www-form-urlencoded", "text": "[REDACTED]"}
            case HarRedactionPolicy.FINGERPRINT:
                fp = hashlib.sha256(body.encode()).hexdigest()[:16]
                return {"mimeType": "application/x-www-form-urlencoded", "text": f"[FP:{fp}]"}
            case HarRedactionPolicy.INCLUDE:
                return {"mimeType": "application/x-www-form-urlencoded", "text": body}
