# DynamoDB Vector Cache Infrastructure: Single Table for All Agent Cache Patterns

One DynamoDB table with a native vector index replaces two Valkey/ElastiCache clusters. Every entry type - semantic responses, plan templates, reasoning trajectories, and tool results - lives in a single `agent-cache-dynamodb` table without any VPC, security groups, or node sizing.

![CDK](https://img.shields.io/badge/AWS_CDK-2.265.0-orange)
![DynamoDB](https://img.shields.io/badge/DynamoDB-Vector_Search-purple)
![Python](https://img.shields.io/badge/Python-3.13-blue)

---

## What does this stack provision?

| Resource | Purpose |
|----------|---------|
| `agent-cache-dynamodb` table | Single table for all cache patterns, created via a Lambda-backed custom resource (cr.Provider) |
| `embedding-index` vector index | ANN COSINE index on `embedding` attribute, 1024 dimensions (Titan v2) |
| `entry-type-index` GSI | Queries items by `entry_type` - for cache stats and counts |
| `cache_inventory` Lambda | Cache stats and flush endpoint, invoked by the website backend |
| SSM parameters | Table coordinates read by stack 02 |

---

## Why a Lambda-backed custom resource instead of aws_dynamodb.Table?

[CloudFormation `AWS::DynamoDB::Table`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-dynamodb-table.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) does **not** support `VectorIndexes` in its properties schema. CDK's `aws_dynamodb.Table` and `TableV2` constructs therefore cannot create a vector-indexed table natively.

The workaround is a Lambda-backed **custom resource** (`aws_cdk.custom_resources.Provider`) whose handler calls the `DynamoDB.CreateTable` SDK operation directly, including the `VectorIndexes` block that CloudFormation cannot express. The `GlobalSecondaryIndexes` and `TimeToLiveSpecification` are included in the same `CreateTable` call so all resources are provisioned atomically. Using a `Provider` (rather than the higher-level `AwsCustomResource`) lets the `table_creator` Lambda run a recent boto3 from the deps layer, which is required for the `VectorIndexes` parameter.

---

## How does the single-table design work?

Items are separated by `entry_type`. The vector index declares `entry_type` and `model_id` as `INLINE_FILTER` attributes so `search_vectors()` can scope KNN to one pattern without a separate GSI:

| `entry_type` | Has embedding | Pattern |
|---|---|---|
| `response` | ✅ | Query-level semantic response cache |
| `plan` | ✅ | Plan template cache |
| `trajectory` | ✅ | Reasoning cache: question → tool-call sequence |
| `tool_result` | ❌ | Tool result exact-match cache |

Items without `embedding` are stored with `PutItem` but never appear in `search_vectors` results.

---

## How does search_vectors work?

```python
# Query vector: plain list of {"N": "float_str"} - NOT wrapped in DynamoDB L type
response = ddb.search_vectors(
    TableName="agent-cache-dynamodb",
    IndexName="embedding-index",
    SearchVector=[{"N": str(v)} for v in embedding],
    TopK=1,
    SearchConditionExpression="entry_type = :et AND model_id = :m",
    ExpressionAttributeValues={
        ":et": {"S": "response"},
        ":m":  {"S": "us.amazon.nova-pro-v1:0"},
    },
)
# COSINE score: 0 = identical, 2 = opposite
similarity = 1.0 - (response["SearchResults"][0]["Score"] / 2.0)
```

Store an item with a vector:

```python
ddb.put_item(Item={
    "entry_id":   {"S": str(uuid.uuid4())},
    "entry_type": {"S": "response"},
    "model_id":   {"S": model_id},
    "embedding":  {"L": [{"N": str(v)} for v in embedding]},  # stored as L of N
    "ttl":        {"N": str(int(time.time()) + 3600)},
    ...
})
```

---

## TTL caveat for volatile data

DynamoDB TTL (Time To Live) deletion is **eventually consistent**: AWS deletes expired items ["typically within a few days after their expiration"](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/howitworks-ttl.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el), so an expired item can still come back from a read. This stack only creates the table; the agent tracks that read it re-check the stored `ttl` on every `GetItem`, which matters most for the `search_flights` tool cache (5-minute TTL). The check is in [`local/cache_lib/caches.py`](../local/cache_lib/caches.py) and [`02-production-agent/agent_files/dynamodb_cache.py`](../02-production-agent/agent_files/dynamodb_cache.py):

```python
item = ddb.get_item(...)["Item"]
if int(item["ttl"]["N"]) < int(time.time()):
    return None  # treat as miss even though DynamoDB returned it
```

---

## SSM parameters exported by this stack

| Parameter | Value | Used by |
|-----------|-------|---------|
| `/dynamodb-cache/table-name` | `agent-cache-dynamodb` | stack 02 |
| `/dynamodb-cache/vector-index-name` | `embedding-index` | stack 02 |
| `/dynamodb-cache/entry-type-gsi-name` | `entry-type-index` | stack 02 |
| `/dynamodb-cache/cache-inventory-function-name` | Lambda name | stack 03 |

---

## How do I deploy?

```bash
cd 01-cache-layers-dynamodb
source .venv/bin/activate
pip install -r requirements.txt

# Install boto3 ARM64 layer dependencies (required before deploy)
pip install boto3 \
  -t layers/deps/python/ \
  --platform manylinux2014_aarch64 \
  --only-binary=:all: \
  --python-version 3.13

AWS_PROFILE=<your-profile> cdk deploy
```

Stack name: `DynamoCacheStack`

---

## How do I check what is cached?

The `cache_inventory` Lambda accepts:

```python
# Stats per cache pattern
{"action": "cache_stats"}

# Flush all items
{"action": "flush"}
```

---

## FAQ

**Can I change the vector dimensions after deploy?**
No. The vector index config (`Dimensions`, `DistanceFunction`) is immutable once the table is created. To change dimensions you must redeploy the stack (destroy + recreate).

**Why is `BillingMode` required to be `PAY_PER_REQUEST`?**
[DynamoDB vector indexes only work with on-demand capacity](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.Requirements.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el). Provisioned capacity is not supported.

**What is the `entry-type-index` GSI for?**
`search_vectors` can filter by `entry_type` inline, but the GSI is needed for regular DynamoDB `Query` operations - counting entries per type for cache stats.

---

## References

- [DynamoDB Vector Search docs](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [DynamoDB Vector Search requirements](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.Requirements.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [AWS CDK Custom Resources (Provider)](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources/Provider.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](../../CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../../LICENSE) file for details.
