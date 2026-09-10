"""Create/delete the DynamoDB agent-cache table with its native vector index.

This is the notebook-friendly replacement for the CDK custom resource. Because
CloudFormation does not support ``VectorIndexes`` in ``AWS::DynamoDB::Table``,
the full sample deploys the table through a Lambda-backed custom resource. Here
we call ``create_table`` directly with boto3.

The schema matches the notebook exactly: primary key ``entry_id``, a vector
index over ``embedding`` filtered by a ``kind`` INLINE_FILTER, and TTL on
``ttl``. There is no GSI; per-kind counts and flush use a scan.

IMPORTANT: ``VectorIndexes`` and ``search_vectors`` require **boto3 >= 1.43.72**.
"""

import boto3

from cache_lib.config import CacheConfig, VECTOR_DIM

MIN_BOTO3 = (1, 43, 72)


def assert_boto3_supports_vectors() -> str:
    """Raise a clear error if boto3 is too old for DynamoDB vector search.

    Returns the detected boto3 version string on success.
    """
    import boto3 as _b

    version = _b.__version__
    parts = tuple(int(p) for p in version.split(".")[:3])
    if parts < MIN_BOTO3:
        raise RuntimeError(
            f"boto3 {version} is too old for DynamoDB vector search. "
            f"Need >= {'.'.join(map(str, MIN_BOTO3))}. "
            f"Run: pip install --upgrade 'boto3>=1.43.72'"
        )
    return version


def _ddb(cfg: CacheConfig):
    return boto3.client("dynamodb", region_name=cfg.region)


def table_exists(cfg: CacheConfig) -> bool:
    """True if the cache table already exists."""
    ddb = _ddb(cfg)
    try:
        ddb.describe_table(TableName=cfg.table_name)
        return True
    except ddb.exceptions.ResourceNotFoundException:
        return False


def _vector_filters(cfg: CacheConfig) -> list:
    """Return the INLINE_FILTER attribute names on the existing vector index."""
    ddb = _ddb(cfg)
    desc = ddb.describe_table(TableName=cfg.table_name)["Table"]
    return [s.get("AttributeName")
            for vi in desc.get("VectorIndexes", [])
            for s in vi.get("SearchSchema", [])]


def create_table(cfg: CacheConfig, wait: bool = True) -> dict:
    """Create the cache table with the vector index and TTL. Idempotent.

    Guards against a stale table: if a table with this name already exists but
    lacks the ``kind`` vector filter this code needs, it returns a clear
    ``schema_mismatch`` status instead of letting later searches fail with a
    cryptic error.
    """
    boto3_version = assert_boto3_supports_vectors()
    ddb = _ddb(cfg)

    if table_exists(cfg):
        if "kind" not in _vector_filters(cfg):
            return {
                "created": False,
                "schema_mismatch": True,
                "table_name": cfg.table_name,
                "boto3_version": boto3_version,
                "message": (
                    f"table {cfg.table_name!r} exists but its vector index has no "
                    "'kind' filter (it was made by an older schema). Delete it and "
                    "re-run: delete_table(cfg) then create_table(cfg)."
                ),
            }
        return {
            "created": False,
            "already_existed": True,
            "table_name": cfg.table_name,
            "boto3_version": boto3_version,
        }

    ddb.create_table(
        TableName=cfg.table_name,
        AttributeDefinitions=[
            {"AttributeName": "entry_id", "AttributeType": "S"},
            # INLINE_FILTER attributes must appear in AttributeDefinitions.
            {"AttributeName": "kind", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "entry_id", "KeyType": "HASH"},
        ],
        BillingMode="PAY_PER_REQUEST",
        VectorIndexes=[{
            "IndexName": cfg.vector_index_name,
            "VectorAttribute": {"AttributeName": "embedding"},
            "Dimensions": VECTOR_DIM,
            "DistanceFunction": "COSINE",
            "Projection": {"ProjectionType": "ALL"},
            # Scope KNN searches to one cache pattern (kind).
            "SearchSchema": [
                {"AttributeName": "kind", "SearchSchemaElementType": "INLINE_FILTER"},
            ],
        }],
    )

    if wait:
        ddb.get_waiter("table_exists").wait(TableName=cfg.table_name)
        ddb.update_time_to_live(
            TableName=cfg.table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )

    return {
        "created": True,
        "already_existed": False,
        "table_name": cfg.table_name,
        "boto3_version": boto3_version,
    }


def delete_table(cfg: CacheConfig, wait: bool = True) -> dict:
    """Delete the cache table. Idempotent - ignores a missing table."""
    ddb = _ddb(cfg)
    try:
        ddb.delete_table(TableName=cfg.table_name)
        if wait:
            ddb.get_waiter("table_not_exists").wait(TableName=cfg.table_name)
        return {"deleted": True, "table_name": cfg.table_name}
    except ddb.exceptions.ResourceNotFoundException:
        return {"deleted": False, "table_name": cfg.table_name, "reason": "not found"}


def describe_vector_index(cfg: CacheConfig) -> dict:
    """Return the vector index sub-status from DescribeTable (for validation)."""
    ddb = _ddb(cfg)
    desc = ddb.describe_table(TableName=cfg.table_name)["Table"]
    return {
        "table_status": desc.get("TableStatus"),
        "vector_indexes": desc.get("VectorIndexes", []),
        "item_count": desc.get("ItemCount", 0),
    }
