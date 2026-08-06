import json
import logging

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Allow up to 15 minutes for the agent to respond between SSE events.
# The default 60s read_timeout is too short for agents doing web research.
_AGENTCORE_CONFIG = Config(
    read_timeout=900,
    connect_timeout=30,
    retries={"max_attempts": 0},
)


class AgentCoreService:
    """Client for invoking Bedrock AgentCore runtime agents."""

    def __init__(self, agent_arn, agent_qualifier="DEFAULT"):
        """Initialize with agent ARN and optional qualifier.

        Args:
            agent_arn: The ARN of the AgentCore runtime agent.
            agent_qualifier: The agent qualifier. Defaults to "DEFAULT".
        """
        self.client = boto3.client("bedrock-agentcore", config=_AGENTCORE_CONFIG)
        logger.info(
            "AgentCoreService initialized: read_timeout=%s",
            self.client.meta.config.read_timeout,
        )
        self.agent_arn = agent_arn
        self.agent_qualifier = agent_qualifier

    def invoke(self, payload, session_id=None, user_id=None, invocation_callback=None):
        """Invoke the AgentCore runtime and stream events via callback.

        Args:
            payload: A dict to serialize as the invocation payload.
            session_id: Optional runtime session ID.
            user_id: Optional runtime user ID.
            invocation_callback: Optional callable invoked per event.

        Returns:
            A list of collected event strings from the stream.
        """
        kwargs = {
            "agentRuntimeArn": self.agent_arn,
            "qualifier": self.agent_qualifier,
            "payload": json.dumps(payload).encode("utf-8"),
        }

        if session_id is not None:
            # runtimeSessionId must be at least 33 characters
            padded = session_id.ljust(33, "0")
            kwargs["runtimeSessionId"] = padded
        if user_id is not None:
            kwargs["runtimeUserId"] = user_id

        response = self.client.invoke_agent_runtime(**kwargs)

        content = []
        content_type = response.get("contentType", "")

        if "text/event-stream" in content_type:
            for line in response["response"].iter_lines(chunk_size=1):
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data = line[6:]
                        if invocation_callback is not None:
                            invocation_callback(data)
                        content.append(data)
        else:
            # Non-SSE (application/json): the body is a single JSON document.
            # Iterating a StreamingBody yields arbitrary byte chunks that can
            # split mid-JSON, so read it whole and deliver it once.
            body = response.get("response")
            if hasattr(body, "read"):
                data = body.read().decode("utf-8")
                if invocation_callback is not None:
                    invocation_callback(data)
                content.append(data)
            else:
                for event in body or []:
                    if isinstance(event, bytes):
                        event = event.decode("utf-8")
                    if invocation_callback is not None:
                        invocation_callback(event)
                    content.append(event)

        return content
