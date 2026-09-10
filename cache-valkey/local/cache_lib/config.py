"""Configuration for the local Valkey cache demo.

One dataclass captures everything: how to reach Valkey (host/port), the Bedrock
model ids, the similarity threshold, and TTLs. No SSM, no env-var dance.
"""

from dataclasses import dataclass

# Titan Text Embeddings V2 outputs 1024 dimensions. The FT.CREATE schema DIM
# must match this exactly, so it is not user-configurable.
VECTOR_DIM = 1024

# Index + key-prefix layout (mirrors the production Valkey track).
# Level 1 - semantic response cache (dual-key: vector index + answer payload)
SEMCACHE_INDEX = "idx:semcache"
PREFIX_SEM_VEC = "semcache:vec:"
PREFIX_SEM_ANS = "semcache:ans:"
# Level 2 - reasoning cache: trajectory (vector) + plan payload + tool results
TRAJ_INDEX = "idx:trajcache"
PREFIX_TRAJ_VEC = "trajcache:vec:"
PREFIX_TRAJ_PLAN = "trajcache:plan:"
PREFIX_TOOL = "toolcache:"
PREFIX_TOOL_STALE = "toolstale:"

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
class ValkeyCacheConfig:
    """All knobs for the local Valkey cache demo, with demo-safe defaults.

    Attributes:
        region: AWS region for Bedrock. Nova Lite + Titan V2 must be enabled.
        host: Valkey host (local container).
        port: Valkey port. Default 6380 to avoid a native Valkey/Redis on 6379.
        container_name: Docker container name the setup helper manages.
        image: Docker image - must include the `search` module (valkey-bundle).
        agent_model_id: Bedrock model the agent generates with.
        embedding_model_id: Bedrock model for Titan embeddings (1024-dim).
        similarity_threshold: Cosine similarity a hit must meet (0-1).
        response_ttl_seconds: TTL for cached answers (level 1).
        trajectory_ttl_seconds: TTL for cached tool plans (level 2).
        duffel_secret_name: Optional Secrets Manager name/ARN for the Duffel
            key. If empty, the demo reads DUFFEL_API_KEY from the environment.
    """

    region: str = "us-east-1"

    host: str = "localhost"
    port: int = 6380
    container_name: str = "valkey-cache-local"
    image: str = "valkey/valkey-bundle:latest"

    agent_model_id: str = "us.amazon.nova-lite-v1:0"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    # Cross-language rewrite on a cache hit uses a cheap model (the answer is
    # already verified, so this is only a translation, not research).
    rewrite_model_id: str = "us.amazon.nova-lite-v1:0"
    rewrite_on_hit: bool = True

    similarity_threshold: float = 0.85
    response_ttl_seconds: int = 86400
    trajectory_ttl_seconds: int = 86400

    duffel_secret_name: str = ""
