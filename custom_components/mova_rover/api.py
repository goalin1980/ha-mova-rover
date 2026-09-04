"""Minimal read-only client for the MOVAhome cloud API.

The public surface of this module intentionally contains no write command,
action, MQTT publish, pairing, firmware, or account-management method.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, quote_plus, urlencode

import aiohttp

from .models import MovaDevice, MovaProperty

_API_HOSTS = {"eu": "eu.iot.mova-tech.com:13267"}
_PASSWORD_SALT = "RAylYC%fmSKp7%Tq"
_TENANT_ID = "000002"
_AUTHORIZATION = "Basic bW92YV9hcHA6VjdLb0NoTFc4dkhBQ3FHYg=="
_RLC = "e5828c1d3144dc8d6815f24fa67a5e3f"
_USER_AGENT = "Dart/3.2 (dart:io)"
_META = "cv=i_829"
_MAX_PROPERTIES_PER_REQUEST = 20
_MAX_HTTP_RESPONSE_BYTES = 5 * 1024 * 1024
_RESPONSE_READ_CHUNK_BYTES = 64 * 1024
_AUTH_PATH = "/dreame-auth/oauth/token"
_DEVICE_LIST_PATH = "/dreame-user-iot/iotuserbind/device/listV2"
_DEVICE_INFO_PATH = "/dreame-user-iot/iotuserbind/device/info"
_PROPERTY_COMMAND_PATH = "/dreame-iot-com-20000/device/sendCommand"
_READ_ONLY_PATHS = frozenset(
    {_AUTH_PATH, _DEVICE_LIST_PATH, _DEVICE_INFO_PATH, _PROPERTY_COMMAND_PATH}
)


class MovaError(Exception):
    """Base exception for MOVA cloud failures."""


class MovaAuthError(MovaError):
    """Authentication failed or expired."""


class MovaRateLimitError(MovaError):
    """The MOVA cloud rate-limited a request."""


class MovaDeviceOfflineError(MovaError):
    """The device did not answer the cloud relay."""


class MovaTransportError(MovaError):
    """A verified HTTPS request could not be completed."""


class MovaProtocolError(MovaError):
    """The cloud returned an unexpected response."""


def _cloud_code(payload: Mapping[str, Any]) -> int | None:
    value = payload.get("code")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _looks_like_auth_failure(payload: Mapping[str, Any]) -> bool:
    code = _cloud_code(payload)
    if code in {401, 403, 10001, 10002, 10004, 10005}:
        return True
    message = payload.get("msg") or payload.get("message") or ""
    if not isinstance(message, str):
        return False
    lowered = message.casefold()
    return "token" in lowered and any(word in lowered for word in ("invalid", "expire", "auth"))


def _validate_auth_form(form: Mapping[str, str]) -> None:
    """Allow only the two authentication grants needed by this client."""

    grant_type = form.get("grant_type")
    if grant_type == "password":
        expected = {
            "grant_type",
            "scope",
            "platform",
            "type",
            "username",
            "password",
            "country",
            "lang",
        }
    elif grant_type == "refresh_token":
        expected = {"grant_type", "scope", "platform", "refresh_token"}
    else:
        raise ValueError("Unsupported MOVAhome authentication grant")
    if set(form) != expected:
        raise ValueError("Unexpected fields in MOVAhome authentication request")


def _validate_property_command(body: Mapping[str, Any]) -> None:
    """Fail closed unless a command envelope is a bounded property read."""

    if set(body) != {"did", "id", "data"}:
        raise ValueError("Unexpected fields in MOVAhome property request")
    data = body.get("data")
    if not isinstance(data, Mapping) or set(data) != {"did", "id", "method", "params", "from"}:
        raise ValueError("Invalid MOVAhome property request envelope")
    if data.get("method") != "get_properties":
        raise ValueError("Only get_properties is allowed")
    if body.get("did") != data.get("did") or body.get("id") != data.get("id"):
        raise ValueError("MOVAhome property request identifiers do not match")

    params = data.get("params")
    if not isinstance(params, list) or not 1 <= len(params) <= _MAX_PROPERTIES_PER_REQUEST:
        raise ValueError("MOVAhome property request has an invalid batch size")
    for item in params:
        if not isinstance(item, Mapping) or set(item) != {
            "did",
            "siid",
            "piid",
            "code",
            "updateTime",
        }:
            raise ValueError("Invalid MOVAhome property descriptor")
        if item.get("did") != body.get("did"):
            raise ValueError("MOVAhome property descriptor targets another device")
        siid = item.get("siid")
        piid = item.get("piid")
        if (
            isinstance(siid, bool)
            or not isinstance(siid, int)
            or isinstance(piid, bool)
            or not isinstance(piid, int)
            or not 1 <= siid <= 255
            or not 1 <= piid <= 65535
            or item.get("code") != 0
            or item.get("updateTime") != 0
        ):
            raise ValueError("Invalid MOVAhome property descriptor values")


def _validate_read_only_request(
    path: str,
    *,
    form: Mapping[str, str] | None,
    json_body: Mapping[str, Any] | None,
) -> None:
    """Enforce the client's read-only network boundary before any request."""

    if path not in _READ_ONLY_PATHS:
        raise ValueError("MOVA API endpoint is not on the read-only allowlist")
    if path == _AUTH_PATH:
        if form is None or json_body is not None:
            raise ValueError("MOVAhome authentication requires a form body")
        _validate_auth_form(form)
        return
    if form is not None or json_body is None:
        raise ValueError("MOVAhome read endpoint requires a JSON body")
    if path == _PROPERTY_COMMAND_PATH:
        _validate_property_command(json_body)


