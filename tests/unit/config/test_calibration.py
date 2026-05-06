from __future__ import annotations

from copy import deepcopy

import pytest

from backtest_engine.config.calibration import (
    SpreadCalibrationDiagnosticsSettings,
    load_calibration_diagnostics_settings,
)


def test_bundled_calibration_diagnostics_settings_are_validated() -> None:
    settings = load_calibration_diagnostics_settings()

    assert settings.policy_name == "spread_calibration_internal_heuristics_v1"
    assert settings.threshold_status_levels == ("warning", "review_flag")


def test_calibration_diagnostics_thresholds_reject_inverted_warning_and_review() -> None:
    payload = load_calibration_diagnostics_settings().model_dump(mode="json")
    inverted_payload = deepcopy(payload)
    inverted_payload["thresholds"]["mae_log_warning"] = 0.20
    inverted_payload["thresholds"]["mae_log_review"] = 0.10

    with pytest.raises(ValueError, match="warning thresholds must not exceed review thresholds"):
        SpreadCalibrationDiagnosticsSettings.model_validate(inverted_payload)
