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
        network = dict(
            subnet_ids=params["private-subnet-ids"].split(","),
            security_group_id=params["agent-runtime-sg-id"],
        )

        # Production agent: two-level cache (response + reasoning hooks).
        production = AgentCoreDeployment(
            self, "Agent", role=role.role, **network,
        )

        # A1/A2/A3 reasoning-cache demos: one isolated runtime per approach,
        # all sharing the same ARM64 code package (different entry points).
        plan = AgentCoreDeployment(
            self, "PlanCacheAgent", role=role.role, **network,
            runtime_name="PlanCacheAgent",
            entry_point="plan_cache_agent.py",
            description="A1: plan template cache (Agentic Plan Caching pattern)",
            code_asset=production.code_asset,
        )
        strategy = AgentCoreDeployment(
            self, "StrategyMemoryAgent", role=role.role, **network,
            runtime_name="StrategyMemoryAgent",
            entry_point="strategy_memory_agent.py",
            description="A2: distilled strategy memory (ReasoningBank pattern)",
            code_asset=production.code_asset,
        )
        skills = AgentCoreDeployment(
            self, "SkillInductionAgent", role=role.role, **network,
            runtime_name="SkillInductionAgent",
            entry_point="skill_induction_agent.py",
            description="A3: skill induction from trajectories (Agent Skills pattern)",
            code_asset=production.code_asset,
        )

        # Logical ID "RuntimeArnParam" predates the A-demos — keep it so the
        # existing parameter updates in place instead of failing on create.
        ssm.StringParameter(
            self,
            "RuntimeArnParam",
            parameter_name="/semantic-cache/agent-runtime-arn",
            string_value=production.agent_runtime_arn,
        )
        for name, deployment in [
            ("plan-cache-runtime-arn", plan),
            ("strategy-memory-runtime-arn", strategy),
            ("skill-induction-runtime-arn", skills),
        ]:
            ssm.StringParameter(
                self,
                f"{name}-param",
                parameter_name=f"/semantic-cache/{name}",
                string_value=deployment.agent_runtime_arn,
            )

        CfnOutput(self, "AgentRuntimeArn", value=production.agent_runtime_arn)
        CfnOutput(self, "PlanCacheRuntimeArn", value=plan.agent_runtime_arn)
        CfnOutput(self, "StrategyMemoryRuntimeArn", value=strategy.agent_runtime_arn)
        CfnOutput(self, "SkillInductionRuntimeArn", value=skills.agent_runtime_arn)
