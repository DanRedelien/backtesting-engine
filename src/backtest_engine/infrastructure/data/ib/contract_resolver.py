"""Contract-chain resolution for IB-backed futures source caches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backtest_engine.core.errors import InfrastructureError
from backtest_engine.core.time import ensure_utc
from backtest_engine.core.types import NonEmptyStr, Symbol
from backtest_engine.infrastructure.data.ib.client import IbHistoricalClient
from backtest_engine.infrastructure.data.ib.contracts import IbResolvedContract


# v1 static exchange routing table.  Only CME index futures are
# exercised in v1; the remaining entries support future expansion
# and are kept for documentation purposes.
EXCHANGE_BY_SYMBOL: dict[str, NonEmptyStr] = {
    "ES": "CME",
    "NQ": "CME",
    "RTY": "CME",
    "YM": "CBOT",
    "GC": "COMEX",
    "SI": "COMEX",
    "CL": "NYMEX",
    "NG": "NYMEX",
    "PL": "NYMEX",
    "ZC": "CBOT",
    "6E": "CME",
    "6B": "CME",
    "6J": "CME",
    "6A": "CME",
    "6C": "CME",
    "6S": "CME",
}

# IB uses different ticker symbols for FX futures; this table maps
# the canonical family codes to IB's expected symbols.
IB_SYMBOL_ALIASES: dict[str, NonEmptyStr] = {
    "6E": "EUR",
    "6B": "GBP",
    "6J": "JPY",
    "6A": "AUD",
    "6C": "CAD",
    "6S": "CHF",
}

_QUARTERLY_CODES = frozenset({"H", "M", "U", "Z"})


@dataclass(frozen=True)
class IbContractResolver:
    """Resolve and select the active IB contract for historical backfills."""

    client: IbHistoricalClient

    def resolve_contract_chain(self, symbol: Symbol) -> tuple[IbResolvedContract, ...]:
        """Return one sorted futures chain, preferring quarterly contracts."""

        exchange = EXCHANGE_BY_SYMBOL.get(symbol, "CME")
        ib_symbol = IB_SYMBOL_ALIASES.get(symbol, symbol)
        contracts = self.client.list_contracts(
            symbol=symbol,
            ib_symbol=ib_symbol,
            exchange=exchange,
        )
        if not contracts:
            raise InfrastructureError(
                "IB contract chain is empty",
                symbol=symbol,
                exchange=exchange,
            )

        quarterly = tuple(contract for contract in contracts if _is_quarterly_contract(contract))
        selected = quarterly or contracts
        return tuple(sorted(selected, key=lambda contract: contract.expiry_utc))

    def select_contract(
        self,
        contracts: tuple[IbResolvedContract, ...],
        *,
        target_utc: datetime,
    ) -> IbResolvedContract | None:
        """Return the active contract for one historical timestamp."""

        normalized_target = ensure_utc(target_utc)
        for contract in contracts:
            if contract.expiry_utc > normalized_target:
                return contract
        if not contracts:
            return None
        return contracts[-1]


def _is_quarterly_contract(contract: IbResolvedContract) -> bool:
    return len(contract.local_symbol) >= 3 and contract.local_symbol[2] in _QUARTERLY_CODES


__all__ = ["IB_SYMBOL_ALIASES", "EXCHANGE_BY_SYMBOL", "IbContractResolver"]
