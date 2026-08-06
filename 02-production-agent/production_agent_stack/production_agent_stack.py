from aws_cdk import CfnOutput, Stack, aws_ssm as ssm
from constructs import Construct

from agentcore import AgentCoreDeployment, AgentCoreRole


class ProductionAgentStack(Stack):
    """Stack 02 — Strands agent on AgentCore Runtime, VPC-attached to the
    stack-01 caches. All inputs arrive via SSM (synth-time), the runtime
    ARN is exported via SSM for stack 03."""

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
            self, "Role", duffel_secret_arn=params["duffel-secret-arn"]
        )
        deployment = AgentCoreDeployment(
            self,
            "Agent",
            role=role.role,
            subnet_ids=params["private-subnet-ids"].split(","),
            security_group_id=params["agent-runtime-sg-id"],
        )

        ssm.StringParameter(
            self,
            "RuntimeArnParam",
            parameter_name="/semantic-cache/agent-runtime-arn",
            string_value=deployment.agent_runtime_arn,
        )

        CfnOutput(self, "AgentRuntimeArn", value=deployment.agent_runtime_arn)
