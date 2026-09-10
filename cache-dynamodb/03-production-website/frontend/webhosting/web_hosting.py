import os
import shlex
import shutil
import subprocess

import jsii
from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3deploy,
)

import config


@jsii.implements(cdk.ILocalBundling)
class LocalBundler:
    """Runs the frontend build locally and copies dist/ output to the CDK asset directory."""

    def try_bundle(self, output_dir, *, image, bundling_file_access=None, output_type=None):
        try:
            subprocess.run(  # nosemgrep: dangerous-subprocess-use-audit
                shlex.split(config.FRONTEND_BUILD_COMMAND),
                cwd=config.FRONTEND_SOURCE_DIR,
                check=True,
            )
            dist_dir = os.path.join(config.FRONTEND_SOURCE_DIR, "dist")
            shutil.copytree(dist_dir, output_dir, dirs_exist_ok=True)
            return True
        except Exception:
            return False


# Enum mapping dictionaries – map human-readable config strings to CDK enums
_PRICE_CLASS_MAP = {
    "PRICE_CLASS_100": cloudfront.PriceClass.PRICE_CLASS_100,
    "PRICE_CLASS_200": cloudfront.PriceClass.PRICE_CLASS_200,
    "PRICE_CLASS_ALL": cloudfront.PriceClass.PRICE_CLASS_ALL,
}

_HTTP_VERSION_MAP = {
    "HTTP1_1": cloudfront.HttpVersion.HTTP1_1,
    "HTTP2": cloudfront.HttpVersion.HTTP2,
    "HTTP2_AND_3": cloudfront.HttpVersion.HTTP2_AND_3,
    "HTTP3": cloudfront.HttpVersion.HTTP3,
}

_VIEWER_PROTOCOL_MAP = {
    "ALLOW_ALL": cloudfront.ViewerProtocolPolicy.ALLOW_ALL,
    "HTTPS_ONLY": cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
    "REDIRECT_TO_HTTPS": cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
}


def _resolve_enum(mapping: dict, value: str, label: str):
    """Look up a config string in a mapping dict, raising ValueError if invalid."""
    if value not in mapping:
        valid = ", ".join(sorted(mapping.keys()))
        raise ValueError(f"Invalid {label} '{value}'. Valid options: {valid}")
    return mapping[value]


class WebHosting(Construct):
    """CDK construct that creates S3 bucket, CloudFront distribution, and asset deployment."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Validate config enum strings early (fail-fast at synth time)
        _resolve_enum(_PRICE_CLASS_MAP, config.PRICE_CLASS, "PRICE_CLASS")
        _resolve_enum(_HTTP_VERSION_MAP, config.HTTP_VERSION, "HTTP_VERSION")
        _resolve_enum(
            _VIEWER_PROTOCOL_MAP,
            config.VIEWER_PROTOCOL_POLICY,
            "VIEWER_PROTOCOL_POLICY",
        )

        # --- S3 Bucket (private, destroy on stack removal) ---
        self.site_bucket = s3.Bucket(
            self,
            "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- CloudFront Distribution with OAC ---
        error_responses = [
            cloudfront.ErrorResponse(
                http_status=err["http_status"],
                response_http_status=err["response_http_status"],
                response_page_path=err["response_page_path"],
                ttl=Duration.seconds(err["ttl_seconds"]),
            )
            for err in config.SPA_ERROR_RESPONSES
        ]

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    self.site_bucket
                ),
                viewer_protocol_policy=_resolve_enum(
                    _VIEWER_PROTOCOL_MAP,
                    config.VIEWER_PROTOCOL_POLICY,
                    "VIEWER_PROTOCOL_POLICY",
                ),
                compress=True,
            ),
            default_root_object=config.DEFAULT_ROOT_OBJECT,
            price_class=_resolve_enum(
                _PRICE_CLASS_MAP, config.PRICE_CLASS, "PRICE_CLASS"
            ),
            http_version=_resolve_enum(
                _HTTP_VERSION_MAP, config.HTTP_VERSION, "HTTP_VERSION"
            ),
            error_responses=error_responses,
        )

        self.distribution_domain_name = self.distribution.distribution_domain_name

        # --- Asset Deployment with local bundling ---
        site_source = s3deploy.Source.asset(
            config.FRONTEND_SOURCE_DIR,
            bundling=cdk.BundlingOptions(
                image=cdk.DockerImage.from_registry("node:18"),
                local=LocalBundler(),
            ),
        )

        s3deploy.BucketDeployment(
            self,
            "DeployWebsite",
            sources=[site_source],
            destination_bucket=self.site_bucket,
            destination_key_prefix=config.DESTINATION_KEY_PREFIX,
            distribution=self.distribution,
            distribution_paths=config.INVALIDATION_PATHS,
        )
