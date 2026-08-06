from constructs import Construct
from aws_cdk import Duration, Expiration
from aws_cdk.aws_appsync import (
    EventApi,
    EventApiAuthConfig,
    AppSyncAuthProvider,
    AppSyncAuthorizationType,
    AppSyncApiKeyConfig,
    AppSyncCognitoConfig,
    HandlerConfig,
    LambdaInvokeType,
)


class EventsAPI(Construct):
    def __init__(self, scope, construct_id, cognito_user_pool=None, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # Build auth providers list — always include API_KEY
        auth_providers = [
            AppSyncAuthProvider(
                authorization_type=AppSyncAuthorizationType.API_KEY,
                api_key_config=AppSyncApiKeyConfig(
                    expires=Expiration.after(Duration.days(365))
                ),
            )
        ]

        # Auth mode types — always include API_KEY
        auth_mode_types = [AppSyncAuthorizationType.API_KEY]

        # If Cognito User Pool is provided, add USER_POOL auth
        if cognito_user_pool:
            auth_providers.append(
                AppSyncAuthProvider(
                    authorization_type=AppSyncAuthorizationType.USER_POOL,
                    cognito_config=AppSyncCognitoConfig(
                        user_pool=cognito_user_pool
                    ),
                )
            )
            auth_mode_types.append(AppSyncAuthorizationType.USER_POOL)

        self.api = EventApi(
            self,
            "EventApi",
            api_name="EventsAPI",
            authorization_config=EventApiAuthConfig(
                auth_providers=auth_providers,
                connection_auth_mode_types=auth_mode_types,
                default_publish_auth_mode_types=auth_mode_types,
                default_subscribe_auth_mode_types=auth_mode_types,
            ),
        )

    def add_channel_namespace(self, channel_namespace, subscribe=None, publish=None,
                               sub_invoke_type="REQUEST_RESPONSE", pub_invoke_type="REQUEST_RESPONSE"):
        """
        Adds a channel namespace with optional publish/subscribe Lambda handlers.
        Creates Lambda data sources and binds them with direct=True and configurable invoke type.
        """
        invoke_type_map = {
            "REQUEST_RESPONSE": LambdaInvokeType.REQUEST_RESPONSE,
            "EVENT": LambdaInvokeType.EVENT,
        }

        publish_handler_config = None
        subscribe_handler_config = None

        if publish:
            publish_ds = self.api.add_lambda_data_source(
                f"{channel_namespace}-publish-ds", publish
            )
            publish_handler_config = HandlerConfig(
                data_source=publish_ds,
                direct=True,
                lambda_invoke_type=invoke_type_map[pub_invoke_type],
            )

        if subscribe:
            subscribe_ds = self.api.add_lambda_data_source(
                f"{channel_namespace}-subscribe-ds", subscribe
            )
            subscribe_handler_config = HandlerConfig(
                data_source=subscribe_ds,
                direct=True,
                lambda_invoke_type=invoke_type_map[sub_invoke_type],
            )

        kwargs = {"channel_namespace_name": channel_namespace}
        if publish_handler_config:
            kwargs["publish_handler_config"] = publish_handler_config
        if subscribe_handler_config:
            kwargs["subscribe_handler_config"] = subscribe_handler_config

        self.api.add_channel_namespace(f"{channel_namespace}-ns", **kwargs)
