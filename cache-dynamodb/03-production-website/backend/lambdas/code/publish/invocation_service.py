import json
import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

lambda_client = boto3.client("lambda")


def invoke_lambda(function_arn, payload):
    """Invoke a Lambda function asynchronously (Event mode).

    Args:
        function_arn: The ARN of the target Lambda function.
        payload: A dict to serialize as the invocation payload.

    Returns:
        The boto3 invoke response dict.
    """
    return lambda_client.invoke(
        FunctionName=function_arn,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )
