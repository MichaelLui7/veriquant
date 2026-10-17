"""Zero-copy shared market data via Ray's Plasma object store.

The price matrix is ``ray.put`` once; workers are handed the *same* object. When
the scheduler passes the resulting ObjectRef to a task, Ray auto-dereferences it
and — for same-node objects — gives the worker a read-only shared-memory view, so
the array is never serialized/deserialized per task. This is what makes the grid
search scale near-linearly instead of being dominated by data shipping.
"""

from __future__ import annotations

import numpy as np
import ray


class SharedPrices:
    """Store a read-only price matrix once in the object store."""

    def __init__(self, prices: np.ndarray) -> None:
        arr = np.ascontiguousarray(prices, dtype=np.float64)
        self.ref = ray.put(arr)
        self.shape = arr.shape

    @property
    def object_ref(self):
        return self.ref

    def get(self) -> np.ndarray:
        return ray.get(self.ref)


def put(prices: np.ndarray):
    """Thin functional helper mirroring the doc's ``ray.put`` idiom."""
    return ray.put(np.ascontiguousarray(prices, dtype=np.float64))
