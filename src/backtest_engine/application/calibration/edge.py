"""Local EDGE bid-ask spread estimator used by offline calibration.

The implementation follows the public EDGE reference behavior from
``eguidotti/bidask``:

- Ardia, Guidotti, and Kroencke (2024), Journal of Financial Economics.
- Reference project: https://github.com/eguidotti/bidask
- Upstream code license for the reference implementation: MIT, copyright
  (c) 2024 Emanuele Guidotti. See ``docs/THIRD_PARTY_NOTICES.md``.

The estimator returns a full effective spread fraction. A value of ``0.01``
means a 1% full spread. Calibration code may request signed estimates and
decide how to handle negative small-sample outputs; runtime execution code must
not call this module directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Sequence


EdgeInvalidReason = Literal[
    "n_lt_3",
    "length_mismatch",
    "non_finite_input",
    "non_positive_price",
    "invalid_ohlc",
    "nt_lt_2",
    "po_zero",
    "pc_zero",
    "non_finite_output",
]


@dataclass(frozen=True)
class EdgeEstimate:
    """Diagnostic EDGE estimate for one OHLC window."""

    full_spread_frac: float | None
    invalid_reason: EdgeInvalidReason | None = None

    @property
    def valid(self) -> bool:
        """Return whether the window produced a finite EDGE estimate."""

        return self.invalid_reason is None and self.full_spread_frac is not None


def edge_spread(
    open_: Sequence[float | int],
    high: Sequence[float | int],
    low: Sequence[float | int],
    close: Sequence[float | int],
    *,
    signed: bool = False,
) -> float:
    """Return the EDGE full-spread fraction or ``nan`` for invalid windows.

    This mirrors the public ``bidask.edge`` API shape closely enough for local
    parity tests while keeping dependency ownership inside calibration. Length
    mismatches raise ``ValueError``; estimator-invalid windows return ``nan``.
    """

    estimate = estimate_edge_spread(open_, high, low, close, signed=signed)
    if estimate.invalid_reason == "length_mismatch":
        raise ValueError("open, high, low, close must have the same length")
    if estimate.full_spread_frac is None:
        return math.nan
    return estimate.full_spread_frac


def estimate_edge_spread(
    open_: Sequence[float | int],
    high: Sequence[float | int],
    low: Sequence[float | int],
    close: Sequence[float | int],
    *,
    signed: bool = False,
) -> EdgeEstimate:
    """Return a diagnostic EDGE estimate for one sorted OHLC price window."""

    if len(high) != len(open_) or len(low) != len(open_) or len(close) != len(open_):
        return EdgeEstimate(full_spread_frac=None, invalid_reason="length_mismatch")

    nobs = len(open_)
    if nobs < 3:
        return EdgeEstimate(full_spread_frac=None, invalid_reason="n_lt_3")

    open_values = _coerce_price_vector(open_)
    high_values = _coerce_price_vector(high)
    low_values = _coerce_price_vector(low)
    close_values = _coerce_price_vector(close)
    all_values = open_values + high_values + low_values + close_values
    if not all(math.isfinite(value) for value in all_values):
        return EdgeEstimate(full_spread_frac=None, invalid_reason="non_finite_input")
    if any(value <= 0.0 for value in all_values):
        return EdgeEstimate(full_spread_frac=None, invalid_reason="non_positive_price")
    if (
        first_invalid_ohlc_shape_index(open_values, high_values, low_values, close_values)
        is not None
    ):
        return EdgeEstimate(full_spread_frac=None, invalid_reason="invalid_ohlc")

    open_log = [math.log(value) for value in open_values]
    high_log = [math.log(value) for value in high_values]
    low_log = [math.log(value) for value in low_values]
    close_log = [math.log(value) for value in close_values]
    midpoint_log = [
        (high_value + low_value) / 2.0 for high_value, low_value in zip(high_log, low_log)
    ]

    h1 = high_log[:-1]
    l1 = low_log[:-1]
    c1 = close_log[:-1]
    m1 = midpoint_log[:-1]
    open_log = open_log[1:]
    high_log = high_log[1:]
    low_log = low_log[1:]
    midpoint_log = midpoint_log[1:]

    r1 = [m_value - o_value for m_value, o_value in zip(midpoint_log, open_log)]
    r2 = [o_value - m1_value for o_value, m1_value in zip(open_log, m1)]
    r3 = [m_value - c1_value for m_value, c1_value in zip(midpoint_log, c1)]
    r4 = [c1_value - m1_value for c1_value, m1_value in zip(c1, m1)]
    r5 = [o_value - c1_value for o_value, c1_value in zip(open_log, c1)]

    tau = [
        1.0 if h_value != l_value or l_value != c1_value else 0.0
        for h_value, l_value, c1_value in zip(high_log, low_log, c1)
    ]
    po1 = [
        tau_value * (1.0 if o_value != h_value else 0.0)
        for tau_value, o_value, h_value in zip(tau, open_log, high_log)
    ]
    po2 = [
        tau_value * (1.0 if o_value != l_value else 0.0)
        for tau_value, o_value, l_value in zip(tau, open_log, low_log)
    ]
    pc1 = [
        tau_value * (1.0 if c1_value != h1_value else 0.0)
        for tau_value, c1_value, h1_value in zip(tau, c1, h1)
    ]
    pc2 = [
        tau_value * (1.0 if c1_value != l1_value else 0.0)
        for tau_value, c1_value, l1_value in zip(tau, c1, l1)
    ]

    pt = _mean(tau)
    po = _mean(po1) + _mean(po2)
    pc = _mean(pc1) + _mean(pc2)

    nt = sum(tau)
    if nt < 2:
        return EdgeEstimate(full_spread_frac=None, invalid_reason="nt_lt_2")
    if po == 0.0:
        return EdgeEstimate(full_spread_frac=None, invalid_reason="po_zero")
    if pc == 0.0:
        return EdgeEstimate(full_spread_frac=None, invalid_reason="pc_zero")

    d1 = [value - _mean(r1) / pt * tau_value for value, tau_value in zip(r1, tau)]
    d3 = [value - _mean(r3) / pt * tau_value for value, tau_value in zip(r3, tau)]
    d5 = [value - _mean(r5) / pt * tau_value for value, tau_value in zip(r5, tau)]

    x1 = [
        -4.0 / po * d1_value * r2_value + -4.0 / pc * d3_value * r4_value
        for d1_value, r2_value, d3_value, r4_value in zip(d1, r2, d3, r4)
    ]
    x2 = [
        -4.0 / po * d1_value * r5_value + -4.0 / pc * d5_value * r4_value
        for d1_value, r5_value, d5_value, r4_value in zip(d1, r5, d5, r4)
    ]

    e1 = _mean(x1)
    e2 = _mean(x2)
    v1 = _mean([value * value for value in x1]) - e1 * e1
    v2 = _mean([value * value for value in x2]) - e2 * e2
    vt = v1 + v2
    s2 = (v2 * e1 + v1 * e2) / vt if vt > 0.0 else (e1 + e2) / 2.0

    spread = math.sqrt(abs(s2))
    if signed:
        spread *= _sign(s2)
    if not math.isfinite(spread):
        return EdgeEstimate(full_spread_frac=None, invalid_reason="non_finite_output")
    return EdgeEstimate(full_spread_frac=spread)


def _coerce_price_vector(values: Sequence[float | int]) -> list[float]:
    return [float(value) for value in values]


def first_invalid_ohlc_shape_index(
    open_: Sequence[float | int],
    high: Sequence[float | int],
    low: Sequence[float | int],
    close: Sequence[float | int],
) -> int | None:
    """Return the first index whose OHLC shape is impossible, if any."""

    for index, (open_value, high_value, low_value, close_value) in enumerate(
        zip(open_, high, low, close)
    ):
        if high_value < max(open_value, close_value, low_value):
            return index
        if low_value > min(open_value, close_value, high_value):
            return index
    return None


def _mean(values: Sequence[float]) -> float:
    if not values:
        return math.nan
    return sum(values) / len(values)


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


__all__ = [
    "EdgeEstimate",
    "EdgeInvalidReason",
    "edge_spread",
    "estimate_edge_spread",
    "first_invalid_ohlc_shape_index",
]
