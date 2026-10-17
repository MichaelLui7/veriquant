"""Strategy plugin package.

Importing this package registers all bundled strategies into the registry.
"""

from strategies.base import BaseStrategy, get_strategy, register  # noqa: F401
from strategies import ma_crossover  # noqa: F401  (side effect: registers MACrossover)
