import aws_cdk as cdk

from get_param import get_string_param
from production_agent_stack.production_agent_stack import ProductionAgentStack

PARAM_NAMES = [
    "duffel-secret-arn",
    "private-subnet-ids",
    "agent-runtime-sg-id",
]

params = {
    name: get_string_param(f"/semantic-cache/{name}") for name in PARAM_NAMES
}

app = cdk.App()

ProductionAgentStack(
    app,
    "ProductionAgentStack",
    params=params,
    description="Semantic-cache travel agent on AgentCore Runtime (VPC mode)",
)

app.synth()
