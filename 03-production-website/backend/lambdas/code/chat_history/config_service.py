import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm_client = boto3.client("ssm")


def get_ssm_parameter(parameter_name):
    """Retrieve a parameter value from SSM Parameter Store.

    Args:
        parameter_name: The name of the SSM parameter to retrieve.

    Returns:
        The parameter value as a string.

    Raises:
        ValueError: If parameter_name is empty or the parameter is not found.
    """
    if not parameter_name:
        raise ValueError("Parameter name must not be empty")

    try:
        response = ssm_client.get_parameter(
            Name=parameter_name, WithDecryption=True
        )
        return response["Parameter"]["Value"]
    except ssm_client.exceptions.ParameterNotFound:
        raise ValueError(f"SSM parameter not found: {parameter_name}")
