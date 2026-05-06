"""Load concrete strategy cartridges from ``implementation_id``."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module, invalidate_caches
import re
import sys

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.strategies.package_contracts import StrategyPackageDefinition


_IMPLEMENTATION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_STRATEGY_MODULE_PREFIX = "backtest_engine.strategies."
_SHARED_STRATEGY_MODULES = {"package_contracts", "package_loader"}


def clear_strategy_package_definition_cache() -> None:
    """Clear cached package definitions for test isolation and fresh-process semantics."""

    invalidate_caches()
    _purge_concrete_strategy_modules()
    _load_strategy_package_definition.cache_clear()


def load_strategy_package_definition(implementation_id: str) -> StrategyPackageDefinition:
    """Return the strategy cartridge definition for one implementation id."""

    return _load_strategy_package_definition(implementation_id)


@lru_cache(maxsize=None)
def _load_strategy_package_definition(implementation_id: str) -> StrategyPackageDefinition:
    """Return a cached strategy cartridge definition for one implementation id."""

    _validate_implementation_id(implementation_id)
    package_name = f"backtest_engine.strategies.{implementation_id}"
    module_name = f"backtest_engine.strategies.{implementation_id}.definition"
    try:
        definition_module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name in {package_name, module_name}:
            raise InfrastructureError(
                "strategy package definition could not be imported",
                implementation_id=implementation_id,
                module_name=module_name,
            ) from exc
        raise InfrastructureError(
            "strategy package definition import failed due to missing dependency",
            implementation_id=implementation_id,
            module_name=module_name,
            missing_module=exc.name,
        ) from exc
    except ImportError as exc:
        raise InfrastructureError(
            "strategy package definition import failed",
            implementation_id=implementation_id,
            module_name=module_name,
            error_type=type(exc).__name__,
            error_message=str(exc),
        ) from exc
    except Exception as exc:
        raise InfrastructureError(
            "strategy package definition import failed",
            implementation_id=implementation_id,
            module_name=module_name,
            error_type=type(exc).__name__,
        ) from exc

    definition = getattr(definition_module, "STRATEGY_DEFINITION", None)
    if definition is None:
        raise InfrastructureError(
            "strategy package definition module must export STRATEGY_DEFINITION",
            implementation_id=implementation_id,
            module_name=module_name,
        )
    if not isinstance(definition, StrategyPackageDefinition):
        raise InfrastructureError(
            "strategy package STRATEGY_DEFINITION must be a StrategyPackageDefinition",
            implementation_id=implementation_id,
            module_name=module_name,
            exported_type=type(definition).__name__,
        )
    if definition.implementation_id != implementation_id:
        raise InfrastructureError(
            "strategy package implementation_id does not match folder name",
            implementation_id=implementation_id,
            exported_implementation_id=definition.implementation_id,
            module_name=module_name,
        )
    _validate_runtime_path(
        definition.strategy_path,
        implementation_id=implementation_id,
        path_field="strategy_path",
    )
    _validate_runtime_path(
        definition.config_path,
        implementation_id=implementation_id,
        path_field="config_path",
    )
    return definition


def _validate_implementation_id(implementation_id: str) -> None:
    if _IMPLEMENTATION_ID_PATTERN.fullmatch(implementation_id):
        return
    raise InfrastructureError(
        "strategy implementation_id must match ^[a-z][a-z0-9_]*$",
        implementation_id=implementation_id,
    )


def _validate_runtime_path(
    import_path: str,
    *,
    implementation_id: str,
    path_field: str,
) -> None:
    expected_module = f"backtest_engine.strategies.{implementation_id}.nautilus_strategy"
    module_path, separator, attribute_name = import_path.partition(":")
    if separator and module_path == expected_module and attribute_name:
        _validate_runtime_path_attribute(
            module_path,
            attribute_name,
            implementation_id=implementation_id,
            path_field=path_field,
            import_path=import_path,
        )
        return
    raise InfrastructureError(
        "strategy package runtime path must point at its nautilus_strategy module",
        implementation_id=implementation_id,
        path_field=path_field,
        import_path=import_path,
        expected_module=expected_module,
    )


def _validate_runtime_path_attribute(
    module_path: str,
    attribute_name: str,
    *,
    implementation_id: str,
    path_field: str,
    import_path: str,
) -> None:
    try:
        runtime_module = import_module(module_path)
    except ModuleNotFoundError as exc:
        if exc.name == module_path:
            raise InfrastructureError(
                "strategy package runtime path module could not be imported",
                implementation_id=implementation_id,
                path_field=path_field,
                import_path=import_path,
                module_name=module_path,
            ) from exc
        raise InfrastructureError(
            "strategy package runtime path import failed due to missing dependency",
            implementation_id=implementation_id,
            path_field=path_field,
            import_path=import_path,
            module_name=module_path,
            missing_module=exc.name,
        ) from exc
    except ImportError as exc:
        raise InfrastructureError(
            "strategy package runtime path import failed",
            implementation_id=implementation_id,
            path_field=path_field,
            import_path=import_path,
            module_name=module_path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        ) from exc
    except Exception as exc:
        raise InfrastructureError(
            "strategy package runtime path import failed",
            implementation_id=implementation_id,
            path_field=path_field,
            import_path=import_path,
            module_name=module_path,
            error_type=type(exc).__name__,
        ) from exc
    if getattr(runtime_module, attribute_name, None) is not None:
        return
    raise InfrastructureError(
        "strategy package runtime path attribute does not exist",
        implementation_id=implementation_id,
        path_field=path_field,
        import_path=import_path,
        module_name=module_path,
        attribute_name=attribute_name,
    )


def _purge_concrete_strategy_modules() -> None:
    for module_name in tuple(sys.modules):
        if not module_name.startswith(_STRATEGY_MODULE_PREFIX):
            continue
        relative_name = module_name.removeprefix(_STRATEGY_MODULE_PREFIX)
        strategy_or_module = relative_name.split(".", maxsplit=1)[0]
        if strategy_or_module in _SHARED_STRATEGY_MODULES:
            continue
        sys.modules.pop(module_name, None)


__all__ = [
    "clear_strategy_package_definition_cache",
    "load_strategy_package_definition",
]
