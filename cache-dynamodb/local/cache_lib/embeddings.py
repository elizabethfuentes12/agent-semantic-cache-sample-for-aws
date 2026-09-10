"""Embedding utility - Amazon Titan Text Embeddings V2 via Amazon Bedrock.

Titan V2 is multilingual, which is why a question asked in Spanish can hit an
answer cached in English (measured ~0.93 cosine in the full sample).
"""

import json

import boto3

from cache_lib.config import VECTOR_DIM

_clients: dict = {}


def _client(region: str):
    if region not in _clients:
        _clients[region] = boto3.client("bedrock-runtime", region_name=region)
    return _clients[region]


def generate_embedding(text: str, model_id: str, region: str) -> list:
    """Return a 1024-dim embedding for ``text`` using Titan V2."""
    response = _client(region).invoke_model(
        modelId=model_id,
        body=json.dumps({"inputText": text, "dimensions": VECTOR_DIM}),
    )
    return json.loads(response["body"].read())["embedding"]


def to_ddb_vector(embedding: list) -> list:
    """Convert a float list to the DynamoDB SearchVector / L attribute format.

    DynamoDB vector search wants a plain list of ``{"N": "float_str"}`` - this
    same shape works both as the SearchVector argument and as an ``L`` attribute
    value when storing the embedding on an item.
    """
    return [{"N": str(v)} for v in embedding]


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Plain cosine similarity between two float lists (0-1 for these vectors)."""
    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    norm = (sum(x * x for x in vec_a) ** 0.5) * (sum(y * y for y in vec_b) ** 0.5)
    return dot / norm if norm else 0.0
