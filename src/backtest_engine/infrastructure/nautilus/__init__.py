"""Concrete Nautilus adapters for the rewrite runtime boundary."""

from backtest_engine.infrastructure.nautilus.catalogs import (
    CatalogItem,
    CatalogReference,
    FilesystemNautilusCatalogBuilder,
)
from backtest_engine.infrastructure.nautilus.portfolio_projection import (
    FilesystemPortfolioProjector,
    PortfolioProjection,
    PortfolioProjector,
)
from backtest_engine.infrastructure.nautilus.reports import NautilusReportWriter, RuntimeReportReference
from backtest_engine.infrastructure.nautilus.run_spec_compiler import (
    CanonicalNautilusRunSpecCompiler,
    NautilusDataSpec,
    NautilusRunSpec,
    NautilusRunSpecCompiler,
    NautilusStrategySpec,
    NautilusVenueSpec,
)
from backtest_engine.infrastructure.nautilus.runner import (
    BacktestNodeNautilusRunner,
    NautilusRunArtifacts,
    NautilusRunner,
)
from backtest_engine.infrastructure.nautilus.strategy_package_resolver import (
    PackageBackedNautilusStrategyResolver,
    build_default_nautilus_strategy_resolver,
)
from backtest_engine.infrastructure.nautilus.symbol_map import (
    SymbolMap,
    SymbolMapping,
    default_symbol_map_path,
    load_symbol_map,
)

__all__ = [
    "BacktestNodeNautilusRunner",
    "CanonicalNautilusRunSpecCompiler",
    "CatalogItem",
    "CatalogReference",
    "FilesystemNautilusCatalogBuilder",
    "FilesystemPortfolioProjector",
    "NautilusDataSpec",
    "NautilusReportWriter",
    "NautilusRunArtifacts",
    "NautilusRunSpec",
    "NautilusRunSpecCompiler",
    "NautilusRunner",
    "NautilusStrategySpec",
    "NautilusVenueSpec",
    "PackageBackedNautilusStrategyResolver",
    "PortfolioProjection",
    "PortfolioProjector",
    "RuntimeReportReference",
    "SymbolMap",
    "SymbolMapping",
    "build_default_nautilus_strategy_resolver",
    "default_symbol_map_path",
    "load_symbol_map",
]
