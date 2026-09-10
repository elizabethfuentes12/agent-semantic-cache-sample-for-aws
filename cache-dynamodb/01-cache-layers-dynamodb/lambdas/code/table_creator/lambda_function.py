"""Custom Resource Lambda — creates the DynamoDB agent-cache table with VectorIndexes.

Uses boto3 from the deps layer (1.43.72+) because the Lambda runtime's built-in
boto3 does not support the VectorIndexes parameter in CreateTable.

CloudFormation event protocol (aws_cdk.custom_resources.Provider):
  RequestType: Create | Update | Delete
  Return: dict with PhysicalResourceId and optional Data
"""

import logging
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = "agent-cache-dynamodb"


def lambda_handler(event, context):
    req_type = event["RequestType"]
    logger.info("RequestType=%s TableName=%s", req_type, TABLE_NAME)

    ddb = boto3.client("dynamodb")

    if req_type == "Create":
        _create_table(ddb)
        return {"PhysicalResourceId": TABLE_NAME, "Data": {"TableName": TABLE_NAME}}

    if req_type == "Update":
        # Table config is immutable — nothing to update
        return {"PhysicalResourceId": event["PhysicalResourceId"]}

    if req_type == "Delete":
        _delete_table(ddb)
        return {"PhysicalResourceId": event["PhysicalResourceId"]}

    return {"PhysicalResourceId": TABLE_NAME}


def _create_table(ddb):
    """Create the table with VectorIndexes, GSI, and TTL."""
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "entry_id",   "AttributeType": "S"},
            {"AttributeName": "entry_type", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "N"},
            # SearchSchema INLINE_FILTER attributes must be in AttributeDefinitions
            {"AttributeName": "model_id",   "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "entry_id", "KeyType": "HASH"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "entry-type-index",
            "KeySchema": [
                {"AttributeName": "entry_type", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
        VectorIndexes=[{
            "IndexName": "embedding-index",
            "VectorAttribute": {"AttributeName": "embedding"},
            "Dimensions": 1024,
            "DistanceFunction": "COSINE",
            "Projection": {"ProjectionType": "ALL"},
            # entry_type and model_id as INLINE_FILTERs for scoped KNN searches
            "SearchSchema": [
                {"AttributeName": "entry_type", "SearchSchemaElementType": "INLINE_FILTER"},
                {"AttributeName": "model_id",   "SearchSchemaElementType": "INLINE_FILTER"},
            ],
        }],
    )
    ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    ddb.update_time_to_live(
        TableName=TABLE_NAME,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )
    logger.info("Table %s created with VectorIndexes and TTL", TABLE_NAME)


def _delete_table(ddb):
    """Delete the table; ignore if it doesn't exist."""
    try:
        ddb.delete_table(TableName=TABLE_NAME)
        ddb.get_waiter("table_not_exists").wait(TableName=TABLE_NAME)
        logger.info("Table %s deleted", TABLE_NAME)
    except ddb.exceptions.ResourceNotFoundException:
        logger.info("Table %s already gone", TABLE_NAME)
