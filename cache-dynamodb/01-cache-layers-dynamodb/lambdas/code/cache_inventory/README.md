# cache_inventory

Returns counts of cached items per pattern or deletes all cache entries from the DynamoDB agent cache table.

## Trigger

Invoked directly (synchronous) by the AppSync `cache/` namespace Lambda resolver, or called from the `03-production-website` backend to power the dashboard cache panel.

## Input

```json
{"action": "cache_stats"}
{"action": "flush"}
```

## Output

```json
// cache_stats
{"statusCode": 200, "counts": {"response": 12, "plan": 3, "tool_result": 47}}

// flush
{"statusCode": 200, "deleted": 69}
```

## Environment variables

| Variable | Set in | Purpose |
|----------|--------|---------|
| `TABLE_NAME` | stack wiring | DynamoDB table to query/flush |
| `ENTRY_TYPE_GSI_NAME` | stack wiring | GSI name for per-entry_type counts |

## Permissions

- `dynamodb:Query` on `arn:aws:dynamodb:{region}:{account}:table/{TABLE_NAME}/index/*`
- `dynamodb:Scan` on `arn:aws:dynamodb:{region}:{account}:table/{TABLE_NAME}`
- `dynamodb:DeleteItem`, `dynamodb:BatchWriteItem` on `arn:aws:dynamodb:{region}:{account}:table/{TABLE_NAME}`

## Layers / dependencies

Uses the `deps` layer (boto3 with DynamoDB vector search support). No external packages needed at function level.
