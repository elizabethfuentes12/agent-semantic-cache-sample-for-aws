"""DynamoDB-backed production agent stack.

Stack name: DynamoProductionAgentStack — does not conflict with ProductionAgentStack.
SSM prefix: /dynamodb-cache/ — does not conflict with /semantic-cache/

Key difference from the Valkey version: no VPC attachment.
DynamoDB is a public AWS endpoint — no ENIs, subnets, or security groups needed.
"""

from aws_cdk import CfnOutput, Stack, aws_ssm as ssm
from constructs import Construct

from agentcore import AgentCoreDeployment, AgentCoreRole


class ProductionAgentDynamoStack(Stack):
    """Stack 02-dynamodb — Strands agent on AgentCore Runtime, DynamoDB cache."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        params: dict,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        role = AgentCoreRole(
            self,
            "Role",
            duffel_secret_arn=params["duffel-secret-arn"],
            table_name=params["table-name"],
        )

        # Production agent: two-level cache (response + reasoning hooks).
        production = AgentCoreDeployment(self, "Agent", role=role.role)

        # A1 reasoning-cache demo: isolated runtime for the plan template cache.
        plan = AgentCoreDeployment(
            self, "PlanCacheAgent",
            role=role.role,
            runtime_name="DynamoPlanCacheAgent",
            entry_point="plan_cache_agent.py",
            description="A1: plan template cache (DynamoDB backend)",
            code_asset=production.code_asset,
        )

        # SSM outputs — read by 03-production-website
        ssm.StringParameter(
            self, "AgentRuntimeArnParam",
            parameter_name="/dynamodb-cache/agent-runtime-arn",
            string_value=production.agent_runtime_arn,
        )
        for name, deployment in [
            ("plan-cache-runtime-arn", plan),
        ]:
            ssm.StringParameter(
                self, f"{name}-param",
                parameter_name=f"/dynamodb-cache/{name}",
                string_value=deployment.agent_runtime_arn,
            )

        CfnOutput(self, "AgentRuntimeArn", value=production.agent_runtime_arn)
        CfnOutput(self, "PlanCacheRuntimeArn", value=plan.agent_runtime_arn)
