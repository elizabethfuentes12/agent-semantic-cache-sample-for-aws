#!/usr/bin/env python3
import aws_cdk as cdk

from ai_agent_website_primitive.ai_agent_website_primitive_stack import AiAgentWebsitePrimitiveStack

app = cdk.App()
AiAgentWebsitePrimitiveStack(app, "DynamoCacheWebsiteStack")
app.synth()
