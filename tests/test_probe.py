"""Safety tests for the standalone guided protocol probe."""

from __future__ import annotations

import json
import stat

import pytest

from custom_components.mova_rover.models import MovaDevice, MovaProperty
from tools.mova_probe import (
    PROFILES,
    ProbeSafetyError,
    _select_device,
    _validate_results,
    _write_bundle,
)


def test_probe_rejects_unsolicited_or_duplicate_results() -> None:
    requested = [(1, 1), (2, 1)]

    with pytest.raises(ProbeSafetyError, match="unsolicited"):
        _validate_results([MovaProperty(9, 9, 0, 1)], requested)
    with pytest.raises(ProbeSafetyError, match="duplicate"):
        _validate_results(
            [MovaProperty(1, 1, 0, 1), MovaProperty(1, 1, 0, 2)],
            requested,
        )


def test_device_selection_rejects_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    devices = [
        MovaDevice(device_id="first", model="mova.swbot.first", name="First"),
        MovaDevice(device_id="second", model="mova.swbot.second", name="Second"),
    ]
    answers = iter(("0", "1"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert _select_device(devices).device_id == "first"


def test_probe_writes_unique_owner_only_files(tmp_path) -> None:
    bundle = {
        "profile": "rover-x10-core",
        "device": {"alias": "device_1", "model": "mova.swbot.test"},
    }

    first = _write_bundle(bundle, (), None, output_dir=tmp_path)
    second = _write_bundle(bundle, (), None, output_dir=tmp_path)

    assert first != second
    assert first.exists()
    assert second.exists()
    assert json.loads(first.read_text(encoding="utf-8")) == bundle
    assert stat.S_IMODE(first.stat().st_mode) == 0o600


def test_every_action_has_an_explicit_baseline_instruction() -> None:
    for steps in PROFILES.values():
        assert len({step.step_id for step in steps}) == len(steps)
        for step in steps:
            assert step.prepare.strip()
            if step.action is not None:
                assert step.action.strip()


def test_core_profile_does_not_conflate_idle_and_charging() -> None:
    steps = {step.step_id: step for step in PROFILES["rover-x10-core"]}

    assert "idle" in steps
    assert "charging" in steps
    assert steps["idle"].action is None
    assert steps["charging"].action is not None
