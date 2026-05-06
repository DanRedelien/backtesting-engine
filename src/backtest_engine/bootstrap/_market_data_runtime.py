"""Market-data bootstrap wiring isolated from the broader application container."""

from __future__ import annotations

from backtest_engine.application.market_data import HistoricalMarketDataService
from backtest_engine.config.settings import PlatformSettings, load_settings
from backtest_engine.infrastructure.data import (
    FilesystemHistoricalDataStore,
    IbHistoricalClient,
    IbHistoricalDataProvider,
    MarketDataValidator,
    Mt5HistoricalDataProvider,
)
from backtest_engine.infrastructure.observability import DiagnosticsSink, NullDiagnosticsSink


def build_market_data_service(
    settings: PlatformSettings | None = None,
    *,
    diagnostics: DiagnosticsSink | None = None,
) -> HistoricalMarketDataService:
    """Build the unified historical market-data service without loading unrelated flows."""

    resolved_settings = settings or load_settings()
    store = FilesystemHistoricalDataStore(source_cache_root=resolved_settings.data.source_cache_root)
    active_diagnostics = diagnostics or NullDiagnosticsSink()
    return HistoricalMarketDataService(
        store=store,
        providers={
            "ib": IbHistoricalDataProvider(
                settings=resolved_settings.data.ib,
                store=store,
                client=IbHistoricalClient(settings=resolved_settings.data.ib),
                symbol_map_path=None,
                diagnostics=active_diagnostics,
            ),
            "mt5": Mt5HistoricalDataProvider(
                settings=resolved_settings.data.mt5,
                store=store,
                symbol_map_path=None,
                diagnostics=active_diagnostics,
            ),
        },
        verifier=MarketDataValidator(store=store),
        diagnostics=active_diagnostics,
    )


__all__ = ["build_market_data_service"]
