# mypy: disable-error-code=no-untyped-def
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
import shutil
import textwrap
from typing import cast

import pytest

import backtest_engine.strategies as strategies_package
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue
from backtest_engine.domain.strategy.specifications import (
    PortfolioStrategySpec,
    StrategyLegSpec,
    StrategySpec,
)
from backtest_engine.infrastructure.nautilus.catalogs import CatalogItem, CatalogReference
from backtest_engine.infrastructure.nautilus.portfolio_sizing import CompiledSlotSizing
from backtest_engine.infrastructure.nautilus.strategy_package_resolver import (
    build_default_nautilus_strategy_resolver,
)
from backtest_engine.strategies.package_loader import (
    clear_strategy_package_definition_cache,
    load_strategy_package_definition,
)


def _build_catalog() -> CatalogReference:
    return CatalogReference(
        dataset_id="dataset-unit-test",
        catalog_root=Path("catalogs/unit-test"),
        items=(
            CatalogItem(
                symbol="ES",
                timeframe="30m",
                instrument_id="ES.CME",
                venue="CME",
                quote_currency="USD",
                bar_type="ES.CME-30-MINUTE-LAST-EXTERNAL",
                row_count=8,
            ),
            CatalogItem(
                symbol="NQ",
                timeframe="30m",
                instrument_id="NQ.CME",
                venue="CME",
                quote_currency="USD",
                bar_type="NQ.CME-30-MINUTE-LAST-EXTERNAL",
                row_count=8,
            ),
        ),
    )


def _build_strategy_spec(
    implementation_id: str,
    *,
    legs: tuple[str, ...] = ("ES",),
    parameters: Mapping[str, object] | None = None,
) -> PortfolioStrategySpec:
    return PortfolioStrategySpec(
        slot_id=f"slot-{implementation_id}",
        weight_frac=1.0,
        strategy=StrategySpec(
            strategy_id=f"{implementation_id}-strategy",
            implementation_id=implementation_id,
            policy_version="v1",
            parameters=cast(dict[str, JsonValue], dict(parameters or {})),
        ),
        legs=tuple(StrategyLegSpec(symbol=symbol) for symbol in legs),
    )


@pytest.fixture
def write_strategy_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    package_root = tmp_path / "fixture_packages" / "backtest_engine" / "strategies"
    package_root.mkdir(parents=True)
    existing_path = list(strategies_package.__path__)
    monkeypatch.setattr(strategies_package, "__path__", [*existing_path, str(package_root)])
    clear_strategy_package_definition_cache()

    def _write(
        implementation_id: str,
        *,
        definition_body: str | None = None,
        runtime_body: str | None = None,
        include_definition: bool = True,
    ) -> None:
        strategy_dir = package_root / implementation_id
        strategy_dir.mkdir(parents=True, exist_ok=True)
        (strategy_dir / "__init__.py").write_text('"""fixture strategy package."""\n', encoding="utf-8")
        (strategy_dir / "nautilus_strategy.py").write_text(
            textwrap.dedent(runtime_body or _valid_runtime_body()),
            encoding="utf-8",
        )
        if include_definition:
            (strategy_dir / "definition.py").write_text(
                textwrap.dedent(definition_body or _valid_definition_body(implementation_id)),
                encoding="utf-8",
            )
        shutil.rmtree(strategy_dir / "__pycache__", ignore_errors=True)
        clear_strategy_package_definition_cache()

    yield _write
    clear_strategy_package_definition_cache()


def _valid_definition_body(
    implementation_id: str,
    *,
    min_legs: int = 1,
    max_legs: int | None = None,
    validate_body: str = "return None",
    config_body: str | None = None,
) -> str:
    max_legs_repr = "None" if max_legs is None else str(max_legs)
    build_config = config_body or (
        "return {\n"
        "        'instrument_ids': [item.instrument_id for item in strategy_items],\n"
        "        'leg_symbols': [leg.symbol for leg in strategy_spec.legs],\n"
        "        'required_value': parameters.required_value,\n"
        "        'slot_multiplier': 1.0 if slot_sizing is None else float(slot_sizing.slot_multiplier),\n"
        "    }"
    )
    return f"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.domain.strategy.specifications import PortfolioStrategySpec
from backtest_engine.strategies.package_contracts import StrategyPackageDefinition


class FixtureParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    required_value: int = Field(gt=0)


def build_parameters(strategy_spec: PortfolioStrategySpec) -> FixtureParameters:
    return FixtureParameters.model_validate(strategy_spec.strategy.parameters)


def build_config(strategy_spec, parameters, strategy_items, slot_sizing):
    {textwrap.indent(build_config, '    ').lstrip()}


def validate_strategy_spec(strategy_spec: PortfolioStrategySpec) -> None:
    {textwrap.indent(validate_body, '    ').lstrip()}


