#!/usr/bin/env python3
import aws_cdk as cdk

from appsync_event_lambda_primitive.appsync_event_lambda_primitive_stack import AppsyncEventLambdaPrimitiveStack
from config import COGNITO_USER_POOL_ID

app = cdk.App()
AppsyncEventLambdaPrimitiveStack(
    app, "DynamoCacheWebBackendStack",
    cognito_user_pool_id=COGNITO_USER_POOL_ID,
    description="Website backend for the DynamoDB-cache travel agent (AppSync Events + Cognito)",
)
app.synth()
