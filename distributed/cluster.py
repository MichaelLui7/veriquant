"""Ray cluster bootstrap and resource probe."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable inside Ray workers (which import this module
# and the core_engine/strategies packages it depends on).
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import ray  # noqa: E402


def init_cluster(num_cpus: int | None = None, **kwargs):
    """Initialize a local Ray cluster (idempotent) and return its resources."""
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True, num_cpus=num_cpus, **kwargs)
    return ray.cluster_resources()


def cluster_info() -> dict:
    """Return a small resource/health probe for logging and tests."""
    nodes = ray.nodes()
    return {
        "num_nodes": len(nodes),
        "resources": ray.cluster_resources(),
        "available_resources": ray.available_resources(),
    }


def shutdown():
    if ray.is_initialized():
        ray.shutdown()
