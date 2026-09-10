"""cache_lib - a self-contained, notebook-friendly DynamoDB cache demo.

The LOCAL track: no CDK, no SSM, no VPC. One DynamoDB table (single ``kind``
schema) holds three caches, each wired to a Strands agent as a hook:

    ResponseCache      question -> answer      (BeforeInvocation cancel)
    ToolResultCache    (tool,args) -> result   (BeforeToolCall swap)
    ReasoningCache     question -> tool plan   (BeforeInvocation plan hint)

This is the packaged form of what ``01_deploy_and_test.ipynb`` builds inline, so the
notebook and the Streamlit app share one table and one implementation.

Quick start
-----------
>>> from cache_lib import CacheConfig, create_table, CachedTravelAgent
>>> cfg = CacheConfig()
>>> create_table(cfg)                   # one-time, ~30s
>>> agent = CachedTravelAgent(cfg)
>>> agent.ask("Best time to visit Japan and do I need a visa?")
"""

from cache_lib.agent import CachedTravelAgent
from cache_lib.caches import ReasoningCache, ResponseCache, ToolResultCache
from cache_lib.config import CacheConfig
from cache_lib.inventory import cache_stats, flush_all
from cache_lib.table import create_table, delete_table, table_exists

__all__ = [
    "CacheConfig",
    "CachedTravelAgent",
    "ResponseCache",
    "ToolResultCache",
    "ReasoningCache",
    "create_table",
    "delete_table",
    "table_exists",
    "cache_stats",
    "flush_all",
]
