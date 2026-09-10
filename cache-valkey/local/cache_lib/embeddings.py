"""Embedding utility - Amazon Titan Text Embeddings V2 via Amazon Bedrock.

Titan V2 is multilingual, which is why a question asked in Spanish can hit an
answer cached in English. For Valkey vector search the embedding is packed as
FLOAT32 bytes (the format ``FT.CREATE ... TYPE FLOAT32`` expects).
"""

import json
import struct

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


def embedding_to_bytes(embedding: list) -> bytes:
    """Pack a float list as little-endian FLOAT32 bytes for Valkey vectors."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Plain cosine similarity between two float lists."""
    dot = sum(x * y for x, y in zip(vec_a, vec_b))
    norm = (sum(x * x for x in vec_a) ** 0.5) * (sum(y * y for y in vec_b) ** 0.5)
    return dot / norm if norm else 0.0
