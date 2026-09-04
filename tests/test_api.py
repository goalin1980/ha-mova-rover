"""Tests for the deliberately read-only MOVAhome transport."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import aiohttp
import pytest

from custom_components.mova_rover.api import (
    MovaAuthError,
    MovaCloudClient,
    MovaDeviceOfflineError,
    MovaProtocolError,
)


class FakeContent:
    def __init__(self, payload: Any) -> None:
        self._error = payload if isinstance(payload, Exception) else None
        self._body = (
            b""
            if self._error is not None
            else payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode()
        )
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self._error is not None:
            raise self._error
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.content = FakeContent(payload)
        self.content_length = None if isinstance(payload, Exception) else len(self.content._body)

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.responses.popleft()


def login_response() -> FakeResponse:
    return FakeResponse(
        200,
        {
            "access_token": "access-token-value",
            "refresh_token": "refresh-token-value",
            "expires_in": 3600,
        },
    )


@pytest.mark.asyncio
async def test_login_and_shared_device_listing_are_fixed_and_read_only() -> None:
    session = FakeSession(
        login_response(),
        FakeResponse(
            200,
            {
                "code": 0,
                "data": {
                    "page": {
                        "records": [
                            {
                                "did": "secret-did",
                                "model": "mova.swbot.test",
                                "customName": "Pool",
                                "sharedStatus": 1,
                            }
                        ]
                    }
                },
            },
        ),
    )
    client = MovaCloudClient(session, "user@example.com", "plain-password-123", "eu")  # type: ignore[arg-type]

    devices = await client.async_get_devices()

    assert len(devices) == 1
    assert devices[0].model == "mova.swbot.test"
    login_url, login_call = session.calls[0]
    assert login_url == "https://eu.iot.mova-tech.com:13267/dreame-auth/oauth/token"
    assert login_call["allow_redirects"] is False
    assert login_call["headers"]["Dreame-Auth"] == "bearer"
    assert login_call["headers"]["Tenant-Id"] == "000002"
    assert login_call["headers"]["Dreame-Rlc"] == "e5828c1d3144dc8d6815f24fa67a5e3f"
    assert "plain-password-123" not in login_call["data"]
    assert "username=user%40example.com" in login_call["data"]
    list_url, list_call = session.calls[1]
    assert list_url.endswith("/dreame-user-iot/iotuserbind/device/listV2")
    assert list_call["json"]["sharedStatus"] == 1


@pytest.mark.asyncio
async def test_property_call_can_only_emit_get_properties() -> None:
    session = FakeSession(
        login_response(),
        FakeResponse(
            200,
            {
                "code": 0,
                "data": {"result": [{"siid": 2, "piid": 1, "code": 0, "value": 4}]},
            },
        ),
    )
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    result = await client.async_get_properties("secret-did", [(2, 1)])

    assert result[0].value == 4
    _, command_call = session.calls[1]
    body = command_call["json"]
    assert body["data"]["method"] == "get_properties"
    assert body["id"] == body["data"]["id"]
    assert not hasattr(client, "async_set_properties")
    assert not hasattr(client, "async_action")
    assert not hasattr(client, "async_publish")


@pytest.mark.asyncio
async def test_property_batch_limit_is_enforced_before_network() -> None:
    session = FakeSession()
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        await client.async_get_properties("did", [(1, index) for index in range(1, 22)])

    assert session.calls == []


@pytest.mark.asyncio
async def test_oversized_http_response_is_rejected_before_json_parsing() -> None:
    oversized = FakeResponse(200, b"{" + b" " * (5 * 1024 * 1024))
    oversized.content_length = None  # Exercise the streaming bound, not only the header check.
    session = FakeSession(oversized)
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(MovaProtocolError, match="size limit"):
        await client.async_login()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("property_results", "message"),
    (
        (
            [
                {"siid": 2, "piid": 1, "code": 0, "value": 4},
                {"siid": 3, "piid": 1, "code": 0, "value": 80},
            ],
            "more properties than requested",
        ),
        (
            [{"siid": 3, "piid": 1, "code": 0, "value": 80}],
            "property that was not requested",
        ),
    ),
)
async def test_property_results_are_bounded_to_requested_pairs(
    property_results: list[dict[str, Any]], message: str
) -> None:
    session = FakeSession(
        login_response(),
        FakeResponse(200, {"code": 0, "data": {"result": property_results}}),
    )
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(MovaProtocolError, match=message):
        await client.async_get_properties("did", [(2, 1)])


@pytest.mark.asyncio
async def test_transport_rejects_write_or_unknown_requests_before_network() -> None:
    session = FakeSession()
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Only get_properties"):
        await client._async_request_json(  # noqa: SLF001 - verifies the network boundary
            "/dreame-iot-com-20000/device/sendCommand",
            json_body={
                "did": "did",
                "id": 1,
                "data": {
                    "did": "did",
                    "id": 1,
                    "method": "action",
                    "params": {"did": "did", "siid": 2, "aiid": 1, "in": []},
                    "from": "XXXXXX",
                },
            },
        )
    with pytest.raises(ValueError, match="allowlist"):
        await client._async_request_json(  # noqa: SLF001 - verifies the network boundary
            "/dreame-user-iot/iotuserbind/device/unbind",
            json_body={"did": "did"},
        )

    assert session.calls == []


@pytest.mark.asyncio
async def test_authentication_error_has_no_server_body_or_credentials() -> None:
    session = FakeSession(FakeResponse(401, {"error": "password was secret"}))
    client = MovaCloudClient(session, "user@example.com", "very-secret")  # type: ignore[arg-type]

    with pytest.raises(MovaAuthError) as caught:
        await client.async_login()

    message = str(caught.value)
    assert "very-secret" not in message
    assert "user@example.com" not in message
    assert "password was secret" not in message


@pytest.mark.asyncio
async def test_device_offline_code_is_not_treated_as_auth_failure() -> None:
    session = FakeSession(login_response(), FakeResponse(200, {"code": 80001}))
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(MovaDeviceOfflineError):
        await client.async_get_properties("did", [(2, 1)])

    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_missing_cloud_code_fails_closed() -> None:
    session = FakeSession(
        login_response(),
        FakeResponse(200, {"data": {"page": {"records": []}}}),
    )
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(MovaProtocolError, match="no valid cloud code"):
        await client.async_get_devices()


@pytest.mark.asyncio
async def test_failed_forced_reauth_invalidates_rejected_access_token() -> None:
    session = FakeSession(
        FakeResponse(200, {"access_token": "rejected-access-token", "expires_in": 3600}),
        FakeResponse(401, {}),
        FakeResponse(401, {}),
    )
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(MovaAuthError):
        await client.async_get_properties("did", [(2, 1)])

    assert client.authenticated is False
    assert client._access_token is None  # noqa: SLF001 - rejected-token regression guard


@pytest.mark.asyncio
async def test_auth_retry_refreshes_once_and_reuses_the_read_only_request() -> None:
    session = FakeSession(
        login_response(),
        FakeResponse(401, {}),
        FakeResponse(200, {"access_token": "new-access-token", "expires_in": 3600}),
        FakeResponse(200, {"code": 0, "data": {"result": []}}),
    )
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    await client.async_get_properties("did", [(2, 1)])

    assert len(session.calls) == 4
    _, refresh_call = session.calls[2]
    assert "grant_type=refresh_token" in refresh_call["data"]
    assert refresh_call["headers"]["Dreame-Auth"] == "bearer access-token-value"
    _, retried_property_call = session.calls[3]
    assert retried_property_call["json"]["data"]["method"] == "get_properties"


def test_short_positive_token_lifetime_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]
    monkeypatch.setattr("custom_components.mova_rover.api.time.monotonic", lambda: 1000.0)

    client._store_session(  # noqa: SLF001 - token-expiry regression guard
        {"access_token": "short-access-token", "expires_in": 60}
    )

    assert client._token_expires_at == 1054.0  # noqa: SLF001


def test_session_secret_audit_does_not_expose_tokens() -> None:
    session = FakeSession()
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]
    client._access_token = "access-token-that-must-stay-private"  # noqa: SLF001
    client._refresh_token = "refresh-token-that-must-stay-private"  # noqa: SLF001

    client.audit_serialized_session_secrets('{"safe": true}')
    with pytest.raises(ValueError, match="session secret"):
        client.audit_serialized_session_secrets('{"token": "access-token-that-must-stay-private"}')
    client._access_token = "token/with+url=characters"  # noqa: SLF001
    with pytest.raises(ValueError, match="session secret"):
        client.audit_serialized_session_secrets('{"token": "token%2Fwith%2Burl%3Dcharacters"}')

    assert not hasattr(client, "secret_values")


def test_clear_credentials_drops_all_in_memory_secrets() -> None:
    session = FakeSession()
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]
    client._access_token = "access-token"  # noqa: SLF001
    client._refresh_token = "refresh-token"  # noqa: SLF001

    client.clear_credentials()

    assert client._username == ""  # noqa: SLF001
    assert client._password == ""  # noqa: SLF001
    assert client._access_token is None  # noqa: SLF001
    assert client._refresh_token is None  # noqa: SLF001
    assert client.authenticated is False


@pytest.mark.asyncio
async def test_invalid_json_is_protocol_safe() -> None:
    session = FakeSession(FakeResponse(200, b"not-json"))
    client = MovaCloudClient(session, "user@example.com", "password")  # type: ignore[arg-type]

    with pytest.raises(Exception) as caught:
        await client.async_login()

    assert "user@example.com" not in str(caught.value)
    assert not isinstance(caught.value, aiohttp.ClientError)
