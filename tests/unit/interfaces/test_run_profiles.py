from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from backtest_engine.config.execution_costs import DEFAULT_EXECUTION_COST_PROFILE_ID
from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.enums import RunKind
from backtest_engine.core.errors import ApplicationError
from backtest_engine.interfaces.run_profiles import (
    RunProfile,
    load_run_profile,
    load_run_profile_spec,
    run_profile_to_spec,
)


ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DIR = ROOT / "run_profiles"
STRATEGY_ROOT = ROOT / "src" / "backtest_engine" / "strategies"


@pytest.mark.parametrize(
    "profile_name",
    (
        "fx_single_asset.yaml",
        "fx_statarb_pair.yaml",
        "three_slot_portfolio.yaml",
    ),
)
def test_example_profiles_load_into_backtest_run_specs(profile_name: str) -> None:
    run_spec = load_run_profile_spec(EXAMPLE_DIR / profile_name)

    assert isinstance(run_spec, BacktestRunSpec)
    assert run_spec.strategies


def test_fx_profiles_use_verified_local_mt5_history_windows() -> None:
    single_asset = load_run_profile_spec(EXAMPLE_DIR / "fx_single_asset.yaml")
    statarb_pair = load_run_profile_spec(EXAMPLE_DIR / "fx_statarb_pair.yaml")

    assert single_asset.execution_window.start_utc == datetime(2022, 4, 11, 15, 45, tzinfo=timezone.utc)
    assert single_asset.execution_window.end_utc == datetime(2026, 4, 19, 23, 30, tzinfo=timezone.utc)
    assert statarb_pair.execution_window.start_utc == datetime(2022, 4, 11, 19, 30, tzinfo=timezone.utc)
    assert statarb_pair.execution_window.end_utc == datetime(2026, 4, 19, 23, 30, tzinfo=timezone.utc)


def test_example_profiles_reference_existing_strategy_folders() -> None:
    discovered_implementation_ids = {
        definition_path.parent.name for definition_path in STRATEGY_ROOT.glob("*/definition.py")
    }

    for profile_path in sorted(EXAMPLE_DIR.glob("*.yaml")):
        profile = load_run_profile(profile_path)
        implementation_ids = {strategy.implementation_id for strategy in profile.strategies}

        assert implementation_ids.issubset(discovered_implementation_ids), profile_path


