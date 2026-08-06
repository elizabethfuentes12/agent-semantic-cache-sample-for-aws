"""Tests for the WebHosting construct and AiAgentWebsitePrimitiveStack.

Uses CDK template assertions against the synthesized CloudFormation template.
LocalBundler.try_bundle is mocked to avoid running the actual frontend build.
"""

import os
from unittest.mock import patch

import pytest
import aws_cdk as cdk
from aws_cdk import assertions

from ai_agent_website_primitive.ai_agent_website_primitive_stack import (
    AiAgentWebsitePrimitiveStack,
)


def _fake_try_bundle(self, output_dir, *, image, bundling_file_access=None, output_type=None):
    """Mock bundler that creates a dummy index.html instead of running pnpm build."""
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "index.html"), "w") as f:
        f.write("<html></html>")
    return True


@pytest.fixture(scope="module")
def template():
    """Synthesize the stack with mocked bundler and return a Template object."""
    with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle):
        app = cdk.App()
        stack = AiAgentWebsitePrimitiveStack(app, "TestStack")
        return assertions.Template.from_stack(stack)


class TestS3Bucket:
    """S3 bucket assertions.

    Validates: Requirements 3.1, 3.2, 3.3
    """

    def test_public_access_block_all_flags_true(self, template):
        """Assert PublicAccessBlockConfiguration has all four flags true."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
            },
        )

    def test_deletion_policy_delete(self, template):
        """Assert the S3 bucket has DeletionPolicy: Delete."""
        template.has_resource(
            "AWS::S3::Bucket",
            {
                "DeletionPolicy": "Delete",
            },
        )

    def test_auto_delete_objects_custom_resource(self, template):
        """Assert auto-delete-objects custom resource is present."""
        template.has_resource_properties(
            "Custom::S3AutoDeleteObjects",
            assertions.Match.any_value(),
        )


class TestCloudFrontDistribution:
    """CloudFront distribution assertions.

    Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """

    def test_s3_origin_with_oac(self, template):
        """Assert distribution has an S3 origin with OriginAccessControlId."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "Origins": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "S3OriginConfig": assertions.Match.any_value(),
                                    "OriginAccessControlId": assertions.Match.any_value(),
                                }
                            )
                        ]
                    ),
                },
            },
        )

    def test_viewer_protocol_policy_redirect_to_https(self, template):
        """Assert ViewerProtocolPolicy is redirect-to-https."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "DefaultCacheBehavior": assertions.Match.object_like(
                        {
                            "ViewerProtocolPolicy": "redirect-to-https",
                        }
                    ),
                },
            },
        )

    def test_compress_enabled(self, template):
        """Assert Compress is true."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "DefaultCacheBehavior": assertions.Match.object_like(
                        {
                            "Compress": True,
                        }
                    ),
                },
            },
        )

    def test_default_root_object(self, template):
        """Assert DefaultRootObject is index.html."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "DefaultRootObject": "index.html",
                },
            },
        )

    def test_price_class(self, template):
        """Assert PriceClass is PriceClass_100."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "PriceClass": "PriceClass_100",
                },
            },
        )

    def test_http_version(self, template):
        """Assert HttpVersion is http2."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "HttpVersion": "http2",
                },
            },
        )

    def test_custom_error_responses_403_and_404(self, template):
        """Assert CustomErrorResponses for 403 and 404 mapping to /index.html with status 200."""
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": {
                    "CustomErrorResponses": assertions.Match.array_with(
                        [
                            assertions.Match.object_like(
                                {
                                    "ErrorCode": 403,
                                    "ResponseCode": 200,
                                    "ResponsePagePath": "/index.html",
                                }
                            ),
                            assertions.Match.object_like(
                                {
                                    "ErrorCode": 404,
                                    "ResponseCode": 200,
                                    "ResponsePagePath": "/index.html",
                                }
                            ),
                        ]
                    ),
                },
            },
        )


class TestAssetDeployment:
    """Asset deployment assertions.

    Validates: Requirements 5.1, 5.2, 5.3
    """

    def test_bucket_deployment_resource_exists(self, template):
        """Assert Custom::CDKBucketDeployment resource exists."""
        template.has_resource_properties(
            "Custom::CDKBucketDeployment",
            assertions.Match.any_value(),
        )

    def test_deployment_references_distribution_for_invalidation(self, template):
        """Assert deployment references the CloudFront distribution for cache invalidation."""
        template.has_resource_properties(
            "Custom::CDKBucketDeployment",
            {
                "DistributionId": assertions.Match.any_value(),
                "DistributionPaths": assertions.Match.any_value(),
            },
        )


class TestStackOutputs:
    """CfnOutput assertions.

    Validates: Requirements 6.1, 6.2, 6.3
    """

    def test_distribution_domain_name_output(self, template):
        """Assert CfnOutput exists for distribution domain name."""
        template.has_output(
            "DistributionDomainName",
            assertions.Match.any_value(),
        )

    def test_distribution_id_output(self, template):
        """Assert CfnOutput exists for distribution ID."""
        template.has_output(
            "DistributionId",
            assertions.Match.any_value(),
        )

    def test_site_bucket_name_output(self, template):
        """Assert CfnOutput exists for bucket name."""
        template.has_output(
            "SiteBucketName",
            assertions.Match.any_value(),
        )


class TestSSMParameters:
    """SSM parameter assertions.

    Validates: Requirements 7.1, 7.2, 7.3
    """

    def test_distribution_domain_ssm_parameter(self, template):
        """Assert SSM parameter exists for distribution domain."""
        template.has_resource_properties(
            "AWS::SSM::Parameter",
            {
                "Name": "/cloudfront/distribution-domain",
            },
        )

    def test_distribution_id_ssm_parameter(self, template):
        """Assert SSM parameter exists for distribution ID."""
        template.has_resource_properties(
            "AWS::SSM::Parameter",
            {
                "Name": "/cloudfront/distribution-id",
            },
        )

    def test_site_bucket_ssm_parameter(self, template):
        """Assert SSM parameter exists for site bucket."""
        template.has_resource_properties(
            "AWS::SSM::Parameter",
            {
                "Name": "/s3/site-bucket",
            },
        )


class TestConstructEncapsulation:
    """Construct encapsulation assertions.

    Validates: Requirements 8.1, 8.2, 8.3, 8.4
    """

    def test_web_hosting_is_construct_subclass(self):
        """Assert WebHosting is a Construct subclass."""
        from webhosting.web_hosting import WebHosting
        from constructs import Construct

        assert issubclass(WebHosting, Construct)

    def test_web_hosting_exposes_site_bucket(self, template):
        """Assert WebHosting exposes site_bucket attribute."""
        with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle):
            app = cdk.App()
            stack = AiAgentWebsitePrimitiveStack(app, "AttrTestStack")
            assert hasattr(stack.web_hosting, "site_bucket")

    def test_web_hosting_exposes_distribution(self, template):
        """Assert WebHosting exposes distribution attribute."""
        with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle):
            app = cdk.App()
            stack = AiAgentWebsitePrimitiveStack(app, "AttrTestStack2")
            assert hasattr(stack.web_hosting, "distribution")

    def test_web_hosting_exposes_distribution_domain_name(self, template):
        """Assert WebHosting exposes distribution_domain_name attribute."""
        with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle):
            app = cdk.App()
            stack = AiAgentWebsitePrimitiveStack(app, "AttrTestStack3")
            assert hasattr(stack.web_hosting, "distribution_domain_name")

    def test_stack_has_create_resources_method(self):
        """Assert the stack has a create_resources() method."""
        assert callable(getattr(AiAgentWebsitePrimitiveStack, "create_resources", None))

    def test_stack_has_create_parameters_method(self):
        """Assert the stack has a create_parameters() method."""
        assert callable(getattr(AiAgentWebsitePrimitiveStack, "create_parameters", None))


class TestErrorHandling:
    """Error handling assertions for invalid config enum strings.

    Validates: Requirements 8.1
    """

    def test_invalid_price_class_raises_value_error(self):
        """Assert invalid PRICE_CLASS string raises ValueError."""
        with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle), \
             patch("config.PRICE_CLASS", "INVALID"):
            app = cdk.App()
            with pytest.raises(ValueError, match="Invalid PRICE_CLASS"):
                AiAgentWebsitePrimitiveStack(app, "BadPriceClassStack")

    def test_invalid_http_version_raises_value_error(self):
        """Assert invalid HTTP_VERSION string raises ValueError."""
        with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle), \
             patch("config.HTTP_VERSION", "INVALID"):
            app = cdk.App()
            with pytest.raises(ValueError, match="Invalid HTTP_VERSION"):
                AiAgentWebsitePrimitiveStack(app, "BadHttpVersionStack")

    def test_invalid_viewer_protocol_policy_raises_value_error(self):
        """Assert invalid VIEWER_PROTOCOL_POLICY string raises ValueError."""
        with patch("webhosting.web_hosting.LocalBundler.try_bundle", _fake_try_bundle), \
             patch("config.VIEWER_PROTOCOL_POLICY", "INVALID"):
            app = cdk.App()
            with pytest.raises(ValueError, match="Invalid VIEWER_PROTOCOL_POLICY"):
                AiAgentWebsitePrimitiveStack(app, "BadProtocolStack")
