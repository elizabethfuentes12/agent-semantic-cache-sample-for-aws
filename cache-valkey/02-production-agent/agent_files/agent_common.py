"""Shared plumbing for the reasoning-cache demo agents.

Kept separate from production_agent.py so the existing production runtime
is untouched. Each demo agent reports the SAME honest metrics contract:

    usage            tokens actually spent this invocation
    overhead_tokens  tokens spent building/adapting cached reasoning
    tokens_saved     cold-baseline minus (usage + overhead), floor 0
    flow             ordered cache touchpoints for the dashboard timeline

The budget-matched caveat (arXiv:2606.15017) is the reason overhead_tokens
exists: savings that ignore memory-building costs don't survive scrutiny.
"""

import json
import logging
import re

import boto3

logger = logging.getLogger(__name__)

PARAM_PREFIX = "/semantic-cache"

_params = None
_node_client = None
_tool_client = None
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
        missing = {"valkey-host", "valkey-port", "tool-cache-host",
                   "tool-cache-port", "agent-model-id"} - params.keys()
        if missing:
            raise RuntimeError(f"SSM contract incomplete, missing: {missing}")
        _params = params
        os.environ.setdefault("EMBEDDING_MODEL_ID", params["embedding-model-id"])
        os.environ.setdefault("DUFFEL_SECRET_ARN", params["duffel-secret-arn"])
    return _params


def get_clients():
    """(node_based_client, serverless_tool_client) — lazy, shared."""
    global _node_client, _tool_client
    if _node_client is None:
        import valkey

        params = get_params()
        conf = dict(ssl=True, ssl_cert_reqs="required", decode_responses=False,
                    socket_timeout=5, socket_connect_timeout=5)
        _node_client = valkey.Valkey(
            host=params["valkey-host"], port=int(params["valkey-port"]), **conf)
        _tool_client = valkey.Valkey(
            host=params["tool-cache-host"], port=int(params["tool-cache-port"]), **conf)
    return _node_client, _tool_client


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


def knn_lookup(client, index: str, question: str, threshold: float) -> tuple[str | None, float]:
    """Shared KNN: returns (entry_id, similarity) above threshold or (None, best)."""
    from embeddings import embedding_to_bytes, generate_embedding

    query_vec = embedding_to_bytes(generate_embedding(question))
    result = client.execute_command(
        "FT.SEARCH", index,
        "*=>[KNN 1 @embedding $vec AS score]",
        "PARAMS", "2", "vec", query_vec,
        "RETURN", "2", "entry_id", "score",
        "DIALECT", "2",
    )
    if not result or int(result[0]) == 0:
        return None, 0.0
    fields = result[2]
    doc = {}
    for i in range(0, len(fields), 2):
        k = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
        v = fields[i + 1].decode() if isinstance(fields[i + 1], bytes) else fields[i + 1]
        doc[k] = v
    similarity = 1.0 - (float(doc["score"]) / 2.0)
    if similarity < threshold:
        return None, similarity
    return doc["entry_id"], similarity


def store_vector(client, index_prefix: str, entry_id: str, question: str, ttl: int) -> None:
    import time

    from embeddings import embedding_to_bytes, generate_embedding

    client.hset(f"{index_prefix}{entry_id}", mapping={
        "embedding": embedding_to_bytes(generate_embedding(question)),
        "entry_id": entry_id,
        "timestamp": str(time.time()),
    })
    client.expire(f"{index_prefix}{entry_id}", ttl)


def ensure_vector_index(client, index: str, prefix: str) -> None:
    from valkey.exceptions import ResponseError

    from embeddings import VECTOR_DIM

    try:
        client.execute_command(
            "FT.CREATE", index, "ON", "HASH", "PREFIX", "1", prefix,
            "SCHEMA", "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", str(VECTOR_DIM),
            "DISTANCE_METRIC", "COSINE", "entry_id", "TAG",
        )
    except ResponseError as e:
        if "already exists" not in str(e).lower():
            raise


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
