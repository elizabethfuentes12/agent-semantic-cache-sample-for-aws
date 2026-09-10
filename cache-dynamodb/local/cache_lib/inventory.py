"""Cache inventory: count items per kind, flush the table.

The table has no per-kind GSI (the vector index only filters KNN searches), so
counts use a scan with a filter. Fine for a demo with a handful of items.
"""

import time

import boto3

from cache_lib.config import CacheConfig


def _ddb(cfg: CacheConfig):
    return boto3.client("dynamodb", region_name=cfg.region)


def _count(ddb, table: str, kind: str) -> int:
    count, start = 0, None
    while True:
        kw = {"TableName": table, "Select": "COUNT",
              "FilterExpression": "kind = :k",
              "ExpressionAttributeValues": {":k": {"S": kind}}}
        if start:
            kw["ExclusiveStartKey"] = start
        resp = ddb.scan(**kw)
        count += resp.get("Count", 0)
        start = resp.get("LastEvaluatedKey")
        if not start:
            return count


def cache_stats(cfg: CacheConfig) -> dict:
    """Count items per kind. Returns named counts plus a total."""
    ddb = _ddb(cfg)
    counts = {k: _count(ddb, cfg.table_name, k) for k in cfg.all_kinds}
    # friendly aliases the UI expects
    out = {
        "response": counts.get("answer", 0),
        "trajectory": counts.get("trajectory", 0),
        "tool_result": counts.get("tool_result", 0),
    }
    out["total"] = sum(out.values())
    return out


def flush_all(cfg: CacheConfig) -> int:
    """Delete every item via paginated Scan + BatchWriteItem, retrying any
    UnprocessedItems. Returns the number of items deleted."""
    ddb = _ddb(cfg)
    deleted = 0
    start = None
    while True:
        kw = {"TableName": cfg.table_name, "ProjectionExpression": "entry_id"}
        if start:
            kw["ExclusiveStartKey"] = start
        resp = ddb.scan(**kw)
        items = resp.get("Items", [])
        for i in range(0, len(items), 25):
            batch = [{"DeleteRequest": {"Key": {"entry_id": it["entry_id"]}}}
                     for it in items[i:i + 25]]
            request = {cfg.table_name: batch}
            # retry UnprocessedItems with a short backoff
            for attempt in range(5):
                result = ddb.batch_write_item(RequestItems=request)
                unprocessed = result.get("UnprocessedItems", {})
                done = len(request[cfg.table_name]) - len(unprocessed.get(cfg.table_name, []))
                deleted += done
                if not unprocessed:
                    break
                request = unprocessed
                time.sleep(0.1 * (attempt + 1))
        start = resp.get("LastEvaluatedKey")
        if not start:
            break
    return deleted
