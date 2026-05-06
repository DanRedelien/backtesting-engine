"""Canonical Nautilus runner boundary and concrete BacktestNode adapter."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.config.runtime import BacktestRunSpec
from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.types import JsonValue, NonEmptyStr
from backtest_engine.infrastructure.nautilus.reports import NautilusReportWriter
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    NautilusImportableModelSpec,
    NautilusRunSpec,
    NautilusRunSpecCompiler,
    NautilusStrategySpec,
    NautilusVenueSpec,
)

if TYPE_CHECKING:
    from nautilus_trader.backtest.config import BacktestRunConfig
    from nautilus_trader.config import ImportableStrategyConfig


class NautilusRunArtifacts(BaseModel):
    """Normalized runtime artifacts emitted by the Nautilus boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyStr
    runtime_root: NonEmptyStr
    report_locations: dict[str, NonEmptyStr] = Field(default_factory=dict)
    metrics: dict[str, JsonValue] = Field(default_factory=dict)


class NautilusRunner(Protocol):
    """The only canonical runtime boundary for execution flows."""

    def run(self, run_spec: BacktestRunSpec) -> NautilusRunArtifacts:
        """Execute one canonical run spec through Nautilus."""
        ...


@dataclass(frozen=True)
class BacktestNodeNautilusRunner:
    """Execute compiled run specs through Nautilus `BacktestNode`."""

    compiler: NautilusRunSpecCompiler
    report_writer: NautilusReportWriter

    def run(self, run_spec: BacktestRunSpec) -> NautilusRunArtifacts:
        compiled = self.compiler.compile(run_spec)
        compiled.runtime_root.mkdir(parents=True, exist_ok=True)
        compiled.artifact_root.mkdir(parents=True, exist_ok=True)
        run_spec_path = compiled.runtime_root / "compiled_run_spec.json"
        run_spec_path.write_text(compiled.model_dump_json(indent=2), encoding="utf-8")
        config = _build_backtest_run_config(compiled)
        try:
            from nautilus_trader.backtest.node import BacktestNode
        except Exception as exc:
            raise InfrastructureError("failed to import Nautilus BacktestNode") from exc

        node = BacktestNode(configs=[config])
        started = perf_counter()
        try:
            [run_result] = node.run()
            engine = node.get_engine(config.id)
            if engine is None:
                raise InfrastructureError(
                    "nautilus backtest completed but engine could not be retrieved",
                    run_id=compiled.run_id,
                    run_config_id=str(config.id),
                )
            return self.report_writer.persist(
                compiled_spec=compiled,
                run_result=run_result,
                engine=engine,
                runtime_sec=perf_counter() - started,
                run_spec_path=run_spec_path,
            )
        except InfrastructureError:
            raise
        except Exception as exc:
            raise InfrastructureError(
                "nautilus backtest execution failed",
                run_id=compiled.run_id,
                dataset_id=compiled.dataset_id,
            ) from exc
        finally:
            node.dispose()


def _build_backtest_run_config(compiled: NautilusRunSpec) -> BacktestRunConfig:
    from nautilus_trader.backtest.config import BacktestDataConfig
    from nautilus_trader.backtest.config import BacktestEngineConfig
    from nautilus_trader.backtest.config import BacktestRunConfig
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.model import Bar

    venue_configs = [_build_venue_config(venue) for venue in compiled.venues]
    data_configs = [
        BacktestDataConfig(
            catalog_path=str(data_spec.catalog_root),
            data_cls=Bar,
            instrument_ids=[data_spec.instrument_id],
            bar_types=[data_spec.bar_type],
            start_time=data_spec.start_time_utc.isoformat(),
            end_time=data_spec.end_time_utc.isoformat(),
        )
        for data_spec in compiled.data
    ]
    strategy_configs = [_build_strategy_config(strategy) for strategy in compiled.strategies]
    return BacktestRunConfig(
        venues=venue_configs,
        data=data_configs,
        engine=BacktestEngineConfig(
            logging=LoggingConfig(log_level="ERROR"),
            strategies=strategy_configs,
        ),
        dispose_on_completion=False,
        raise_exception=True,
    )


def _build_strategy_config(strategy: NautilusStrategySpec) -> ImportableStrategyConfig:
    from nautilus_trader.config import ImportableStrategyConfig

    return ImportableStrategyConfig(
        strategy_path=strategy.strategy_path,
        config_path=strategy.config_path,
        config=dict(strategy.config),
    )


def _build_venue_config(venue: NautilusVenueSpec):
    from nautilus_trader.backtest.config import BacktestVenueConfig

    fill_model = (
        _build_fill_model_config(venue.fill_model) if venue.fill_model is not None else None
    )
    fee_model = _build_fee_model_config(venue.fee_model) if venue.fee_model is not None else None
    return BacktestVenueConfig(
        name=venue.name,
        oms_type=venue.oms_type,
        account_type=venue.account_type,
        base_currency=venue.base_currency,
        starting_balances=list(venue.starting_balances),
        book_type=venue.book_type,
        fill_model=fill_model,
        fee_model=fee_model,
    )


def _build_fill_model_config(model: NautilusImportableModelSpec):
    from nautilus_trader.backtest.config import ImportableFillModelConfig

    return ImportableFillModelConfig(
        fill_model_path=model.model_path,
        config_path=model.config_path,
        config=dict(model.config),
    )


def _build_fee_model_config(model: NautilusImportableModelSpec):
    from nautilus_trader.backtest.config import ImportableFeeModelConfig

    return ImportableFeeModelConfig(
        fee_model_path=model.model_path,
        config_path=model.config_path,
        config=dict(model.config),
    )


__all__ = ["BacktestNodeNautilusRunner", "NautilusRunArtifacts", "NautilusRunner"]
