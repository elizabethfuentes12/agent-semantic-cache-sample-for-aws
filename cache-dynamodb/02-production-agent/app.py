import aws_cdk as cdk

from get_param import get_string_param
from production_agent_dynamodb.production_agent_dynamodb_stack import ProductionAgentDynamoStack


def _param(name: str, fallback: str) -> str:
    """Read SSM param; return fallback when stack 01 is not yet deployed."""
    try:
        return get_string_param(name)
    except Exception:
        return fallback


params = {
    "table-name":           _param("/dynamodb-cache/table-name",           "agent-cache-dynamodb"),
    "vector-index-name":    _param("/dynamodb-cache/vector-index-name",    "embedding-index"),
    "entry-type-gsi-name":  _param("/dynamodb-cache/entry-type-gsi-name",  "entry-type-index"),
    "duffel-secret-arn":    _param("/semantic-cache/duffel-secret-arn",    "arn:aws:secretsmanager:us-east-1:000000000000:secret:placeholder"),
}

app = cdk.App()

ProductionAgentDynamoStack(
    app,
    "DynamoProductionAgentStack",
    params=params,
    description="DynamoDB-backed travel agent on AgentCore Runtime (no VPC required)",
)

app.synth()
