"""Shared plumbing for the DynamoDB reasoning-cache demo agents.

Replaces the Valkey-based agent_common.py. The Valkey client pair
(node_based_client, serverless_tool_client) is replaced by a single
boto3 DynamoDB client — no split-store needed because DynamoDB handles
both vector search and exact-match KV in one table.

SSM contract prefix: /dynamodb-cache/  (Valkey used /semantic-cache/)
Required SSM params:
  table-name            DynamoDB table for all cache patterns
  vector-index-name     Vector index name (embedding-index)
  entry-type-gsi-name   GSI for per-pattern queries (entry-type-index)
  agent-model-id        Bedrock model ID for the agent
  embedding-model-id    Bedrock model ID for Titan embeddings
  duffel-secret-arn     Secrets Manager ARN for the Duffel API key

Each demo agent reports the same honest metrics contract:
    usage            tokens actually spent this invocation
    overhead_tokens  tokens spent building/adapting cached reasoning
    tokens_saved     cold-baseline minus (usage + overhead), floor 0
    flow             ordered cache touchpoints for the dashboard timeline

Budget-matched caveat (arXiv:2606.15017): overhead_tokens exists because
savings that ignore memory-building costs don't survive scrutiny.
"""

import json
import logging
import re

import boto3

logger = logging.getLogger(__name__)

PARAM_PREFIX = "/dynamodb-cache"

_params = None
_ddb_client = None
_model = None


def get_params() -> dict:
    global _params
    if _params is None:
        import os

        ssm = boto3.client("ssm")
        params = {}
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=PARAM_PREFIX, Recursive=True):
            for p in page["Parameters"]:
                params[p["Name"].removeprefix(f"{PARAM_PREFIX}/")] = p["Value"]
        missing = {"table-name", "vector-index-name", "entry-type-gsi-name",
                   "agent-model-id"} - params.keys()
        if missing:
            raise RuntimeError(f"SSM contract incomplete, missing: {missing}")
        _params = params
        os.environ.setdefault("EMBEDDING_MODEL_ID", params.get("embedding-model-id", ""))
        os.environ.setdefault("DUFFEL_SECRET_ARN", params.get("duffel-secret-arn", ""))
    return _params


def get_ddb_client():
    """Lazy singleton DynamoDB client. Replaces get_clients() from Valkey version."""
    global _ddb_client
    if _ddb_client is None:
        _ddb_client = boto3.client("dynamodb")
    return _ddb_client


def get_model():
    global _model
    if _model is None:
        from strands.models import BedrockModel
        _model = BedrockModel(model_id=get_params()["agent-model-id"])
    return _model


def parse_json_block(text: str):
    """Parse JSON that models often wrap in ```json fences or prose."""
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def clean_answer(text: str) -> str:
    if "<answer>" in text:
        text = text.split("<answer>", 1)[1].split("</answer>", 1)[0]
    return re.sub(r"<thinking>.*?(</thinking>|$)", "", text, flags=re.S).strip()


def llm_call(system: str, prompt: str) -> tuple[str, int]:
    """One-shot model call outside the agent loop. Returns (text, tokens)."""
    from strands import Agent

    agent = Agent(model=get_model(), system_prompt=system)
    result = agent(prompt)
    return clean_answer(str(result)), dict(result.metrics.accumulated_usage).get("totalTokens", 0)


def knn_lookup(question: str, entry_type: str, threshold: float,
               top_k: int = 1) -> tuple[str | None, float]:
    """Shared DynamoDB KNN lookup.

    Returns (entry_id, similarity) for the best result above threshold,
    or (None, best_similarity) on a miss.

    Replaces the Valkey FT.SEARCH-based knn_lookup(client, index, ...).
    """
    from embeddings import generate_embedding

    params = get_params()
    ddb = get_ddb_client()
    qvec = [{"N": str(v)} for v in generate_embedding(question)]
    try:
        resp = ddb.search_vectors(
            TableName=params["table-name"],
            IndexName=params["vector-index-name"],
            SearchVector=qvec,
            TopK=top_k,
            SearchConditionExpression="entry_type = :et",
            ExpressionAttributeValues={":et": {"S": entry_type}},
        )
    except Exception:
        logger.exception("knn_lookup failed")
        return None, 0.0

    results = resp.get("SearchResults", [])
    if not results:
        return None, 0.0

    score = results[0]["Score"]
    similarity = 1.0 - (score / 2.0)
    if similarity < threshold:
        return None, similarity

    entry_id = results[0]["Item"].get("entry_id", {}).get("S", "")
    return entry_id, similarity


def store_vector(question: str, entry_id: str, entry_type: str,
                 extra_attrs: dict, ttl: int) -> None:
    """Store an item with a vector embedding in the DynamoDB cache table.

    Replaces Valkey store_vector(client, index_prefix, entry_id, question, ttl).

    extra_attrs: dict of DynamoDB attribute dicts to merge into the item,
    e.g. {"template": {"S": "..."}, "cold_tokens": {"N": "1234"}}.
    """
    import time as _time

    from embeddings import generate_embedding

    params = get_params()
    ddb = get_ddb_client()
    item = {
        "entry_id":   {"S": entry_id},
        "entry_type": {"S": entry_type},
        "question":   {"S": question},
        "created_at": {"N": str(int(_time.time()))},
        "ttl":        {"N": str(int(_time.time()) + ttl)},
        "embedding":  {"L": [{"N": str(v)} for v in generate_embedding(question)]},
    }
    item.update(extra_attrs)
    try:
        ddb.put_item(TableName=params["table-name"], Item=item)
    except Exception:
        logger.exception("store_vector failed for entry_id=%s", entry_id)


def ensure_vector_index(*args, **kwargs) -> None:
    """No-op: the DynamoDB vector index is created at deploy time by CDK.

    Replaces Valkey ensure_vector_index(client, index, prefix).
    Kept for API compatibility with agents that call it at startup.
    """


def response_payload(answer: str, usage: dict, overhead: int, baseline: int,
                     flow: list, started: float, extra: dict | None = None) -> dict:
    import time

    spent = usage.get("totalTokens", 0)
    saved = max(0, baseline - spent - overhead) if baseline else 0
    payload = {
        "answer": answer,
        "result": answer,
        "usage": usage,
        "overhead_tokens": overhead,
        "tokens_saved": saved,
        "flow": flow,
        "latency_ms": int((time.time() - started) * 1000),
    }
    if extra:
        payload.update(extra)
    logger.info(json.dumps({k: v for k, v in payload.items() if k not in ("answer", "result")}))
    return payload
