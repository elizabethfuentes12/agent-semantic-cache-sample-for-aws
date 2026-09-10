"""Cache inventory for the production dashboard.

REQUEST_RESPONSE handler on the AppSync `cache/` namespace. The Valkey stores
are VPC-only, so this function proxies to the stack-01 reasoning Lambda
(which lives in the VPC and already implements the `cache_stats` and `flush`
actions). The function name comes from SSM (`/semantic-cache/reasoning-function-name`).
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_lambda = boto3.client("lambda")
_ssm = boto3.client("ssm")

_fn_name = None

VALID_ACTIONS = {"cache_stats", "flush"}


def _reasoning_fn() -> str:
    global _fn_name
    if _fn_name is None:
        _fn_name = _ssm.get_parameter(
            Name=os.environ["REASONING_FUNCTION_PARAM"]
        )["Parameter"]["Value"]
    return _fn_name


def _response(event_id, payload):
    return {"events": [{"id": event_id, "payload": payload}]}


def lambda_handler(event, context):
    event_id = "unknown"
    try:
        incoming = event["events"][0]
        event_id = incoming.get("id", "unknown")
        payload = incoming["payload"]
        action = payload.get("action")
        if action not in VALID_ACTIONS:
            return _response(event_id, {"statusCode": 400, "error": f"Invalid action: {action}"})

        result = _lambda.invoke(
            FunctionName=_reasoning_fn(),
            Payload=json.dumps({"action": action}).encode(),
        )
        body = json.loads(result["Payload"].read())
        return _response(event_id, {"statusCode": 200, **body})
    except Exception:
        logger.exception("cache inventory failed")
        return _response(event_id, {"statusCode": 500, "error": "cache inventory failed"})
