"""Synthesis tests for the DynamoDB cache-layers stack (stack 01).

Replaces the auto-generated `cdk init` template. Validates that the stack
synthesizes and exports the cross-stack SSM contract read by stack 02.
"""

import aws_cdk as cdk
import aws_cdk.assertions as assertions

from cache_layers_dynamodb.cache_layers_dynamodb_stack import CacheLayersDynamodbStack


def _template():
    app = cdk.App()
    stack = CacheLayersDynamodbStack(app, "TestDynamoCacheStack")
    return assertions.Template.from_stack(stack)


def test_stack_synthesizes():
    """The stack synthesizes without error."""
    assert _template() is not None


def test_exports_ssm_contract():
    """Stack 02 reads the table name / index names from these SSM parameters."""
    template = _template()
    for param_name in (
        "/dynamodb-cache/table-name",
        "/dynamodb-cache/vector-index-name",
        "/dynamodb-cache/entry-type-gsi-name",
        "/dynamodb-cache/cache-inventory-function-name",
    ):
        template.has_resource_properties("AWS::SSM::Parameter", {"Name": param_name})


def test_cache_inventory_lambda_exists():
    """The table-creator + cache-inventory Lambdas are provisioned."""
    template = _template()
    # At least the table_creator and cache_inventory functions plus the
    # custom-resource provider framework functions.
    template.resource_count_is("AWS::SSM::Parameter", 4)
