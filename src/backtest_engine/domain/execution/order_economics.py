"""Order-type execution economics contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from backtest_engine.core.enums import OrderType


class OrderPriceBehavior(str, Enum):
    """Price-behavior class used by deterministic execution-cost policies."""

    MARKET_LIKE = "market_like"
    LIMIT_LIKE = "limit_like"


class DefaultLiquidityRole(str, Enum):
    """Conservative liquidity role assumed before an explicit policy overrides it."""

    TAKER = "taker"


class OrderExecutionEconomics(BaseModel):
    """Pure order-type classification for future execution-cost calculations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_type: OrderType
    price_behavior: OrderPriceBehavior
    default_liquidity_role: DefaultLiquidityRole
    passive_fill_requires_explicit_policy: bool
    adverse_slippage_allowed: bool
    adverse_price_must_respect_limit: bool

    @property
    def is_market_like(self) -> bool:
        """Return whether this order type behaves like a marketable order."""

        return self.price_behavior is OrderPriceBehavior.MARKET_LIKE

    @property
    def is_limit_like(self) -> bool:
        """Return whether this order type has limit-price protection."""

        return self.price_behavior is OrderPriceBehavior.LIMIT_LIKE


_ORDER_EXECUTION_ECONOMICS: dict[OrderType, OrderExecutionEconomics] = {
    OrderType.MARKET: OrderExecutionEconomics(
        order_type=OrderType.MARKET,
        price_behavior=OrderPriceBehavior.MARKET_LIKE,
        default_liquidity_role=DefaultLiquidityRole.TAKER,
        passive_fill_requires_explicit_policy=False,
        adverse_slippage_allowed=True,
        adverse_price_must_respect_limit=False,
    ),
    OrderType.STOP: OrderExecutionEconomics(
        order_type=OrderType.STOP,
        price_behavior=OrderPriceBehavior.MARKET_LIKE,
        default_liquidity_role=DefaultLiquidityRole.TAKER,
        passive_fill_requires_explicit_policy=False,
        adverse_slippage_allowed=True,
        adverse_price_must_respect_limit=False,
    ),
    OrderType.LIMIT: OrderExecutionEconomics(
        order_type=OrderType.LIMIT,
        price_behavior=OrderPriceBehavior.LIMIT_LIKE,
        default_liquidity_role=DefaultLiquidityRole.TAKER,
        passive_fill_requires_explicit_policy=True,
        adverse_slippage_allowed=False,
        adverse_price_must_respect_limit=True,
    ),
    OrderType.STOP_LIMIT: OrderExecutionEconomics(
        order_type=OrderType.STOP_LIMIT,
        price_behavior=OrderPriceBehavior.LIMIT_LIKE,
        default_liquidity_role=DefaultLiquidityRole.TAKER,
        passive_fill_requires_explicit_policy=True,
        adverse_slippage_allowed=False,
        adverse_price_must_respect_limit=True,
    ),
}


def classify_order_execution(order_type: OrderType | str) -> OrderExecutionEconomics:
    """Return the conservative execution-economics contract for an order type."""

    return _ORDER_EXECUTION_ECONOMICS[OrderType(order_type)]


__all__ = [
    "DefaultLiquidityRole",
    "OrderExecutionEconomics",
    "OrderPriceBehavior",
    "classify_order_execution",
]
