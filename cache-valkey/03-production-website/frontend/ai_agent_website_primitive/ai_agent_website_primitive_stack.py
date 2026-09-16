from aws_cdk import (
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_logs as logs,
    aws_ssm as ssm,
)
from constructs import Construct

from webhosting.web_hosting import WebHosting
import config


class AiAgentWebsitePrimitiveStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.create_resources()
        self.create_parameters()
        self.destroy_log_groups()

    def destroy_log_groups(self) -> None:
        """CDK-managed Lambda log groups default to RETAIN, which leaves orphans
        behind after `cdk destroy`. This sample is disposable, so they go with it."""
        for child in self.node.find_all():
            if isinstance(child, logs.CfnLogGroup):
                child.apply_removal_policy(RemovalPolicy.DESTROY)

    def create_resources(self) -> None:
        self.web_hosting = WebHosting(self, "WebHosting")

        CfnOutput(
            self,
            "DistributionDomainName",
            value=self.web_hosting.distribution_domain_name,
        )
        CfnOutput(
            self,
            "DistributionId",
            value=self.web_hosting.distribution.distribution_id,
        )
        CfnOutput(
            self,
            "SiteBucketName",
            value=self.web_hosting.site_bucket.bucket_name,
        )

    def create_parameters(self) -> None:
        ssm.StringParameter(
            self,
            "DistributionDomainParam",
            parameter_name=config.DISTRIBUTION_DOMAIN_PARAM_NAME,
            string_value=self.web_hosting.distribution_domain_name,
        )
        ssm.StringParameter(
            self,
            "DistributionIdParam",
            parameter_name=config.DISTRIBUTION_ID_PARAM_NAME,
            string_value=self.web_hosting.distribution.distribution_id,
        )
        ssm.StringParameter(
            self,
            "SiteBucketParam",
            parameter_name=config.SITE_BUCKET_PARAM_NAME,
            string_value=self.web_hosting.site_bucket.bucket_name,
        )
