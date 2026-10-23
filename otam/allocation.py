"""Assign complete TAR estimates without counting compression gains."""
from .common import SafetyError


def allocate(sizes: list[int], capacities: list[int]) -> list[int]:
    """Try largest-first best fit, retaining ordered next fit as a fallback.

    Return medium indices in original TAR order. This is a deterministic
    heuristic, not a proof of infeasibility when neither arrangement fits.
    """
    if not capacities or any(size <= 0 for size in sizes):
        raise SafetyError("Invalid complete-TAR allocation")
    remaining = capacities.copy()
    result = [0] * len(sizes)
    for index in sorted(range(len(sizes)), key=lambda i: (-sizes[i], i)):
        choices = [m for m, free in enumerate(remaining) if free >= sizes[index]]
        if not choices:
            break
        medium = min(choices, key=lambda m: (remaining[m] - sizes[index], m))
        result[index] = medium
        remaining[medium] -= sizes[index]
    else:
        return result
    remaining = capacities.copy()
    medium = 0
    for index, size in enumerate(sizes):
        while medium < len(remaining) and remaining[medium] < size:
            medium += 1
        if medium == len(remaining):
            raise SafetyError("Selected media cannot hold every complete TAR with the available allocation")
        result[index] = medium
        remaining[medium] -= size
    return result
