"""Annualization-policy helpers shared by analytics code."""

from __future__ import annotations

import re


_ANNUALIZATION_POLICY_PATTERN = re.compile(r"^(?P<days>[1-9][0-9]*)d$")


def resolve_annualization_factor(annualization_policy: str) -> float:
    """Return the yearly scaling factor implied by one policy string."""

    normalized = annualization_policy.strip().lower()
    match = _ANNUALIZATION_POLICY_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("annualization_policy must use '<days>d' format such as '252d' or '365d'")
    return float(int(match.group("days")))


__all__ = ["resolve_annualization_factor"]
