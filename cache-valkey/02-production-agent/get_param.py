"""SSM reader helper for cross-stack values (synth-time)."""

import os

import boto3

ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def get_string_param(parameter_name: str) -> str:
    response = ssm.get_parameter(Name=parameter_name)
    param = response.get("Parameter")
    if param:
        return param.get("Value")
    raise ValueError(f"SSM parameter not found: {parameter_name}")
