"""How learned distributions are stored and sampled.

A distribution (e.g. "days in transit on route SP -> RJ") is stored as its value at fixed
percentiles: the 0th, 5th, 10th ... 90th, then finer steps in the tail, up to the 100th. To draw a
random value, pick a random percentile between 0 and 100 and read the value there, drawing straight
lines between the stored points (inverse-CDF sampling). The finer tail steps matter because late
deliveries live in the tail.
"""

from __future__ import annotations

import numpy as np

PERCENTILE_GRID = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90,
                   92, 94, 96, 97, 98, 99, 99.5, 100]  # fmt: skip


def to_percentiles(values) -> list[float]:
    array = np.asarray(values, dtype=float)
    array = array[~np.isnan(array)]
    if array.size == 0:
        raise ValueError("Cannot learn a distribution from no values")
    return [round(float(value), 4) for value in np.percentile(array, PERCENTILE_GRID)]


def sample(points: list[float], rng: np.random.Generator) -> float:
    return float(np.interp(rng.random() * 100, PERCENTILE_GRID, points))


def to_shares(counts: dict) -> dict[str, float]:
    total = sum(counts.values())
    return {str(key): round(value / total, 6) for key, value in sorted(counts.items(), key=lambda item: str(item[0]))}


def choose(shares: dict[str, float], rng: np.random.Generator) -> str:
    keys = list(shares)
    weights = np.array([shares[key] for key in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=weights / weights.sum()))]
