"""Synthesis tests for the DynamoDB production-agent stack (stack 02).

Replaces the auto-generated `cdk init` template. Validates that the stack
synthesizes with placeholder params and provisions the production plus A1
AgentCore runtimes plus the SSM contract read by stack 03.
"""

import aws_cdk as cdk
import aws_cdk.assertions as assertions

from production_agent_dynamodb.production_agent_dynamodb_stack import (
    ProductionAgentDynamoStack,
)

_PARAMS = {
    "table-name": "agent-cache-dynamodb",
    "vector-index-name": "embedding-index",
    "entry-type-gsi-name": "entry-type-index",
    "duffel-secret-arn": (
        "arn:aws:secretsmanager:us-east-1:000000000000:secret:placeholder"
    ),
}


def _template():
    app = cdk.App()
    stack = ProductionAgentDynamoStack(app, "TestDynamoProductionAgentStack", params=_PARAMS)
    return assertions.Template.from_stack(stack)


def test_stack_synthesizes():
    """The stack synthesizes without error using placeholder params."""
    assert _template() is not None


def test_agent_runtimes():
    """Production + A1 (plan cache): two AgentCore runtimes."""
    _template().resource_count_is("AWS::BedrockAgentCore::Runtime", 2)


def test_exports_runtime_arn_ssm_contract():
    """Stack 03 reads the runtime ARNs from these SSM parameters."""
    template = _template()
    for param_name in (
        "/dynamodb-cache/agent-runtime-arn",
        "/dynamodb-cache/plan-cache-runtime-arn",
    ):
        template.has_resource_properties("AWS::SSM::Parameter", {"Name": param_name})
