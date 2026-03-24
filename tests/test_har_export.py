"""Tests for HAR export."""

import json
import os
import tempfile
from datetime import UTC, datetime

from carto.domain.observations import (
    NetworkRequest,
    NetworkResponse,
    ObservationKind,
    PageObservation,
)
from carto.export.har import HarBuilder, HarExportConfig, HarRedactionPolicy


def _make_observation(
    cookies: dict[str, str] | None = None,
    requests: list[NetworkRequest] | None = None,
    responses: list[NetworkResponse] | None = None,
) -> PageObservation:
    obs_id = "obs-1"
    return PageObservation(
        observation_id=obs_id,
        kind=ObservationKind.PAGE,
        run_id="r1",
        triggering_action_id="cmd-1",
        url="https://example.com",
        final_url="https://example.com",
        title="Example",
        status_code=200,
        cookies=cookies or {},
        requests=requests or [],
        responses=responses or [],
    )


def _make_request(
    url: str = "https://example.com",
    headers: dict[str, str] | None = None,
    post_data: str | None = None,
) -> NetworkRequest:
    return NetworkRequest(
        request_id="req-1",
        observation_id="obs-1",
        url=url,
        method="GET",
        headers=headers or {},
        post_data=post_data,
    )


def _make_response(
    request_id: str = "req-1",
    headers: dict[str, str] | None = None,
) -> NetworkResponse:
    return NetworkResponse(
        request_id=request_id,
        observation_id="obs-1",
        url="https://example.com",
        status=200,
        headers=headers or {},
    )


class TestHarBuilder:
    def test_empty_build(self):
        builder = HarBuilder()
        har = builder.build()
        assert har["log"]["version"] == "1.2"
        assert har["log"]["entries"] == []
        assert builder.entry_count == 0

    def test_add_observation(self):
        req = _make_request()
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder()
        builder.add_observation(obs)

        har = builder.build()
        assert len(har["log"]["entries"]) == 1
        assert har["log"]["entries"][0]["request"]["url"] == "https://example.com"
        assert builder.entry_count == 1

    def test_page_added(self):
        obs = _make_observation()
        builder = HarBuilder()
        builder.add_observation(obs)
        har = builder.build()
        assert len(har["log"]["pages"]) == 1
        assert har["log"]["pages"][0]["title"] == "Example"


class TestHarRedactionExclude:
    def test_sensitive_header_excluded(self):
        config = HarExportConfig(header_policy=HarRedactionPolicy.EXCLUDE)
        req = _make_request(headers={"authorization": "Bearer tok123", "accept": "text/html"})
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder(config=config)
        builder.add_observation(obs)

        har = builder.build()
        entry = har["log"]["entries"][0]
        header_names = [h["name"] for h in entry["request"]["headers"]]
        assert "authorization" not in header_names
        assert "accept" in header_names


class TestHarRedactionRedact:
    def test_sensitive_header_redacted(self):
        config = HarExportConfig(header_policy=HarRedactionPolicy.REDACT)
        req = _make_request(headers={"authorization": "Bearer tok123"})
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder(config=config)
        builder.add_observation(obs)

        har = builder.build()
        entry = har["log"]["entries"][0]
        auth_header = next(
            h for h in entry["request"]["headers"] if h["name"] == "authorization"
        )
        assert auth_header["value"] == "[REDACTED]"


class TestHarRedactionFingerprint:
    def test_sensitive_header_fingerprinted(self):
        config = HarExportConfig(header_policy=HarRedactionPolicy.FINGERPRINT)
        req = _make_request(headers={"authorization": "Bearer tok123"})
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder(config=config)
        builder.add_observation(obs)

        har = builder.build()
        entry = har["log"]["entries"][0]
        auth_header = next(
            h for h in entry["request"]["headers"] if h["name"] == "authorization"
        )
        assert auth_header["value"].startswith("[FP:")


class TestHarRedactionInclude:
    def test_sensitive_header_included(self):
        config = HarExportConfig(header_policy=HarRedactionPolicy.INCLUDE)
        req = _make_request(headers={"authorization": "Bearer tok123"})
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder(config=config)
        builder.add_observation(obs)

        har = builder.build()
        entry = har["log"]["entries"][0]
        auth_header = next(
            h for h in entry["request"]["headers"] if h["name"] == "authorization"
        )
        assert auth_header["value"] == "Bearer tok123"


class TestHarCookieRedaction:
    def test_cookies_redacted_in_header(self):
        config = HarExportConfig(cookie_policy=HarRedactionPolicy.REDACT)
        req = _make_request(headers={"cookie": "session=abc123; theme=dark"})
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder(config=config)
        builder.add_observation(obs)

        har = builder.build()
        cookies = har["log"]["entries"][0]["request"]["cookies"]
        assert len(cookies) == 2
        assert all(c["value"] == "[REDACTED]" for c in cookies)


class TestHarBodyRedaction:
    def test_post_data_excluded(self):
        config = HarExportConfig(body_policy=HarRedactionPolicy.EXCLUDE)
        req = _make_request(post_data="username=admin&password=secret")
        resp = _make_response()
        obs = _make_observation(requests=[req], responses=[resp])

        builder = HarBuilder(config=config)
        builder.add_observation(obs)

        har = builder.build()
        post = har["log"]["entries"][0]["request"]["postData"]
        assert post["text"] == "[EXCLUDED]"


class TestHarExportJson:
    def test_export_to_file(self):
        obs = _make_observation(
            requests=[_make_request()],
            responses=[_make_response()],
        )
        builder = HarBuilder()
        builder.add_observation(obs)

        with tempfile.NamedTemporaryFile(suffix=".har", delete=False) as f:
            path = f.name

        try:
            builder.export_json(path)
            data = json.loads(open(path).read())
            assert data["log"]["version"] == "1.2"
            assert len(data["log"]["entries"]) == 1
        finally:
            os.unlink(path)
