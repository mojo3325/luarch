from __future__ import annotations

import random


def rng_from_seed(seed: int) -> random.Random:
    return random.Random(int(seed))


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
