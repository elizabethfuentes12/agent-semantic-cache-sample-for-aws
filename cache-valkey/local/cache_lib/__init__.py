"""cache_lib - a self-contained, notebook-friendly Valkey version of the
semantic + reasoning cache demo.

This is the LOCAL track for Valkey: no CDK, no SSM, no VPC, no ElastiCache.
The vector store is a **local Valkey container** (`valkey/valkey-bundle`, which
ships the `search` module that provides `FT.*` vector commands). Everything is
driven by an explicit ``ValkeyCacheConfig`` instead of SSM Parameter Store.

Bedrock is still real: embeddings (Titan V2) and the agent LLM (Nova Lite) call
Amazon Bedrock. Only the cache infrastructure is local.

Layout
------
config        ValkeyCacheConfig dataclass + defaults (host/port, model ids)
valkey_setup  start the Docker container, connect, create the FT.* indexes
embeddings    Amazon Titan Text Embeddings V2 via Bedrock (float list -> bytes)
tools         travel research tools backed by real public APIs
caches        ResponseCache (level 1) + ToolResultCache + ReasoningCache (level 2)
agent         CachedTravelAgent - one agent, the three cache hooks attached
inventory     count keys per pattern, flush the store

Quick start
-----------
>>> from cache_lib import ValkeyCacheConfig, start_local_valkey, get_client
>>> from cache_lib import ensure_indexes, CachedTravelAgent
>>> cfg = ValkeyCacheConfig()
>>> start_local_valkey(cfg)          # docker run valkey/valkey-bundle
>>> ensure_indexes(get_client(cfg))  # FT.CREATE the HNSW indexes
>>> agent = CachedTravelAgent(cfg)
>>> agent.ask("Best time to visit Japan and do I need a visa?")
"""

from cache_lib.agent import CachedTravelAgent
from cache_lib.caches import ReasoningCache, ResponseCache, ToolResultCache
from cache_lib.config import ValkeyCacheConfig
from cache_lib.inventory import cache_stats, flush_all
from cache_lib.valkey_setup import (
    ensure_indexes,
    get_client,
    start_local_valkey,
    stop_local_valkey,
    supports_ft_search,
)

__all__ = [
    "ValkeyCacheConfig",
    "CachedTravelAgent",
    "ResponseCache",
    "ToolResultCache",
    "ReasoningCache",
    "start_local_valkey",
    "stop_local_valkey",
    "get_client",
    "ensure_indexes",
    "supports_ft_search",
    "cache_stats",
    "flush_all",
]
