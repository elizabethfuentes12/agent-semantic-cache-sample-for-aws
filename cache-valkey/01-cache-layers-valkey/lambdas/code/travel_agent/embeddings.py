"""Embedding utility — Amazon Titan Text Embeddings V2 via Bedrock."""

import json
import os
import struct

import boto3

# Titan Text Embeddings V2 outputs 1024 dimensions; the FT.CREATE schema
# DIM must match this exactly.
VECTOR_DIM = 1024

_bedrock = None


def _client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


def generate_embedding(text: str) -> list:
    response = _client().invoke_model(
        modelId=os.environ["EMBEDDING_MODEL_ID"],
        body=json.dumps({"inputText": text, "dimensions": VECTOR_DIM}),
    )
    return json.loads(response["body"].read())["embedding"]


def embedding_to_bytes(embedding: list) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)
