"""Configuration for the local DynamoDB cache demo.

One dataclass drives everything: the region, table, models, and thresholds.
No SSM, no hidden globals. This mirrors the schema the notebook builds: a single
table whose vector index is filtered by a ``kind`` attribute.
"""

from dataclasses import dataclass

# Titan Text Embeddings V2 outputs 1024 dimensions. The vector index
# ``Dimensions`` MUST match this exactly, so it is not user-configurable here.
VECTOR_DIM = 1024

# kind values - one table holds every cache pattern, distinguished by this
# attribute, which is also an INLINE_FILTER on the vector index.
KIND_ANSWER = "answer"          # response cache: question -> answer (has embedding)
KIND_TRAJECTORY = "trajectory"  # reasoning cache: question -> tool plan (has embedding)
KIND_TOOL = "tool_result"       # tool-result cache: exact (tool, args) -> result (no embedding)

# Per-tool cache TTLs by data volatility (seconds).
TOOL_TTL_SECONDS = {
    "geocode_destination": 30 * 24 * 3600,  # coordinates: effectively immutable
    "climate_summary": 7 * 24 * 3600,       # historical climate: monthly refresh
    "wikipedia_summary": 24 * 3600,         # policies change without notice
    "search_flights": 300,                  # prices: volatile, minutes only
}
DEFAULT_TOOL_TTL = 3600
NEGATIVE_TTL_SECONDS = 300      # results that succeeded but found nothing


@dataclass
class CacheConfig:
    """All knobs for the local cache demo, with demo-safe defaults.

    Attributes:
        region: AWS region. Bedrock Nova Lite + Titan V2 must be enabled here.
        table_name: DynamoDB table that holds every cache pattern.
        vector_index_name: Native vector index for KNN lookups.
        agent_model_id: Bedrock model the agent generates with.
        embedding_model_id: Bedrock model for Titan embeddings (1024-dim).
        similarity_threshold: Cosine similarity a hit must meet (0-1).
        response_ttl_seconds: TTL for cached answers (response cache).
        trajectory_ttl_seconds: TTL for cached tool plans (reasoning cache).
    """

    region: str = "us-east-1"
    table_name: str = "agent-cache-dynamodb-local"
    vector_index_name: str = "embedding-index"

    agent_model_id: str = "us.amazon.nova-lite-v1:0"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    # Cross-language rewrite on a cache hit uses a cheap model (the answer is
    # already verified, so this is only a translation, not research).
    rewrite_model_id: str = "us.amazon.nova-lite-v1:0"
    rewrite_on_hit: bool = True

    similarity_threshold: float = 0.85
    response_ttl_seconds: int = 86400
    trajectory_ttl_seconds: int = 86400

    # Every kind stored in the table (for inventory counts).
    all_kinds: tuple = (KIND_ANSWER, KIND_TRAJECTORY, KIND_TOOL)