STRATEGY_DEFINITION = StrategyPackageDefinition(
    implementation_id='{implementation_id}',
    strategy_path='backtest_engine.strategies.{implementation_id}.nautilus_strategy:FixtureStrategy',
    config_path='backtest_engine.strategies.{implementation_id}.nautilus_strategy:FixtureConfig',
    build_parameters=build_parameters,
    build_config=build_config,
    min_legs={min_legs},
    max_legs={max_legs_repr},
    validate_strategy_spec=validate_strategy_spec,
)
"""


def _valid_runtime_body() -> str:
    return """
class FixtureStrategy:
    pass


class FixtureConfig:
    pass
"""


def test_clear_strategy_package_definition_cache_purges_loaded_strategy_modules(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package(
        "reload_fixture",
        definition_body=_valid_definition_body("reload_fixture", min_legs=1),
    )
    first_definition = load_strategy_package_definition("reload_fixture")

    write_strategy_package(
        "reload_fixture",
        definition_body=_valid_definition_body("reload_fixture", min_legs=2),
    )
    second_definition = load_strategy_package_definition("reload_fixture")

    assert first_definition.min_legs == 1
    assert second_definition.min_legs == 2
    assert second_definition is not first_definition


def test_strategy_package_resolver_rejects_unknown_implementation_id() -> None:
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="definition could not be imported"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("unknown_fixture"),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_missing_definition_module(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("missing_definition", include_definition=False)
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="definition could not be imported"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("missing_definition"),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_includes_import_error_message(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("import_error_fixture", definition_body="raise ImportError('boom from fixture')\n")
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="definition import failed") as exc_info:
        resolver.resolve(
            strategy_spec=_build_strategy_spec("import_error_fixture"),
            catalog=_build_catalog(),
        )

    assert exc_info.value.context["error_message"] == "boom from fixture"


def test_strategy_package_resolver_rejects_missing_definition_export(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("missing_export", definition_body="NOT_THE_DEFINITION = object()\n")
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="must export STRATEGY_DEFINITION"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("missing_export"),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_implementation_id_mismatch(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("mismatch_fixture", definition_body=_valid_definition_body("other_fixture"))
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="does not match folder name"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("mismatch_fixture", parameters={"required_value": 1}),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_runtime_paths_outside_cartridge(
    write_strategy_package: Callable[..., None],
) -> None:
    definition_body = _valid_definition_body("bad_runtime_path").replace(
        "backtest_engine.strategies.bad_runtime_path.nautilus_strategy:FixtureStrategy",
        "backtest_engine.infrastructure.nautilus.strategies.bad_runtime_path:FixtureStrategy",
    )
    write_strategy_package("bad_runtime_path", definition_body=definition_body)
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="runtime path must point at its nautilus_strategy"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("bad_runtime_path", parameters={"required_value": 1}),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_bad_config_runtime_path(
    write_strategy_package: Callable[..., None],
) -> None:
    definition_body = _valid_definition_body("bad_config_path").replace(
        "backtest_engine.strategies.bad_config_path.nautilus_strategy:FixtureConfig",
        "backtest_engine.infrastructure.nautilus.strategies.bad_config_path:FixtureConfig",
    )
    write_strategy_package("bad_config_path", definition_body=definition_body)
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="runtime path must point at its nautilus_strategy"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("bad_config_path", parameters={"required_value": 1}),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_missing_runtime_path_attribute(
    write_strategy_package: Callable[..., None],
) -> None:
    definition_body = _valid_definition_body("bad_runtime_attribute").replace(
        "backtest_engine.strategies.bad_runtime_attribute.nautilus_strategy:FixtureStrategy",
        "backtest_engine.strategies.bad_runtime_attribute.nautilus_strategy:TypoFixtureStrategy",
    )
    write_strategy_package("bad_runtime_attribute", definition_body=definition_body)
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="runtime path attribute does not exist"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec(
                "bad_runtime_attribute",
                parameters={"required_value": 1},
            ),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_invalid_implementation_id_format() -> None:
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match=r"\^\[a-z\]\[a-z0-9_\]\*\$"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("Invalid-Name"),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_rejects_invalid_leg_count(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("requires_two_legs", definition_body=_valid_definition_body("requires_two_legs", min_legs=2))
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="does not support so few legs"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("requires_two_legs", parameters={"required_value": 1}),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_validates_leg_count_before_catalog_symbols(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package(
        "requires_two_legs_before_catalog",
        definition_body=_valid_definition_body("requires_two_legs_before_catalog", min_legs=2),
    )
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="does not support so few legs"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec(
                "requires_two_legs_before_catalog",
                legs=("MISSING",),
                parameters={"required_value": 1},
            ),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_wraps_strategy_specific_validation_failure(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package(
        "validator_failure",
        definition_body=_valid_definition_body(
            "validator_failure",
            validate_body="raise ValueError('fixture invariant failed')",
        ),
    )
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="validate_strategy_spec failed"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("validator_failure", parameters={"required_value": 1}),
            catalog=_build_catalog(),
        )


def test_strategy_package_resolver_wraps_parameter_validation_failure(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("parameter_failure")
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="parameter validation failed"):
        resolver.resolve(
            strategy_spec=_build_strategy_spec("parameter_failure"),
            catalog=_build_catalog(),
        )


@pytest.mark.parametrize(
    ("case_name", "config_body", "invalid_type"),
    (
        ("decimal", "from decimal import Decimal\nreturn {'bad': Decimal('1.25')}", "Decimal"),
        (
            "datetime",
            "from datetime import datetime, timezone\n"
            "return {'bad': datetime(2026, 4, 1, tzinfo=timezone.utc)}",
            "datetime",
        ),
        ("tuple", "return {'bad': (1, 2)}", "tuple"),
        ("object", "return {'bad': object()}", "object"),
        ("nan", "return {'bad': float('nan')}", "float"),
        ("infinity", "return {'bad': float('inf')}", "float"),
        ("numpy_scalar", "import numpy as np\nreturn {'bad': np.float64(1.25)}", "float64"),
    ),
)
def test_strategy_package_resolver_rejects_non_serializable_config(
    write_strategy_package: Callable[..., None],
    case_name: str,
    config_body: str,
    invalid_type: str,
) -> None:
    write_strategy_package(
        f"bad_config_{case_name}",
        definition_body=_valid_definition_body(
            f"bad_config_{case_name}",
            config_body=config_body,
        ),
    )
    resolver = build_default_nautilus_strategy_resolver()

    with pytest.raises(InfrastructureError, match="non-serializable config payload") as exc_info:
        resolver.resolve(
            strategy_spec=_build_strategy_spec(
                f"bad_config_{case_name}",
                parameters={"required_value": 1},
            ),
            catalog=_build_catalog(),
        )

    assert exc_info.value.context["invalid_type"] == invalid_type


def test_strategy_package_resolver_accepts_nested_json_config(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package(
        "nested_json_config",
        definition_body=_valid_definition_body(
            "nested_json_config",
            config_body=(
                "return {\n"
                "        'nested': {\n"
                "            'items': [1, 2.5, 'three', True, None, {'child': []}],\n"
                "        },\n"
                "    }"
            ),
        ),
    )
    resolver = build_default_nautilus_strategy_resolver()

    compiled = resolver.resolve(
        strategy_spec=_build_strategy_spec("nested_json_config", parameters={"required_value": 1}),
        catalog=_build_catalog(),
    )

    assert compiled.config == {
        "nested": {
            "items": [1, 2.5, "three", True, None, {"child": []}],
        },
    }


def test_strategy_package_resolver_passes_minimal_slot_sizing_view(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package(
        "slot_view_fixture",
        definition_body=_valid_definition_body(
            "slot_view_fixture",
            config_body=(
                "return {\n"
                "        'slot_multiplier': slot_sizing.slot_multiplier,\n"
                "        'has_effective_weight_frac': hasattr(slot_sizing, 'effective_weight_frac'),\n"
                "    }"
            ),
        ),
    )
    resolver = build_default_nautilus_strategy_resolver()

    compiled = resolver.resolve(
        strategy_spec=_build_strategy_spec("slot_view_fixture", parameters={"required_value": 1}),
        catalog=_build_catalog(),
        slot_sizing=CompiledSlotSizing(
            slot_id="slot-slot_view_fixture",
            target_weight_frac=1.0,
            effective_weight_frac=0.5,
            slot_multiplier=0.5,
        ),
    )

    assert compiled.config["slot_multiplier"] == 0.5
    assert compiled.config["has_effective_weight_frac"] is False


def test_strategy_package_resolver_preserves_catalog_leg_order(
    write_strategy_package: Callable[..., None],
) -> None:
    write_strategy_package("ordered_fixture")
    resolver = build_default_nautilus_strategy_resolver()

    compiled = resolver.resolve(
        strategy_spec=_build_strategy_spec(
            "ordered_fixture",
            legs=("NQ", "ES"),
            parameters={"required_value": 7},
        ),
        catalog=_build_catalog(),
    )

    assert compiled.implementation_id == "ordered_fixture"
    assert compiled.strategy_path == (
        "backtest_engine.strategies.ordered_fixture.nautilus_strategy:FixtureStrategy"
    )
    assert compiled.config_path == (
        "backtest_engine.strategies.ordered_fixture.nautilus_strategy:FixtureConfig"
    )
    assert compiled.config["instrument_ids"] == ["NQ.CME", "ES.CME"]
    assert compiled.config["leg_symbols"] == ["NQ", "ES"]
    assert compiled.config["required_value"] == 7
