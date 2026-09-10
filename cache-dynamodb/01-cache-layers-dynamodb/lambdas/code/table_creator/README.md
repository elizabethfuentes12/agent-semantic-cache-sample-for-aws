# table_creator

CloudFormation Custom Resource handler that creates the `agent-cache-dynamodb` DynamoDB table with a native vector index.

## Why a custom Lambda

`AWS::DynamoDB::Table` (CloudFormation / CDK `aws_dynamodb.Table`) does not support `VectorIndexes`. This Lambda uses the `deps` layer which pins boto3 ≥ 1.43.72 - the first version with `CreateTable VectorIndexes` support.

## Trigger

`aws_cdk.custom_resources.Provider` - invoked by CloudFormation on Create, Update, Delete.

## Input

| RequestType | Behaviour |
|-------------|-----------|
| `Create` | Creates the table with VectorIndexes, GSI, TTL |
| `Update` | No-op (table config is immutable) |
| `Delete` | Deletes the table (idempotent) |

## Output

`Data.TableName` = `agent-cache-dynamodb`

## Environment variables

None - table name is hardcoded in the module.

## Permissions

`dynamodb:CreateTable`, `dynamodb:DeleteTable`, `dynamodb:DescribeTable`, `dynamodb:UpdateTimeToLive` on `*`.

## Layers / dependencies

`deps` layer - boto3 ≥ 1.43.72 (required for `VectorIndexes` in `CreateTable`).