async def _read_bounded_json_response(response: aiohttp.ClientResponse) -> Mapping[str, Any]:
    """Read one JSON object without allowing an unbounded response body."""

    content_length = response.content_length
    if content_length is not None and content_length > _MAX_HTTP_RESPONSE_BYTES:
        raise MovaProtocolError("MOVAhome response exceeds the size limit")

    body = bytearray()
    while True:
        remaining = _MAX_HTTP_RESPONSE_BYTES - len(body)
        chunk = await response.content.read(min(_RESPONSE_READ_CHUNK_BYTES, remaining + 1))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > _MAX_HTTP_RESPONSE_BYTES:
            raise MovaProtocolError("MOVAhome response exceeds the size limit")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise MovaProtocolError("MOVAhome returned invalid JSON") from err
    if not isinstance(payload, Mapping):
        raise MovaProtocolError("MOVAhome returned a non-object response")
    return payload


class MovaCloudClient:
    """Small async MOVAhome client limited to read-only operations."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        region: str = "eu",
    ) -> None:
        if region not in _API_HOSTS:
            raise ValueError(f"Unsupported MOVA cloud region: {region}")

        self._session = session
        self._username = username
        self._password = password
        self._region = region
        self._base_url = f"https://{_API_HOSTS[region]}"
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at = 0.0
        self._auth_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._request_id = secrets.randbelow(800_000) + 100_000
        self.last_http_status: int | None = None
        self.last_cloud_code: int | None = None

    @property
    def region(self) -> str:
        """Return the fixed cloud region."""

        return self._region

    @property
    def authenticated(self) -> bool:
        """Return whether a non-expired access token is present."""

        return bool(self._access_token and time.monotonic() < self._token_expires_at)

    def _headers(
        self,
        *,
        content_type: str,
        token: str | None = None,
    ) -> dict[str, str]:
        dreame_auth = "bearer"
        if token:
            dreame_auth = token if token.casefold().startswith("bearer ") else f"bearer {token}"
        return {
            "Accept": "application/json",
            "Content-Type": content_type,
            "User-Agent": _USER_AGENT,
            "Dreame-Meta": _META,
            "Dreame-Rlc": _RLC,
            "Tenant-Id": _TENANT_ID,
            "Authorization": _AUTHORIZATION,
            "Dreame-Auth": dreame_auth,
        }

    async def _async_request_json(
        self,
        path: str,
        *,
        form: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        token: str | None = None,
        login_request: bool = False,
    ) -> Mapping[str, Any]:
        if not path.startswith("/") or "://" in path:
            raise ValueError("MOVA API path must be relative to the fixed vendor host")
        if (form is None) == (json_body is None):
            raise ValueError("Exactly one request body must be supplied")
        _validate_read_only_request(path, form=form, json_body=json_body)

        content_type = (
            "application/x-www-form-urlencoded" if form is not None else "application/json"
        )
        request_kwargs: dict[str, Any] = {
            "headers": self._headers(content_type=content_type, token=token),
            "timeout": aiohttp.ClientTimeout(total=20),
            "allow_redirects": False,
        }
        if form is not None:
            request_kwargs["data"] = urlencode(form)
        else:
            request_kwargs["json"] = json_body

        try:
            async with self._session.post(f"{self._base_url}{path}", **request_kwargs) as response:
                self.last_http_status = response.status
                if response.status in {401, 403}:
                    raise MovaAuthError("MOVAhome authentication was rejected")
                if response.status == 429:
                    raise MovaRateLimitError("MOVAhome rate limit reached")
                if response.status < 200 or response.status >= 300:
                    if login_request and response.status in {400, 422}:
                        raise MovaAuthError("MOVAhome credentials were rejected")
                    raise MovaTransportError(
                        f"MOVAhome HTTPS request failed with status {response.status}"
                    )
                payload = await _read_bounded_json_response(response)
        except TimeoutError as err:
            raise MovaTransportError("MOVAhome HTTPS request timed out") from err
        except aiohttp.ClientError as err:
            raise MovaTransportError("MOVAhome verified HTTPS connection failed") from err

        self.last_cloud_code = _cloud_code(payload)
        return payload

    async def _async_password_login(self) -> None:
        password_hash = hashlib.md5(  # noqa: S324 - required by the vendor protocol
            f"{self._password}{_PASSWORD_SALT}".encode()
        ).hexdigest()
        payload = await self._async_request_json(
            _AUTH_PATH,
            form={
                "grant_type": "password",
                "scope": "all",
                "platform": "IOS",
                "type": "account",
                "username": self._username,
                "password": password_hash,
                "country": "DE",
                "lang": "de",
            },
            login_request=True,
        )
        self._store_session(payload)

    async def _async_refresh_login(self, access_token: str | None) -> None:
        if not self._refresh_token:
            raise MovaAuthError("No MOVAhome refresh token available")
        payload = await self._async_request_json(
            _AUTH_PATH,
            form={
                "grant_type": "refresh_token",
                "scope": "all",
                "platform": "IOS",
                "refresh_token": self._refresh_token,
            },
            token=access_token,
            login_request=True,
        )
        self._store_session(payload, keep_refresh_token=True)

    def _store_session(
        self, payload: Mapping[str, Any], *, keep_refresh_token: bool = False
    ) -> None:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise MovaAuthError("MOVAhome did not return an access token")

        refresh_token = payload.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            self._refresh_token = refresh_token
        elif not keep_refresh_token:
            self._refresh_token = None

        try:
            lifetime = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            lifetime = 3600
        if lifetime <= 0:
            lifetime = 3600
        refresh_margin = min(120, lifetime // 10)
        self._access_token = access_token
        self._token_expires_at = time.monotonic() + lifetime - refresh_margin

    async def async_login(self, *, force: bool = False) -> None:
        """Authenticate without ever logging credentials or response bodies."""

        async with self._auth_lock:
            if self.authenticated and not force:
                return

            refresh_access_token = self._access_token
            if force:
                # The caller has evidence that this token was rejected. Invalidate
                # it before attempting either refresh or password authentication so
                # a failed reauthentication can never make it appear usable again.
                self._access_token = None
                self._token_expires_at = 0.0

            if self._refresh_token:
                try:
                    await self._async_refresh_login(refresh_access_token)
                    return
                except (MovaAuthError, MovaProtocolError):
                    self._access_token = None
                    self._refresh_token = None
                    self._token_expires_at = 0.0

            await self._async_password_login()

    async def _async_authenticated_request(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        retry_auth: bool = True,
    ) -> Mapping[str, Any]:
        await self.async_login()
        try:
            payload = await self._async_request_json(path, json_body=body, token=self._access_token)
        except MovaAuthError:
            if not retry_auth:
                raise
            await self.async_login(force=True)
            return await self._async_authenticated_request(path, body, retry_auth=False)

        if _looks_like_auth_failure(payload):
            if not retry_auth:
                raise MovaAuthError("MOVAhome session expired")
            await self.async_login(force=True)
            return await self._async_authenticated_request(path, body, retry_auth=False)
        return payload

    @staticmethod
    def _require_success(payload: Mapping[str, Any]) -> None:
        code = _cloud_code(payload)
        if code in {80001, -8}:
            raise MovaDeviceOfflineError("MOVA device did not answer")
        if code is None:
            raise MovaProtocolError("MOVAhome response has no valid cloud code")
        if code != 0:
            raise MovaProtocolError(f"MOVAhome returned cloud code {code}")

    async def async_get_devices(self) -> list[MovaDevice]:
        """Return owned and shared devices without retaining raw metadata."""

        payload = await self._async_authenticated_request(
            _DEVICE_LIST_PATH,
            {
                "sharedStatus": 1,
                "current": 1,
                "size": 100,
                "lang": "de",
                "timestamp": int(time.time() * 1000),
            },
        )
        self._require_success(payload)

        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise MovaProtocolError("MOVAhome device list has no data object")
        nested = data.get("data")
        if isinstance(nested, Mapping):
            data = nested
        page = data.get("page")
        if not isinstance(page, Mapping) or not isinstance(page.get("records"), list):
            raise MovaProtocolError("MOVAhome device list has no records")

        devices: list[MovaDevice] = []
        for record in page["records"]:
            if not isinstance(record, Mapping):
                continue
            try:
                devices.append(MovaDevice.from_cloud(record))
            except ValueError:
                continue
        return devices

    async def async_get_device_info(self, device_id: str) -> MovaDevice:
        """Return one device descriptor from the fixed read-only info endpoint."""

        payload = await self._async_authenticated_request(_DEVICE_INFO_PATH, {"did": device_id})
        self._require_success(payload)
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise MovaProtocolError("MOVAhome device info has no data object")
        try:
            return MovaDevice.from_cloud(data)
        except ValueError as err:
            raise MovaProtocolError("MOVAhome device info is incomplete") from err

    async def async_get_properties(
        self,
        device_id: str,
        properties: Sequence[tuple[int, int]],
    ) -> list[MovaProperty]:
        """Read at most 20 properties through the fixed EU device relay."""

        if not properties:
            return []
        if len(properties) > _MAX_PROPERTIES_PER_REQUEST:
            raise ValueError(
                f"At most {_MAX_PROPERTIES_PER_REQUEST} properties may be read per request"
            )
        for siid, piid in properties:
            if not (1 <= siid <= 255 and 1 <= piid <= 65535):
                raise ValueError("Property identifiers are outside the allowed range")
        requested_pairs = set(properties)
        if len(requested_pairs) != len(properties):
            raise ValueError("Duplicate property identifiers are not allowed")

        async with self._command_lock:
            request_id = self._request_id
            self._request_id += 1
            params = [
                {
                    "did": device_id,
                    "siid": siid,
                    "piid": piid,
                    "code": 0,
                    "updateTime": 0,
                }
                for siid, piid in properties
            ]
            payload = await self._async_authenticated_request(
                _PROPERTY_COMMAND_PATH,
                {
                    "did": device_id,
                    "id": request_id,
                    "data": {
                        "did": device_id,
                        "id": request_id,
                        "method": "get_properties",
                        "params": params,
                        "from": "XXXXXX",
                    },
                },
            )
        self._require_success(payload)

        data = payload.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as err:
                raise MovaProtocolError("MOVAhome property data is invalid JSON") from err
        if not isinstance(data, Mapping) or not isinstance(data.get("result"), list):
            raise MovaProtocolError("MOVAhome property response has no result list")
        if len(data["result"]) > len(requested_pairs):
            raise MovaProtocolError("MOVAhome returned more properties than requested")

        results: list[MovaProperty] = []
        returned_pairs: set[tuple[int, int]] = set()
        for item in data["result"]:
            if not isinstance(item, Mapping):
                raise MovaProtocolError("MOVAhome returned an invalid property result")
            try:
                siid = int(item["siid"])
                piid = int(item["piid"])
            except (KeyError, TypeError, ValueError) as err:
                raise MovaProtocolError("MOVAhome returned an invalid property identifier") from err
            pair = (siid, piid)
            if pair not in requested_pairs:
                raise MovaProtocolError("MOVAhome returned a property that was not requested")
            if pair in returned_pairs:
                raise MovaProtocolError("MOVAhome returned a duplicate property")
            returned_pairs.add(pair)
            code_value = item.get("code")
            try:
                code = int(code_value) if code_value is not None else None
            except (TypeError, ValueError):
                code = None
            results.append(MovaProperty(siid=siid, piid=piid, code=code, value=item.get("value")))
        return results

    async def async_get_properties_batched(
        self,
        device_id: str,
        properties: Sequence[tuple[int, int]],
        *,
        delay: float = 0.2,
    ) -> list[MovaProperty]:
        """Read a deliberate diagnostic set in small rate-limited batches."""

        results: list[MovaProperty] = []
        for offset in range(0, len(properties), _MAX_PROPERTIES_PER_REQUEST):
            batch = properties[offset : offset + _MAX_PROPERTIES_PER_REQUEST]
            results.extend(await self.async_get_properties(device_id, batch))
            if offset + _MAX_PROPERTIES_PER_REQUEST < len(properties):
                await asyncio.sleep(delay)
        return results

    def clear_credentials(self) -> None:
        """Drop in-memory session secrets."""

        self._username = ""
        self._password = ""
        self._access_token = None
        self._refresh_token = None
        self._token_expires_at = 0.0

    def audit_serialized_session_secrets(self, serialized: str) -> None:
        """Fail closed if serialized diagnostics contain an in-memory token."""

        if not isinstance(serialized, str):
            raise TypeError("Serialized diagnostics must be text")
        for token in (
            self._username,
            self._password,
            self._access_token,
            self._refresh_token,
        ):
            if not isinstance(token, str) or not token:
                continue
            candidates = {
                token,
                json.dumps(token, ensure_ascii=True)[1:-1],
                quote(token, safe=""),
                quote_plus(token),
            }
            if any(candidate and candidate in serialized for candidate in candidates):
                raise ValueError("MOVAhome session secret remained in diagnostics")
