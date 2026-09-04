#!/usr/bin/env python3
"""Guided, read-only protocol probe for a MOVA Rover X10.

Credentials are accepted interactively only and raw cloud responses are never
written to disk. The single output file is sanitized and leak-audited first.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import secrets
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from custom_components.mova_rover.api import (  # noqa: E402
    MovaCloudClient,
    MovaError,
)
from custom_components.mova_rover.const import INTEGRATION_VERSION  # noqa: E402
from custom_components.mova_rover.models import MovaProperty  # noqa: E402
from custom_components.mova_rover.redaction import (  # noqa: E402
    audit_serialized_diagnostics,
    safe_device,
    safe_property,
)

MAX_BUNDLE_BYTES = 5 * 1024 * 1024
MAX_DEVICES = 100
MAX_SUPPORTED_PROPERTIES = 256
BATCH_DELAY_SECONDS = 0.5
DISCOVERY_SERVICES = (*range(1, 9), 20)
DISCOVERY_PIID_MAX = 120


class ProbeSafetyError(Exception):
    """The vendor response exceeded a probe safety boundary."""


@dataclass(frozen=True)
class ProbeStep:
    """One labelled state or before/after transition capture."""

    step_id: str
    prepare: str
    action: str | None = None


PROFILES: dict[str, tuple[ProbeStep, ...]] = {
    "rover-x10-core": (
        ProbeStep(
            "idle",
            "Power the Rover on, keep it out of the pool and off the charger, and leave it idle with AquaSonar off.",
        ),
        ProbeStep(
            "charging",
            "Return the Rover to the same powered-on, idle and off-charger state.",
            "Place it on the charger and wait until MOVAhome explicitly reports charging.",
        ),
        ProbeStep(
            "aquasonar_on",
            "Take the Rover off the charger, leave it idle and confirm AquaSonar is off.",
            "Switch AquaSonar on and wait until MOVAhome reports it connected.",
        ),
        ProbeStep(
            "in_water_idle",
            "Keep the Rover idle, out of the water, with AquaSonar connected.",
            "Place it safely in the pool without starting a cleaning task and wait until it is ready.",
        ),
        ProbeStep(
            "complete_started",
            "Leave the Rover idle in the pool and confirm no task is running.",
            "Start Complete cleaning in MOVAhome and wait until the app reports that it is running.",
        ),
        ProbeStep(
            "paused",
            "Leave Complete cleaning running.",
            "Pause the task in MOVAhome and wait until the app reports it paused.",
        ),
        ProbeStep(
            "resumed",
            "Leave the cleaning task paused.",
            "Resume it in MOVAhome and wait until the app reports that it is running again.",
        ),
        ProbeStep(
            "stopped",
            "Leave the cleaning task running.",
            "Stop the task in MOVAhome and wait until the app reports that it has stopped.",
        ),
        ProbeStep(
            "parked",
            "Leave the Rover idle in the pool with no task running.",
            "If MOVAhome offers a parking command, use it and wait until the resulting state is shown; otherwise skip this step.",
        ),
    ),
    "rover-x10-modes": (
        ProbeStep(
            "floor_started",
            "Leave the Rover idle in the pool and stop any previous task.",
            "Start Floor cleaning in MOVAhome and wait until the app reports that it is running.",
        ),
        ProbeStep(
            "wall_started",
            "Stop Floor cleaning and return the Rover to an idle in-pool state.",
            "Start Wall cleaning in MOVAhome and wait until the app reports that it is running.",
        ),
        ProbeStep(
            "surface_started",
            "Stop Wall cleaning and return the Rover to an idle in-pool state.",
            "Start Surface cleaning in MOVAhome and wait until the app reports that it is running.",
        ),
        ProbeStep(
            "spot_started",
            "Stop Surface cleaning and return the Rover to an idle in-pool state.",
            "If MOVAhome offers Spot cleaning, start it and wait until the app reports that it is running; otherwise skip this step.",
        ),
    ),
    "rover-x10-completion": (
        ProbeStep(
            "cleaning_started",
            "Leave the Rover idle in the pool and confirm no task is running.",
            "Start a normal cleaning task in MOVAhome and wait until the app reports that it is running.",
        ),
        ProbeStep(
            "cleaning_completed",
            "Leave that cleaning task running.",
            "Wait for the task to finish naturally and for MOVAhome to show the completed state.",
        ),
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture sanitized, read-only MOVA Rover protocol evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    guided = subparsers.add_parser("guided", help="Run a guided Rover X10 scenario")
    guided.add_argument(
        "--profile",
        choices=tuple(PROFILES),
        default="rover-x10-core",
        help="Scenario to capture (default: rover-x10-core)",
    )
    guided.add_argument(
        "--region",
        choices=("eu",),
        default="eu",
        help="MOVAhome cloud region; only EU is verified in this beta",
    )
    return parser


def _select_device(devices: list[Any]) -> Any:
    print("\nDevices returned by MOVAhome (cloud IDs and custom names are hidden):")
    for index, device in enumerate(devices, start=1):
        sanitized = safe_device(device, alias=f"device_{index}")
        details = [f"model={sanitized['model']}"]
        if sanitized["firmware"]:
            details.append(f"firmware={sanitized['firmware']}")
        if sanitized["category"]:
            details.append(f"category={sanitized['category']}")
        if sanitized["shared"] is not None:
            details.append(f"shared={'yes' if sanitized['shared'] else 'no'}")
        if sanitized["online"] is not None:
            details.append(f"online={'yes' if sanitized['online'] else 'no'}")
        print(f"  {index}. " + ", ".join(details))

    while True:
        selected = input("Select the Rover by number: ").strip()
        try:
            selected_index = int(selected)
            if not 1 <= selected_index <= len(devices):
                raise ValueError
            return devices[selected_index - 1]
        except (IndexError, ValueError):
            print("Please enter one of the numbers shown above.")


def _pairs() -> list[tuple[int, int]]:
    return [
        (siid, piid) for siid in DISCOVERY_SERVICES for piid in range(1, DISCOVERY_PIID_MAX + 1)
    ]


def _relative_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _validate_results(
    results: list[MovaProperty],
    requested_pairs: list[tuple[int, int]],
) -> list[MovaProperty]:
    """Reject extra, duplicated or unsolicited property results."""

    requested = set(requested_pairs)
    if len(results) > len(requested_pairs):
        raise ProbeSafetyError("MOVAhome returned more properties than requested")

    seen: set[tuple[int, int]] = set()
    for item in results:
        pair = (item.siid, item.piid)
        if pair not in requested:
            raise ProbeSafetyError("MOVAhome returned an unsolicited property")
        if pair in seen:
            raise ProbeSafetyError("MOVAhome returned a duplicate property")
        seen.add(pair)
    return results


def _safe_results(
    results: list[MovaProperty],
    correlation_key: bytes,
) -> list[dict[str, Any]]:
    return [
        safe_property(item, correlation_key=correlation_key) for item in results if item.supported
    ]


async def _snapshot(
    client: MovaCloudClient,
    device_id: str,
    supported_pairs: list[tuple[int, int]],
    session_started: float,
    correlation_key: bytes,
) -> dict[str, Any]:
    started_ms = _relative_ms(session_started)
    results = await client.async_get_properties_batched(
        device_id,
        supported_pairs,
        delay=BATCH_DELAY_SECONDS,
    )
    results = _validate_results(results, supported_pairs)
    return {
        "started_ms": started_ms,
        "finished_ms": _relative_ms(session_started),
        "properties": _safe_results(results, correlation_key),
    }


def _write_bundle(
    bundle: dict[str, Any],
    secrets_to_check: tuple[str, ...],
    client: MovaCloudClient | None,
    *,
    output_dir: Path | None = None,
) -> Path:
    serialized = json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=True)
    audit_serialized_diagnostics(serialized, secrets_to_check)
    if client is not None:
        client.audit_serialized_session_secrets(serialized)
    encoded = serialized.encode("utf-8") + b"\n"
    if len(encoded) > MAX_BUNDLE_BYTES:
        raise ValueError("Sanitized diagnostics exceed the 5 MiB safety limit")

    output_dir = output_dir or (ROOT_DIR / "probe-output")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)

    profile = str(bundle.get("profile") or "capture")
    safe_profile = "".join(
        character for character in profile if character.isalnum() or character == "-"
    )
    safe_profile = safe_profile[:48] or "capture"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")

    descriptor = -1
    target: Path | None = None
    try:
        for _ in range(10):
            candidate = output_dir / (
                f"mova-rover-{safe_profile}-{stamp}-{secrets.token_hex(3)}.json"
            )
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                continue
            target = candidate
            break
        if descriptor < 0 or target is None:
            raise FileExistsError("Could not allocate a unique diagnostics filename")

        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if target is None:
        raise FileExistsError("Diagnostics output was not created")
    return target


async def _guided(profile: str, region: str) -> int:
    print(
        "This tool performs only MOVAhome login, device listing and get_properties reads.\n"
        "It cannot start, stop, steer, update, reset, pair or unbind a robot.\n"
        "Use a shared test account and keep people and animals out of the pool.\n"
    )
    username = input("MOVAhome email: ").strip()
    password = getpass.getpass("MOVAhome password (not stored): ")
    if not username or not password:
        print("Email and password are required.")
        return 2
    if len(username) > 320 or len(password) > 1024:
        print("Credentials exceed the probe's safety limits.")
        return 2

    started_monotonic = time.monotonic()
    correlation_key = secrets.token_bytes(32)
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "integration_version": INTEGRATION_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "region": region,
        "transport": {
            "https_certificate_verification": True,
            "rest_read_only": True,
            "mqtt_used": False,
            "commands_used": False,
        },
        "profile": profile,
        "device": None,
        "discovery": None,
        "steps": [],
        "errors": [],
        "redaction": {
            "raw_responses_written": False,
            "identifiers_pseudonymized": True,
            "unknown_values_raw": False,
            "correlation_fingerprints": "bundle_local_hmac_sha256",
            "leak_audit": "pending",
        },
    }
    registered_secrets: set[str] = {username, password}
    client: MovaCloudClient | None = None
    output_written = False

    try:
        async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
            client = MovaCloudClient(session, username, password, region)
            print("Connecting to MOVAhome over verified HTTPS...")
            await client.async_login()
            devices = await client.async_get_devices()
            if not devices:
                print("MOVAhome returned no owned or shared devices.")
                return 3
            if len(devices) > MAX_DEVICES:
                raise ProbeSafetyError("MOVAhome returned too many devices")
            device = _select_device(devices)
            registered_secrets.add(device.device_id)
            bundle["device"] = safe_device(device)

            print(
                "\nDiscovering readable properties. This is a bounded, rate-limited read and "
                "can take about a minute..."
            )
            requested_pairs = _pairs()
            discovered = await client.async_get_properties_batched(
                device.device_id,
                requested_pairs,
                delay=BATCH_DELAY_SECONDS,
            )
            discovered = _validate_results(discovered, requested_pairs)
            supported = [item for item in discovered if item.supported]
            supported_pairs = sorted({(item.siid, item.piid) for item in supported})
            error_codes = Counter(str(item.code) for item in discovered if not item.supported)
            bundle["discovery"] = {
                "services": list(DISCOVERY_SERVICES),
                "piid_range": [1, DISCOVERY_PIID_MAX],
                "requested_count": len(_pairs()),
                "returned_count": len(discovered),
                "supported_count": len(supported_pairs),
                "unsupported_codes": dict(sorted(error_codes.items())),
                "supported": _safe_results(supported, correlation_key),
            }
            print(f"Found {len(supported_pairs)} readable properties.")

            if not supported_pairs:
                print("No readable properties were found; exporting discovery diagnostics only.")
                return 4
            if len(supported_pairs) > MAX_SUPPORTED_PROPERTIES:
                raise ProbeSafetyError("Too many readable properties for a bounded guided capture")

            print("\nThe app actions below are performed manually by the device owner.")
            for step in PROFILES[profile]:
                answer = (
                    input(
                        f"\n[{step.step_id}] Prepare the baseline:\n{step.prepare}\n"
                        "Press Enter to capture this baseline, type 's' to skip, or 'q' to finish: "
                    )
                    .strip()
                    .casefold()
                )
                if answer == "q":
                    break
                if answer == "s":
                    bundle["steps"].append({"id": step.step_id, "skipped": True})
                    continue

                baseline = await _snapshot(
                    client,
                    device.device_id,
                    supported_pairs,
                    started_monotonic,
                    correlation_key,
                )
                captured_step: dict[str, Any] = {
                    "id": step.step_id,
                    "baseline": baseline,
                }

                if step.action is not None:
                    action_answer = (
                        input(
                            f"Baseline captured. Now perform this action:\n{step.action}\n"
                            "Press Enter as soon as the stated app condition is stable, "
                            "type 's' to leave the action uncaptured, or 'q' to finish: "
                        )
                        .strip()
                        .casefold()
                    )
                    if action_answer == "s":
                        captured_step["action_skipped"] = True
                        bundle["steps"].append(captured_step)
                        continue
                    if action_answer == "q":
                        captured_step["finished_before_action"] = True
                        bundle["steps"].append(captured_step)
                        break

                first_after = await _snapshot(
                    client,
                    device.device_id,
                    supported_pairs,
                    started_monotonic,
                    correlation_key,
                )
                await asyncio.sleep(5)
                second_after = await _snapshot(
                    client,
                    device.device_id,
                    supported_pairs,
                    started_monotonic,
                    correlation_key,
                )
                captured_step["after"] = {
                    "first": first_after,
                    "after_5_seconds": second_after,
                }
                bundle["steps"].append(captured_step)
                print("Captured a baseline and two sanitized post-state snapshots.")
    except (KeyboardInterrupt, asyncio.CancelledError):
        bundle["errors"].append({"type": "interrupted"})
        print("\nCapture interrupted; exporting the completed sanitized steps.")
    except MovaError as err:
        bundle["errors"].append({"type": type(err).__name__})
        print(f"Probe stopped safely: {type(err).__name__}")
    except Exception as err:
        bundle["errors"].append({"type": type(err).__name__})
        print(f"Probe stopped safely: {type(err).__name__}")
    finally:
        bundle["redaction"]["leak_audit"] = "passed"
        try:
            output = _write_bundle(bundle, tuple(registered_secrets), client)
        except (OSError, ValueError):
            print("No file was written because safe diagnostics export did not complete.")
        else:
            output_written = True
            print(f"Sanitized diagnostics written to: {output}")
        finally:
            if client is not None:
                client.clear_credentials()

    return 0 if output_written else 5


def main() -> int:
    """Run the requested read-only probe."""

    args = _parser().parse_args()
    if args.command == "guided":
        return asyncio.run(_guided(args.profile, args.region))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
