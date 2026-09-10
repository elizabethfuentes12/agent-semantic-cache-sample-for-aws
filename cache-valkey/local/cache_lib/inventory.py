"""Cache inventory - count keys per pattern, flush the store.

Notebook-friendly, returns the same shape (per-pattern counts + total) as the
DynamoDB local track's cache_stats, so the Streamlit app can render either.
"""

from cache_lib.config import (
    PREFIX_SEM_ANS,
    PREFIX_TOOL,
    PREFIX_TRAJ_PLAN,
    ValkeyCacheConfig,
)
from cache_lib.valkey_setup import ensure_indexes, get_client


def _count(client, pattern: str) -> int:
    count, cursor = 0, 0
    while True:
        cursor, batch = client.scan(cursor=cursor, match=pattern, count=200)
        count += len(batch)
        if cursor == 0:
            break
    return count


def cache_stats(cfg: ValkeyCacheConfig) -> dict:
    """Count keys per cache pattern. Returns a dict with named counts + total.

    Keys mirror the DynamoDB track: response / trajectory / tool_result.
    """
    c = get_client(cfg)
    counts = {
        "response": _count(c, f"{PREFIX_SEM_ANS}*"),
        "trajectory": _count(c, f"{PREFIX_TRAJ_PLAN}*"),
        "tool_result": _count(c, f"{PREFIX_TOOL}*"),
    }
    counts["total"] = sum(counts.values())
    return counts


def flush_all(cfg: ValkeyCacheConfig, recreate_indexes: bool = True) -> int:
    """FLUSHDB the store, then recreate the FT.* indexes. Returns keys removed.

    (FLUSHDB drops the indexes too, so they are recreated by default.)
    """
    c = get_client(cfg)
    removed = c.dbsize()
    c.flushdb()
    if recreate_indexes:
        ensure_indexes(c)
    return int(removed)