def test_minimal_toml_profile_loads_into_backtest_run_spec(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    path.write_text(
        """
run_kind = "single"

[execution_window]
start_utc = 2024-01-01T00:00:00Z
end_utc = 2024-03-01T00:00:00Z

[dataset]
source_system = "mt5"
normalization_policy = "nautilus_v1"
schema_version = "1"
symbol_universe = ["EURUSD"]
timeframe = "15m"
dataset_version = "2026-04-19"

[capital_base]
amount = "100000"
currency = "USD"

[[strategies]]
slot_id = "eurusd_sma_pullback"
weight_frac = 1.0
strategy_id = "eurusd_sma_pullback_v1"
implementation_id = "sma_pullback"
policy_version = "v1"
legs = ["EURUSD"]

[strategies.parameters]
fast_sma_window = 50
slow_sma_window = 200
atr_window = 14
atr_sl_mult = 2.0
rr_ratio = 3.0
trade_direction = "both"
""".strip(),
        encoding="utf-8",
    )

    run_spec = load_run_profile_spec(path)

    assert run_spec.run_kind is RunKind.SINGLE
    assert run_spec.strategies[0].strategy.implementation_id == "sma_pullback"


def test_yaml_execution_policy_reaches_backtest_run_spec(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["execution_policy"] = _execution_policy_payload()
    path = _write_yaml(tmp_path, payload)

    run_spec = load_run_profile_spec(path)

    assert run_spec.execution_policy is not None
    assert run_spec.execution_policy.execution_costs.profile_id == DEFAULT_EXECUTION_COST_PROFILE_ID
    assert run_spec.execution_policy.venue_overrides is not None
    assert run_spec.execution_policy.venue_overrides.oms_type == "HEDGING"
    assert run_spec.execution_policy.venue_overrides.account_type == "MARGIN"
    assert run_spec.execution_policy.venue_overrides.book_type == "L1_MBP"


def test_profile_round_trip_preserves_execution_policy_and_hash(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["execution_policy"] = _execution_policy_payload()
    path = _write_yaml(tmp_path, payload)
    profile = load_run_profile(path)
    run_spec = run_profile_to_spec(profile)
    round_tripped_profile = RunProfile.model_validate(profile.model_dump(mode="json"))

    round_tripped_spec = run_profile_to_spec(round_tripped_profile)

    assert round_tripped_spec.execution_policy == run_spec.execution_policy
    assert round_tripped_spec.content_hash == run_spec.content_hash


def test_unsupported_extension_fails(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text("{}", encoding="utf-8")

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "<path>"
    assert error.context["error_type"] == "unsupported_suffix"


def test_empty_file_fails(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("   ", encoding="utf-8")

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["error_type"] == "empty_document"


def test_non_mapping_top_level_document_fails(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["error_type"] == "non_mapping_document"


def test_yaml_multi_document_input_fails(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("---\nrun_kind: single\n---\nrun_kind: portfolio\n", encoding="utf-8")

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["error_type"] == "yaml_document_count"


@pytest.mark.parametrize(
    "run_kind",
    (
        RunKind.BATCH.value,
        RunKind.WALK_FORWARD.value,
        RunKind.SCENARIO.value,
        RunKind.BASELINE.value,
    ),
)
def test_non_runnable_run_kind_fails_at_profile_layer(tmp_path: Path, run_kind: str) -> None:
    payload = _single_profile_payload()
    payload["run_kind"] = run_kind
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "run_kind"
    assert "single and portfolio" in error.context["detail"]


def test_unknown_top_level_field_fails(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["unexpected"] = True
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "unexpected"
    assert error.context["error_type"] == "extra_forbidden"


def test_unknown_nested_strategy_field_fails(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["unexpected"] = True
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "strategies.0.unexpected"
    assert error.context["error_type"] == "extra_forbidden"


def test_invalid_execution_cost_profile_id_fails_with_stable_context(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["execution_policy"] = _execution_policy_payload()
    payload["execution_policy"]["execution_costs"]["profile_id"] = "experimental_costs"
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "execution_policy.execution_costs.profile_id"
    assert error.context["error_type"] == "value_error"
    assert "unsupported execution-cost profile_id" in error.context["detail"]


def test_empty_execution_venue_overrides_fail_with_stable_context(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["execution_policy"] = _execution_policy_payload()
    payload["execution_policy"]["venue_overrides"] = {}
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "execution_policy.venue_overrides"
    assert error.context["error_type"] == "value_error"


def test_invalid_execution_venue_override_literal_fails_with_stable_context(
    tmp_path: Path,
) -> None:
    payload = _single_profile_payload()
    payload["execution_policy"] = _execution_policy_payload()
    payload["execution_policy"]["venue_overrides"]["book_type"] = "L4_BOOK"
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "execution_policy.venue_overrides.book_type"
    assert error.context["error_type"] == "literal_error"


def test_empty_strategies_fails(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["strategies"] = []
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "strategies"


def test_empty_symbol_universe_fails(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["dataset"]["symbol_universe"] = []
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "dataset.symbol_universe"


def test_empty_legs_fails(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["legs"] = []
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "strategies.0.legs"


def test_duplicate_slot_ids_fail(tmp_path: Path) -> None:
    payload = _portfolio_profile_payload()
    payload["strategies"][1]["slot_id"] = payload["strategies"][0]["slot_id"]
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert "slot_id" in error.context["detail"]


def test_duplicate_dataset_symbols_fail(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["dataset"]["symbol_universe"] = ["EURUSD", "EURUSD"]
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert "symbol_universe" in error.context["detail"]


def test_duplicate_leg_symbols_fail(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["dataset"]["symbol_universe"] = ["EURUSD", "GBPUSD"]
    payload["strategies"][0]["legs"] = ["EURUSD", "EURUSD"]
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert "legs" in error.context["detail"]


def test_duplicate_tags_fail(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["tags"] = ["example", "example"]
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert "tags" in error.context["detail"]


@pytest.mark.parametrize("weight_frac", (-0.1, 1.1))
def test_weight_fraction_bounds_fail(tmp_path: Path, weight_frac: float) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["weight_frac"] = weight_frac
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "strategies.0.weight_frac"


def test_portfolio_weights_not_summing_to_one_fail_through_run_spec(tmp_path: Path) -> None:
    payload = _portfolio_profile_payload()
    payload["strategies"][0]["weight_frac"] = 0.5
    payload["strategies"][1]["weight_frac"] = 0.4
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile_spec(path))

    assert "weights to sum to 1.0" in error.context["detail"]


def test_floating_point_portfolio_weight_tolerance_is_canonical(tmp_path: Path) -> None:
    payload = _portfolio_profile_payload(strategy_count=3)
    payload["strategies"][0]["weight_frac"] = 0.1
    payload["strategies"][1]["weight_frac"] = 0.2
    payload["strategies"][2]["weight_frac"] = 0.7
    path = _write_yaml(tmp_path, payload)

    run_spec = load_run_profile_spec(path)

    assert run_spec.run_kind is RunKind.PORTFOLIO
    assert sum(strategy.weight_frac for strategy in run_spec.strategies) == pytest.approx(1.0)


def test_leg_symbol_outside_dataset_universe_fails_through_run_spec(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["legs"] = ["GBPUSD"]
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile_spec(path))

    assert "dataset symbol_universe" in error.context["detail"]


def test_naive_datetime_fails_at_profile_layer(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["execution_window"]["start_utc"] = "2024-01-01T00:00:00"
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "execution_window.start_utc"
    assert "timezone-aware" in error.context["detail"]


def test_window_ordering_fails_through_execution_window(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["execution_window"]["start_utc"] = "2024-03-01T00:00:00Z"
    payload["execution_window"]["end_utc"] = "2024-01-01T00:00:00Z"
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile_spec(path))

    assert "earlier than end_utc" in error.context["detail"]


def test_portfolio_policy_on_single_run_fails_through_run_spec(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["portfolio_policy"] = _portfolio_policy_payload()
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile_spec(path))

    assert "portfolio_policy is only valid" in error.context["detail"]


@pytest.mark.parametrize(
    "parameter_payload",
    (
        {"bad_datetime": datetime(2024, 1, 1, tzinfo=timezone.utc)},
        {1: "non-string-key"},
        {"bad_nan": math.nan},
        {"bad_inf": math.inf},
    ),
)
def test_non_json_parameter_values_fail(
    tmp_path: Path,
    parameter_payload: dict[Any, Any],
) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["parameters"] = parameter_payload
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "strategies.0.parameters"


def test_valid_unknown_implementation_id_loads_into_run_spec(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["implementation_id"] = "unknown_strategy"
    path = _write_yaml(tmp_path, payload)

    run_spec = load_run_profile_spec(path)

    assert run_spec.strategies[0].strategy.implementation_id == "unknown_strategy"


def test_invalid_implementation_id_syntax_fails(tmp_path: Path) -> None:
    payload = _single_profile_payload()
    payload["strategies"][0]["implementation_id"] = "SmaPullback"
    path = _write_yaml(tmp_path, payload)

    error = _raises_profile_error(lambda: load_run_profile(path))

    assert error.context["field_path"] == "strategies.0.implementation_id"
    assert "implementation_id" in error.context["detail"]


def test_profile_round_trip_preserves_canonical_content_hash() -> None:
    profile = load_run_profile(EXAMPLE_DIR / "three_slot_portfolio.yaml")
    run_spec = run_profile_to_spec(profile)
    round_tripped_profile = RunProfile.model_validate(profile.model_dump(mode="json"))

    round_tripped_spec = run_profile_to_spec(round_tripped_profile)

    assert round_tripped_spec.content_hash == run_spec.content_hash
    assert round_tripped_spec.model_dump(exclude_computed_fields=True) == run_spec.model_dump(
        exclude_computed_fields=True,
    )


def _single_profile_payload() -> dict[str, Any]:
    return {
        "run_kind": "single",
        "execution_window": {
            "start_utc": "2024-01-01T00:00:00Z",
            "end_utc": "2024-03-01T00:00:00Z",
        },
        "dataset": {
            "source_system": "mt5",
            "normalization_policy": "nautilus_v1",
            "schema_version": "1",
            "symbol_universe": ["EURUSD"],
            "timeframe": "15m",
            "dataset_version": "2026-04-19",
        },
        "capital_base": {
            "amount": "100000",
            "currency": "USD",
        },
        "strategies": [
            {
                "slot_id": "eurusd_sma_pullback",
                "weight_frac": 1.0,
                "strategy_id": "eurusd_sma_pullback_v1",
                "implementation_id": "sma_pullback",
                "policy_version": "v1",
                "legs": ["EURUSD"],
                "parameters": {
                    "fast_sma_window": 50,
                    "slow_sma_window": 200,
                    "atr_window": 14,
                    "atr_sl_mult": 2.0,
                    "rr_ratio": 3.0,
                    "trade_direction": "both",
                },
            },
        ],
        "tags": ["example"],
    }


def _portfolio_profile_payload(*, strategy_count: int = 2) -> dict[str, Any]:
    payload = _single_profile_payload()
    payload["run_kind"] = "portfolio"
    payload["dataset"]["symbol_universe"] = ["EURUSD", "GBPUSD"]
    payload["portfolio_policy"] = _portfolio_policy_payload()
    payload["strategies"] = [
        payload["strategies"][0],
        {
            "slot_id": "gbpusd_channel_breakout",
            "weight_frac": 0.5,
            "strategy_id": "gbpusd_channel_breakout_v1",
            "implementation_id": "channel_breakout_long",
            "policy_version": "v1",
            "legs": ["GBPUSD"],
            "parameters": {
                "length": 50,
                "ema_period": 200,
                "entry_buffer_ticks": 1,
                "trade_direction": "long",
            },
        },
    ]
    payload["strategies"][0]["weight_frac"] = 0.5
    if strategy_count == 3:
        payload["strategies"].append(
            {
                "slot_id": "eurusd_gbpusd_spread",
                "weight_frac": 0.0,
                "strategy_id": "eurusd_gbpusd_spread_v1",
                "implementation_id": "statarb_weighted_spread",
                "policy_version": "v1",
                "legs": ["EURUSD", "GBPUSD"],
                "parameters": {
                    "trade_sizes": [1.0, 1.0],
                    "spread_weights": [1.0, -1.0],
                    "zscore_window": 120,
                    "entry_zscore": 2.0,
                    "exit_zscore": 0.5,
                    "trade_direction": "both",
                },
            },
        )
    return copy.deepcopy(payload)


def _portfolio_policy_payload() -> dict[str, Any]:
    return {
        "rebalance_cadence": "run_open",
        "target_portfolio_vol_frac": 1.0,
        "vol_lookback_bars": 20,
        "max_portfolio_leverage": 1.0,
        "estimator_version": "rolling_sample_v1",
        "annualization_policy": "252d",
        "warmup_policy": "hold_flat_until_lookback",
    }


def _execution_policy_payload() -> dict[str, Any]:
    return {
        "execution_costs": {"profile_id": DEFAULT_EXECUTION_COST_PROFILE_ID},
        "venue_overrides": {
            "oms_type": "HEDGING",
            "account_type": "MARGIN",
            "book_type": "L1_MBP",
        },
    }


def _write_yaml(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _raises_profile_error(action: Any) -> ApplicationError:
    with pytest.raises(ApplicationError) as exc_info:
        action()
    error = exc_info.value
    assert "profile_path" in error.context
    assert "field_path" in error.context
    assert "error_type" in error.context
    assert "detail" in error.context
    return error
