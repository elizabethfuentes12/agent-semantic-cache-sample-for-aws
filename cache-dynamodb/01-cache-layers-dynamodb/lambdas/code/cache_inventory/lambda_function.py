"""DynamoDB cache inventory — stats and flush.

Handles two actions:
  {"action": "cache_stats"} — count items per entry_type via GSI Query
  {"action": "flush"}       — delete all items via paginated Scan + BatchWriteItem
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
ENTRY_TYPE_GSI_NAME = os.environ["ENTRY_TYPE_GSI_NAME"]

_ddb = None

ENTRY_TYPES = ["response", "plan", "tool_result"]


def _client():
    global _ddb
    if _ddb is None:
        _ddb = boto3.client("dynamodb")
    return _ddb


def _stats() -> dict:
    """Count items per entry_type using the GSI."""
    ddb = _client()
    counts = {}
    for entry_type in ENTRY_TYPES:
        resp = ddb.query(
            TableName=TABLE_NAME,
            IndexName=ENTRY_TYPE_GSI_NAME,
            KeyConditionExpression="entry_type = :t",
            ExpressionAttributeValues={":t": {"S": entry_type}},
            Select="COUNT",
        )
        counts[entry_type] = resp["Count"]
    return counts


def _flush() -> int:
    """Delete all items via paginated Scan + BatchWriteItem. Returns deleted count."""
    ddb = _client()
    deleted = 0
    exclusive_start_key = None

    while True:
        scan_kwargs = {
            "TableName": TABLE_NAME,
            "ProjectionExpression": "entry_id",
        }
        if exclusive_start_key:
            scan_kwargs["ExclusiveStartKey"] = exclusive_start_key

        resp = ddb.scan(**scan_kwargs)
        items = resp.get("Items", [])

        # BatchWriteItem handles up to 25 items per call
        for i in range(0, len(items), 25):
            batch = items[i:i + 25]
            ddb.batch_write_item(
                RequestItems={
                    TABLE_NAME: [
                        {"DeleteRequest": {"Key": {"entry_id": item["entry_id"]}}}
                        for item in batch
                    ]
                }
            )
            deleted += len(batch)

        exclusive_start_key = resp.get("LastEvaluatedKey")
        if not exclusive_start_key:
            break

    return deleted


def lambda_handler(event, context):
    action = event.get("action")
    if action not in ("cache_stats", "flush"):
        return {"statusCode": 400, "error": f"Invalid action: {action}"}

    try:
        if action == "cache_stats":
            return {"statusCode": 200, "counts": _stats()}
        else:
            deleted = _flush()
            return {"statusCode": 200, "deleted": deleted}
    except Exception:
        logger.exception("cache inventory failed for action=%s", action)
        return {"statusCode": 500, "error": "cache inventory failed"}
