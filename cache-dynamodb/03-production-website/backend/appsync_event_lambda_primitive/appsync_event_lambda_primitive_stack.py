from aws_cdk import Stack, Duration, RemovalPolicy, aws_ssm as ssm, aws_iam as iam, aws_cognito as cognito, aws_logs as logs, aws_s3 as s3
from constructs import Construct
from apis.events_api import EventsAPI
from lambdas.project_lambdas import Lambdas
from databases.databases import Tables
from config import (
    APPSYNC_HTTP_ENDPOINT_PARAM_NAME,
    APPSYNC_REALTIME_ENDPOINT_PARAM_NAME,
    APPSYNC_API_KEY_PARAM_NAME,
    MEDIA_SESSIONS_BUCKET_PARAM_NAME,
    CHAT_MESSAGES_TABLE_PARAM_NAME,
    CACHE_INVENTORY_FUNCTION_PARAM_NAME,
    RESPONSE_NAMESPACE,
    TITLE_MODEL_ID,
)


class AppsyncEventLambdaPrimitiveStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, cognito_user_pool_id=None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        if cognito_user_pool_id:
            self.cognito_user_pool = cognito.UserPool.from_user_pool_id(
                self, "ImportedUserPool", cognito_user_pool_id
            )
        else:
            self.cognito_user_pool = cognito.UserPool(
                self, "UserPool",
                self_sign_up_enabled=False,
                sign_in_aliases=cognito.SignInAliases(email=True),
                password_policy=cognito.PasswordPolicy(
                    min_length=12,
                    require_lowercase=True,
                    require_uppercase=True,
                    require_digits=True,
                ),
                removal_policy=RemovalPolicy.DESTROY,
            )
        self.create_resources()
        self.set_up_identity_pool()
        self.set_up_env_vars()
        self.create_parameters()
        self.set_up_permissions()
        self.destroy_log_groups()

    def destroy_log_groups(self):
        """CDK-managed Lambda log groups default to RETAIN, which leaves orphans
        behind after `cdk destroy`. This sample is disposable, so they go with it."""
        for child in self.node.find_all():
            if isinstance(child, logs.CfnLogGroup):
                child.apply_removal_policy(RemovalPolicy.DESTROY)

    def create_resources(self):
        cors_rule = s3.CorsRule(
            allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.POST, s3.HttpMethods.PUT, s3.HttpMethods.DELETE, s3.HttpMethods.HEAD],
            allowed_origins=["*"],
            allowed_headers=["*"],
            exposed_headers=["x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2", "ETag"],
            max_age=3000,
        )
        self.bucket = s3.Bucket(
            self, "S3",
            removal_policy=RemovalPolicy.DESTROY,
            cors=[cors_rule],
            transfer_acceleration=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )

        self.tables = Tables(self, "Tables")
        self.events_api = EventsAPI(self, "EventsAPI", cognito_user_pool=self.cognito_user_pool)
        self.lambdas = Lambdas(self, "Lambdas")
        self.events_api.add_channel_namespace(
            "messages", publish=self.lambdas.publish, pub_invoke_type="EVENT"
        )
        self.events_api.add_channel_namespace("response", subscribe=self.lambdas.subscribe)
        self.events_api.add_channel_namespace(
            "chat", publish=self.lambdas.chat_history, pub_invoke_type="REQUEST_RESPONSE"
        )
        self.events_api.add_channel_namespace(
            "cache", publish=self.lambdas.cache_inventory, pub_invoke_type="REQUEST_RESPONSE"
        )

        # DynamoDB cache: call the 01-cache-layers-dynamodb inventory Lambda directly.
        # Its name is stored in SSM (written by stack 01). No VPC proxy needed since
        # DynamoDB is a public endpoint — unlike the Valkey version that required a
        # VPC Lambda to reach ElastiCache.
        self.lambdas.cache_inventory.add_environment(
            "CACHE_INVENTORY_FUNCTION_PARAM", CACHE_INVENTORY_FUNCTION_PARAM_NAME
        )
        self.lambdas.cache_inventory.add_to_role_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:*"],
            )
        )

    def set_up_identity_pool(self):
        if not self.cognito_user_pool:
            return

        self.web_client = cognito.UserPoolClient(
            self, "WebClient",
            user_pool=self.cognito_user_pool,
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
        )

        provider_name = (
            f"cognito-idp.{self.region}.amazonaws.com/"
            f"{self.cognito_user_pool.user_pool_id}"
        )

        self.identity_pool = cognito.CfnIdentityPool(
            self, "IdentityPool",
            allow_unauthenticated_identities=False,
            cognito_identity_providers=[
                cognito.CfnIdentityPool.CognitoIdentityProviderProperty(
                    client_id=self.web_client.user_pool_client_id,
                    provider_name=provider_name,
                    server_side_token_check=True,
                )
            ],
        )

        self.authenticated_role = iam.Role(
            self, "AuthenticatedRole",
            assumed_by=iam.FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                {
                    "StringEquals": {
                        "cognito-identity.amazonaws.com:aud": self.identity_pool.ref
                    },
                    "ForAnyValue:StringLike": {
                        "cognito-identity.amazonaws.com:amr": "authenticated"
                    },
                },
                "sts:AssumeRoleWithWebIdentity",
            ),
        )

        self.authenticated_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
                resources=[self.bucket.bucket_arn, f"{self.bucket.bucket_arn}/*"],
            )
        )

        self.authenticated_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/dynamodb-cache/*",
                ],
            )
        )

        cognito.CfnIdentityPoolRoleAttachment(
            self, "IdentityPoolRoleAttachment",
            identity_pool_id=self.identity_pool.ref,
            roles={"authenticated": self.authenticated_role.role_arn},
        )

    def set_up_env_vars(self):
        for fn in self.lambdas.get_all_functions():
            fn.add_environment("APPSYNC_HTTP_ENDPOINT_PARAM", APPSYNC_HTTP_ENDPOINT_PARAM_NAME)
            fn.add_environment("APPSYNC_API_KEY_PARAM", APPSYNC_API_KEY_PARAM_NAME)
            fn.add_environment("RESPONSE_NAMESPACE", RESPONSE_NAMESPACE)
            fn.add_environment("CHAT_MESSAGES_TABLE_PARAM", CHAT_MESSAGES_TABLE_PARAM_NAME)

        self.lambdas.chat_history.add_environment("TITLE_MODEL_ID", TITLE_MODEL_ID)

    def create_parameters(self):
        ssm.StringParameter(
            self, "HttpEndpointParam",
            parameter_name=APPSYNC_HTTP_ENDPOINT_PARAM_NAME,
            string_value=self.events_api.api.http_dns,
        )
        ssm.StringParameter(
            self, "RealtimeEndpointParam",
            parameter_name=APPSYNC_REALTIME_ENDPOINT_PARAM_NAME,
            string_value=self.events_api.api.realtime_dns,
        )
        ssm.StringParameter(
            self, "ApiKeyParam",
            parameter_name=APPSYNC_API_KEY_PARAM_NAME,
            string_value=self.events_api.api.api_keys["Default"].attr_api_key,
        )
        ssm.StringParameter(
            self, "MediaSessionsBucketParam",
            parameter_name=MEDIA_SESSIONS_BUCKET_PARAM_NAME,
            string_value=self.bucket.bucket_name,
        )
        ssm.StringParameter(
            self, "ChatMessagesTableParam",
            parameter_name=CHAT_MESSAGES_TABLE_PARAM_NAME,
            string_value=self.tables.chat_messages.table_name,
        )
        if self.cognito_user_pool:
            ssm.StringParameter(
                self, "IdentityPoolIdParam",
                parameter_name="/dynamodb-cache/auth/identity_pool_id",
                string_value=self.identity_pool.ref,
            )
            ssm.StringParameter(
                self, "WebClientIdParam",
                parameter_name="/dynamodb-cache/auth/web_client_id",
                string_value=self.web_client.user_pool_client_id,
            )
            ssm.StringParameter(
                self, "UserPoolIdParam",
                parameter_name="/dynamodb-cache/auth/user_pool_id",
                string_value=self.cognito_user_pool.user_pool_id,
            )

    def set_up_permissions(self):
        for fn in self.lambdas.get_all_functions():
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ssm:GetParameter"],
                    resources=[
                        "arn:aws:ssm:*:*:parameter/dynamodb-cache/*",
                        "arn:aws:ssm:*:*:parameter/semantic-cache/*",
                    ],
                )
            )
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["appsync:EventPublish"],
                    resources=[self.events_api.api.api_arn + "/*"],
                )
            )
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:*"],
                )
            )
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "bedrock-agentcore:InvokeAgentRuntime",
                        "bedrock-agentcore:InvokeAgentRuntimeForUser",
                    ],
                    resources=["arn:aws:bedrock-agentcore:*:*:runtime/*"],
                )
            )

        self.lambdas.publish.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
                resources=[self.tables.chat_messages.table_arn],
            )
        )

        self.lambdas.chat_history.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:Query",
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:UpdateItem",
                ],
                resources=[
                    self.tables.chat_messages.table_arn,
                    f"{self.tables.chat_messages.table_arn}/index/*",
                ],
            )
        )

        self.lambdas.chat_history.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "arn:aws:bedrock:*::foundation-model/*",
                ],
            )
        )
