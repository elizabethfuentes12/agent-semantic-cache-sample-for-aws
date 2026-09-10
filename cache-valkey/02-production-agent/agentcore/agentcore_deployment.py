"""AgentCore Runtime deployment construct (code-based deploy, VPC mode)."""

import os
import subprocess  # nosec B404 - subprocess used with a fixed command list, no shell, no user input

from aws_cdk import (
    aws_bedrockagentcore as bedrockagentcore,
    aws_iam as iam,
    aws_s3_assets as s3_assets,
)
from constructs import Construct


class AgentCoreDeployment(Construct):
    """AgentCore Runtime running the Strands agent inside the stack-01 VPC.

    Option A (direct tool access): the runtime's ENIs live in the private
    subnets, its security group is allowed on the Valkey SG (both wired in
    stack 01 and shared via SSM), so the cache hooks talk to Valkey with
    sub-millisecond latency — no intermediary Lambdas.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        role: iam.Role,
        subnet_ids: list,
        security_group_id: str,
        runtime_name: str = "SemanticCacheTravelAgent",
        entry_point: str = "production_agent.py",
        description: str = "Travel agent with Valkey semantic + reasoning cache",
        code_asset: s3_assets.Asset | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if code_asset is None:
            # Build the ARM64 deployment package if missing
            base_dir = os.path.join(os.path.dirname(__file__), "..")
            zip_path = os.path.join(base_dir, "agent_files", "deployment_package.zip")
            if not os.path.exists(zip_path):
                result = subprocess.run(  # nosemgrep: dangerous-subprocess-use-audit  # nosec B603 B607 - fixed command, list form, no shell, no user input
                    ["bash", "create_deployment_package.sh"],
                    cwd=base_dir,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"Failed to create deployment package: {result.stderr}"
                    )
            code_asset = s3_assets.Asset(self, "AgentCodeAsset", path=zip_path)
        code_asset.grant_read(role)
        self.code_asset = code_asset

        self.runtime = bedrockagentcore.CfnRuntime(
            self,
            "SemanticCacheAgentRuntime",
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=bedrockagentcore.CfnRuntime.CodeConfigurationProperty(
                    code=bedrockagentcore.CfnRuntime.CodeProperty(
                        s3=bedrockagentcore.CfnRuntime.S3LocationProperty(
                            bucket=code_asset.s3_bucket_name,
                            prefix=code_asset.s3_object_key,
                        )
                    ),
                    entry_point=[entry_point],
                    runtime="PYTHON_3_11",
                )
            ),
            agent_runtime_name=runtime_name,
            description=description,
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="VPC",
                network_mode_config=bedrockagentcore.CfnRuntime.VpcConfigProperty(
                    subnets=subnet_ids,
                    security_groups=[security_group_id],
                ),
            ),
            lifecycle_configuration=bedrockagentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=900,
                max_lifetime=28800,
            ),
            role_arn=role.role_arn,
        )
        self.runtime.node.add_dependency(code_asset)

    @property
    def agent_runtime_arn(self) -> str:
        return self.runtime.attr_agent_runtime_arn
