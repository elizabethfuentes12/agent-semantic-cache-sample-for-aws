import json
import logging
import os
import re
from datetime import datetime, timezone

import config_service
import invocation_service

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LAMBDA_ARN_PATTERN = re.compile(
    r"^arn:aws:lambda:[a-z0-9-]+:\d{12}:function:[a-zA-Z0-9_-]+$"
)
LAMBDA_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
AGENT_CORE_ARN_PATTERN = re.compile(
    r"^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[a-zA-Z0-9_-]+$"
)


def _normalize_attachments(files):
    """Normalize an incoming files payload into a compact, persistable shape.

    The frontend sends file metadata as
    ``{"name", "type", "size", "uploadedFile": {"url"}}``. We flatten that to
    ``{"name", "type", "size", "url"}`` so historical messages can render an
    attachment chip and offer a re-download.

    Args:
        files: A list of file metadata dicts, or None.

    Returns:
        A list of normalized attachment dicts, or None when there is nothing
        usable to persist.
    """
    if not files or not isinstance(files, list):
        return None

    normalized = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        uploaded = entry.get("uploadedFile") or {}
        url = entry.get("url") or (uploaded.get("url") if isinstance(uploaded, dict) else None)
        name = entry.get("name")
        if not url or not name:
            continue
        attachment = {"name": name, "url": url}
        if entry.get("type"):
            attachment["type"] = entry["type"]
        if entry.get("size") is not None:
            attachment["size"] = entry["size"]
        normalized.append(attachment)

    return normalized or None


class InvocationCallback:
    """Bridges AgentCoreService streaming events to AppSync Events publishing."""

    def __init__(self, response_channel, appsync_service):
        """Initialize with target channel and AppSync client.

        Args:
            response_channel: The AppSync Events channel to publish to.
            appsync_service: An AppsyncService instance for publishing.
        """
        self.response_channel = response_channel
        self.appsync_service = appsync_service

    def __call__(self, event):
        """Publish a single event string to the response channel.

        Args:
            event: A string (JSON-encoded event data) to publish.
        """
        self.appsync_service.publish_event(self.response_channel, [event])


class AgentCoreStreamProcessor:
    """Parses AgentCore SSE stream events and publishes typed events to AppSync.

    Only forwards relevant events:
    - tool_call: when a tool is invoked (name + input)
    - tool_result: when a tool returns (name + result preview)
    - message: complete assistant text per cycle
    - complete: final answer at stream end
    """

    def __init__(self, response_channel, appsync_service, persistence_service=None,
                 user_id=None, conversation_id=None, agent_arn=None, model_id=None):
        self.response_channel = response_channel
        self.appsync_service = appsync_service
        self.persistence_service = persistence_service
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.agent_arn = agent_arn
        self.model_id = model_id
        self.cycle_text_parts = []
        self.last_message_text = ""
        self.tool_id_to_name = {}
        self._complete_sent = False
        self._published_tool_calls = set()    # toolUseIds already published as tool_call
        self._published_tool_results = set()  # toolUseIds already published as tool_result

    def _publish(self, payload):
        """Publish a typed JSON event to the AppSync channel.

        Automatically injects metadata into every published event:
        - timestamp: millisecond-precision UTC timestamp for ordering
        - conversation_id: associates the event with a conversation
        - agent_arn: identifies which agent produced the response
        - model_id: identifies which model was used
        """
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        payload = {**payload, "timestamp": ts}
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id
        if self.agent_arn:
            payload["agent_arn"] = self.agent_arn
        if self.model_id:
            payload["model_id"] = self.model_id
        self.appsync_service.publish_event(
            self.response_channel, [json.dumps(payload)]
        )

    def __call__(self, raw_event):
        """Process a single SSE event string from AgentCore.

        Args:
            raw_event: A JSON-encoded string from the AgentCore stream.
        """
        try:
            data = json.loads(raw_event)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Non-JSON event skipped: %s", str(raw_event)[:200])
            return

        # The last event can be a plain string (Python repr of AgentResult) — skip it
        if not isinstance(data, dict):
            logger.info("Non-dict event skipped (type=%s)", type(data).__name__)
            return

        logger.info("Stream event keys: %s", list(data.keys()))

        # --- Plain JSON response (Claude Code agent): single body with the
        # full answer in "result"/"response". The frontend renders text from
        # "message" events and uses "complete" only to stop the spinner, so
        # publish both.
        if "result" in data and "type" not in data and "event" not in data:
            answer = data.get("result") or data.get("response") or ""
            if isinstance(answer, str) and answer.strip():
                self.last_message_text = answer
                self._publish({"type": "message", "content": answer})
                # Forward cache/token metrics from the agent alongside the
                # completion so the dashboard can chart savings per question.
                metric_keys = (
                    "tokens_saved", "cycles", "usage", "plan_hint_used",
                    "tool_cache_hits", "tool_executions", "stale_served",
                    "latency_ms",
                )
                metrics = {k: data[k] for k in metric_keys if k in data}
                self._publish({"type": "complete", "answer": answer, **metrics})
                self._complete_sent = True
                self._persist_assistant_message()
            return

        # --- Pre-processed events from agent (already typed) — pass through ---
        if "type" in data:
            event_type = data["type"]
            if event_type in ("message", "complete", "tool_call", "tool_result", "error"):
                # Dedup: skip tool_call/tool_result if already published for this toolUseId
                tool_use_id = data.get("toolUseId", "")
                if event_type == "tool_call" and tool_use_id:
                    if tool_use_id in self._published_tool_calls:
                        logger.info("Dedup: skipping duplicate tool_call for %s", tool_use_id)
                        return
                    self._published_tool_calls.add(tool_use_id)
                    if tool_use_id and data.get("tool"):
                        self.tool_id_to_name[tool_use_id] = data["tool"]
                elif event_type == "tool_result" and tool_use_id:
                    if tool_use_id in self._published_tool_results:
                        logger.info("Dedup: skipping duplicate tool_result for %s", tool_use_id)
                        return
                    self._published_tool_results.add(tool_use_id)

                logger.info("Passthrough event: type=%s", event_type)
                self._publish(data)
                if event_type == "message":
                    self.last_message_text = data.get("content", "")
                elif event_type == "complete":
                    self.last_message_text = data.get("answer", "")
                    self._complete_sent = True
                    self._persist_assistant_message()
                elif event_type in ("tool_call", "tool_result"):
                    self._persist_event(data)
                return

        # --- Cycle boundary: reset text accumulator ---
        if data.get("start_event_loop"):
            self.cycle_text_parts.clear()
            return

        # --- Skip control events ---
        if data.get("init_event_loop") or data.get("start"):
            return

        # --- Handle Bedrock event wrappers ---
        if "event" in data and len(data) == 1:
            inner = data["event"]
            if not isinstance(inner, dict):
                return

            # Extract text from contentBlockDelta for accumulation
            if "contentBlockDelta" in inner:
                delta = inner["contentBlockDelta"].get("delta", {})
                text = delta.get("text", "")
                if text:
                    self.cycle_text_parts.append(text)
                return

            # Track tool names from contentBlockStart
            if "contentBlockStart" in inner:
                start = inner["contentBlockStart"].get("start", {})
                if "toolUse" in start:
                    tu = start["toolUse"]
                    tool_name = tu.get("name")
                    tool_use_id = tu.get("toolUseId", "")
                    if tool_name and tool_use_id:
                        self.tool_id_to_name[tool_use_id] = tool_name
                return

            # Skip other event wrappers (messageStart, messageStop, metadata, contentBlockStop)
            return

        # --- Track tool names from current_tool_use ---
        if "current_tool_use" in data:
            tool_use = data["current_tool_use"]
            tool_name = tool_use.get("name")
            tool_use_id = tool_use.get("toolUseId") or tool_use.get("id", "")
            if tool_name and tool_use_id:
                self.tool_id_to_name[tool_use_id] = tool_name
            return

        # --- Accumulate text from "data" events (streaming deltas) ---
        if "data" in data and "delta" in data:
            text = data["data"]
            if isinstance(text, str) and text:
                self.cycle_text_parts.append(text)
            return

        # --- Assistant message: extract tool_call blocks + cycle text ---
        if "message" in data:
            msg = data["message"]
            if not isinstance(msg, dict):
                return

            if msg.get("role") == "assistant":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "toolUse" in block:
                        tu = block["toolUse"]
                        tool_name = tu.get("name", "unknown")
                        tool_use_id = tu.get("toolUseId", "")
                        tool_input = tu.get("input", {})
                        if tool_use_id:
                            self.tool_id_to_name[tool_use_id] = tool_name
                        # Dedup: skip if already published via passthrough
                        if tool_use_id and tool_use_id in self._published_tool_calls:
                            logger.info("Dedup: skipping duplicate tool_call (raw) for %s", tool_use_id)
                            continue
                        if tool_use_id:
                            self._published_tool_calls.add(tool_use_id)
                        logger.info("tool_call: %s [%s]", tool_name, tool_use_id)
                        tool_call_event = {
                            "type": "tool_call",
                            "tool": tool_name,
                            "toolUseId": tool_use_id,
                            "input": tool_input,
                        }
                        self._publish(tool_call_event)
                        self._persist_event(tool_call_event)

                cycle_text = "".join(self.cycle_text_parts)
                if cycle_text.strip():
                    self.last_message_text = cycle_text
                    logger.info("message (%d chars): %s", len(cycle_text), cycle_text[:100])
                    message_event = {"type": "message", "content": cycle_text}
                    self._publish(message_event)
                self.cycle_text_parts.clear()
                return

            if msg.get("role") == "user":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and "toolResult" in block:
                        tr = block["toolResult"]
                        tool_use_id = tr.get("toolUseId", "")
                        resolved_name = self.tool_id_to_name.get(tool_use_id, tool_use_id)
                        result_content = tr.get("content", [])
                        result_parts = []
                        for c in (result_content if isinstance(result_content, list) else [result_content]):
                            if isinstance(c, dict) and "text" in c:
                                result_parts.append(c["text"])
                            elif isinstance(c, str):
                                result_parts.append(c)
                        result_text = "\n".join(result_parts) if result_parts else str(result_content)
                        preview = (result_text[:500] + "…") if len(result_text) > 500 else result_text
                        # Dedup: skip if already published via passthrough
                        if tool_use_id and tool_use_id in self._published_tool_results:
                            logger.info("Dedup: skipping duplicate tool_result (raw) for %s", tool_use_id)
                            continue
                        if tool_use_id:
                            self._published_tool_results.add(tool_use_id)
                        logger.info("tool_result: %s [%s]", resolved_name, tool_use_id)
                        tool_result_event = {
                            "type": "tool_result",
                            "tool": resolved_name,
                            "toolUseId": tool_use_id,
                            "result": preview,
                        }
                        self._publish(tool_result_event)
                        self._persist_event(tool_result_event)
                return

        # --- Result event (final): extract answer from result string ---
        if "result" in data:
            return

    def _persist_event(self, event_data):
        """Save an intermediate agent event (tool_call, tool_result, message) to DynamoDB."""
        if self.persistence_service and self.user_id and self.conversation_id:
            try:
                self.persistence_service.save_event(
                    self.user_id, self.conversation_id, event_data
                )
            except Exception:
                logger.exception("Failed to persist %s event", event_data.get("type", "unknown"))

    def _persist_assistant_message(self):
        """Save the assistant's complete answer to DynamoDB if persistence is active."""
        answer = self.last_message_text or "".join(self.cycle_text_parts)
        if answer.strip() and self.persistence_service and self.user_id and self.conversation_id:
            try:
                self.persistence_service.save_assistant_message(
                    self.user_id, self.conversation_id, answer
                )
            except Exception:
                logger.exception("Failed to persist assistant message")

    def finalize(self):
        """Publish the final complete event with the last assistant message."""
        if self._complete_sent:
            return
        answer = self.last_message_text or "".join(self.cycle_text_parts)
        if answer.strip():
            logger.info("complete (%d chars)", len(answer))
            self._publish({"type": "complete", "answer": answer})
            self._persist_assistant_message()


def lambda_handler(event, context):
    """Route incoming AppSync Events to AgentCore or a target Lambda.

    Validates the operation, detects routing target (agent_arn takes
    precedence over target_arn), validates the ARN format, retrieves
    AppSync connection data, and delegates to the appropriate handler.

    Args:
        event: The AppSync Events invocation payload.
        context: The Lambda execution context.

    Returns:
        A dict with statusCode and body.
    """
    try:
        # Validate operation
        operation = event["info"]["operation"]
        if operation != "PUBLISH":
            logger.error("Invalid operation: %s", operation)
            return {"statusCode": 400, "body": f"Invalid operation: {operation}"}

        # Extract payload
        payload = event["events"][0]["payload"]

        # Determine routing target: agent_arn takes precedence over target_arn
        agent_arn = payload.get("agent_arn")
        target_arn = payload.get("target_arn")

        if agent_arn:
            # AgentCore path
            if not AGENT_CORE_ARN_PATTERN.match(agent_arn):
                logger.error("Invalid agent_arn format: %s", agent_arn)
                return {
                    "statusCode": 400,
                    "body": f"Invalid agent_arn format: {agent_arn}",
                }
        elif target_arn is not None:
            # Lambda path — preserve existing validation exactly
            if not target_arn:
                logger.error("Empty target_arn in payload")
                return {"statusCode": 400, "body": "Empty target_arn in payload"}

            if not LAMBDA_ARN_PATTERN.match(
                target_arn
            ) and not LAMBDA_NAME_PATTERN.match(target_arn):
                logger.error("Invalid target_arn format: %s", target_arn)
                return {
                    "statusCode": 400,
                    "body": f"Invalid target_arn format: {target_arn}",
                }
        else:
            # Neither agent_arn nor target_arn present
            logger.error("Missing target_arn or agent_arn in payload")
            return {
                "statusCode": 400,
                "body": "Missing target_arn or agent_arn in payload",
            }

        # Retrieve AppSync connection data from SSM
        try:
            appsync_endpoint = config_service.get_ssm_parameter(
                os.environ["APPSYNC_HTTP_ENDPOINT_PARAM"]
            )
            appsync_api_key = config_service.get_ssm_parameter(
                os.environ["APPSYNC_API_KEY_PARAM"]
            )
        except Exception as e:
            logger.error("Failed to retrieve configuration: %s", e)
            return {
                "statusCode": 500,
                "body": f"Failed to retrieve configuration: {e}",
            }

        # Extract channel path and event ID
        channel_path = event["info"]["channel"]["path"].lstrip("/")
        event_id = event["events"][0]["id"]

        # Build response channel: /response/{original_channel}/{event_id}
        # The leading slash is REQUIRED: AppSync treats "response/x" and
        # "/response/x" as different channels, and subscribers use "/response/...".
        response_namespace = os.environ.get("RESPONSE_NAMESPACE", "response/")
        response_channel = f"/{response_namespace.lstrip('/')}{channel_path}/{event_id}"

        # Extract user_id and conversation_id for persistence
        user_id = payload.get("user_id") or payload.get("userId")
        conversation_id = payload.get("conversation_id") or payload.get("conversationId")
        model_id = payload.get("model_id") or payload.get("modelId")

        persistence_service = None
        if conversation_id and user_id:
            try:
                table_name = config_service.get_ssm_parameter(
                    os.environ.get("CHAT_MESSAGES_TABLE_PARAM", "")
                )
                from chat_persistence_service import ChatPersistenceService
                persistence_service = ChatPersistenceService(table_name)
                persistence_service.ensure_conversation_exists(
                    user_id, conversation_id,
                    agent_arn=agent_arn, model_id=model_id,
                )

                # Extract message content and any attached files
                message = payload.get("message", "")
                message_files = None
                if isinstance(message, dict):
                    message_content = message.get("content", "")
                    message_files = message.get("files")
                else:
                    message_content = message

                # Fall back to a top-level `files` field if the message dict
                # did not carry them.
                if not message_files:
                    message_files = payload.get("files")

                if message_content:
                    persistence_service.save_user_message(
                        user_id,
                        conversation_id,
                        message_content,
                        attachments=_normalize_attachments(message_files),
                    )
            except Exception:
                logger.exception("Failed to initialize chat persistence")
                persistence_service = None

        # Route to appropriate handler
        if agent_arn:
            return _handle_agentcore(
                payload, agent_arn, response_channel,
                appsync_endpoint, appsync_api_key,
                persistence_service=persistence_service,
                user_id=user_id,
                conversation_id=conversation_id,
                model_id=model_id,
            )
        else:
            return _handle_lambda(
                payload, target_arn, response_channel,
                appsync_endpoint, appsync_api_key,
            )

    except Exception:
        logger.exception("Unhandled error in publish handler")
        return {"statusCode": 500, "body": "Internal server error"}


def _handle_agentcore(payload, agent_arn, response_channel,
                      appsync_endpoint, appsync_api_key,
                      persistence_service=None, user_id=None, conversation_id=None,
                      model_id=None):
    """Handle the AgentCore invocation path.

    Args:
        payload: The original event payload (not mutated).
        agent_arn: The validated AgentCore runtime ARN.
        response_channel: The AppSync response channel path.
        appsync_endpoint: The AppSync HTTP endpoint.
        appsync_api_key: The AppSync API key.
        persistence_service: Optional ChatPersistenceService instance.
        user_id: Optional user ID for persistence.
        conversation_id: Optional conversation ID for persistence.
        model_id: Optional model ID for the agent invocation.

    Returns:
        A dict with statusCode and body.
    """
    from agent_core_service import AgentCoreService
    from appsync_service import AppsyncService

    agent_qualifier = payload.get("agent_qualifier", "DEFAULT")
    message = payload.get("message", "")
    session_id = payload.get("session_id") or payload.get("sessionId")
    user_id = payload.get("user_id") or payload.get("userId")

    # Extract prompt text: message can be a dict {"content": "..."} or a plain string
    if isinstance(message, dict):
        prompt_text = message.get("content", "")
        files = message.get("files", [])
    else:
        prompt_text = message
        files = []

    # Build AgentCore invocation payload (new dict — no mutation of original)
    agent_payload = {"prompt": prompt_text}
    if files or "files" in payload:
        agent_payload["files"] = files or payload["files"]
    if "selected_tools" in payload:
        agent_payload["selected_tools"] = payload["selected_tools"]
    if user_id:
        agent_payload["user_id"] = user_id

    if not model_id:
        model_id = payload.get("model_id") or payload.get("modelId")
    if model_id:
        agent_payload["model_id"] = model_id
        # The Claude Code agent server reads the override as "model"
        agent_payload["model"] = model_id

    # Create services
    appsync_svc = AppsyncService(appsync_endpoint, appsync_api_key)
    agent_service = AgentCoreService(agent_arn, agent_qualifier)
    processor = AgentCoreStreamProcessor(
        response_channel, appsync_svc,
        persistence_service=persistence_service,
        user_id=user_id,
        conversation_id=conversation_id,
        agent_arn=agent_arn,
        model_id=model_id,
    )

    try:
        agent_service.invoke(
            payload=agent_payload,
            session_id=session_id,
            user_id=user_id,
            invocation_callback=processor,
        )
        processor.finalize()
        return {"statusCode": 200, "body": "OK"}
    except Exception as e:
        logger.error("AgentCore invocation failed: %s", e)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        error_payload = {"type": "error", "error": str(e), "timestamp": ts}
        if conversation_id:
            error_payload["conversation_id"] = conversation_id
        if agent_arn:
            error_payload["agent_arn"] = agent_arn
        if model_id:
            error_payload["model_id"] = model_id
        appsync_svc.publish_event(response_channel, [json.dumps(error_payload)])
        return {"statusCode": 500, "body": "AgentCore invocation failed"}


def _handle_lambda(payload, target_arn, response_channel,
                   appsync_endpoint, appsync_api_key):
    """Handle the existing Lambda invocation path.

    Args:
        payload: The original event payload (not mutated).
        target_arn: The validated Lambda ARN or function name.
        response_channel: The AppSync response channel path.
        appsync_endpoint: The AppSync HTTP endpoint.
        appsync_api_key: The AppSync API key.

    Returns:
        A dict with statusCode and body.
    """
    # Build enriched payload (new dict — no mutation of original)
    enriched_payload = dict(payload)
    enriched_payload["appsync_endpoint"] = appsync_endpoint
    enriched_payload["appsync_api_key"] = appsync_api_key
    enriched_payload["channel"] = response_channel

    # Invoke target Lambda
    try:
        response = invocation_service.invoke_lambda(target_arn, enriched_payload)
    except Exception as e:
        logger.error("Lambda invocation failed: %s", e)
        return {"statusCode": 500, "body": "Internal server error"}

    status_code = response["StatusCode"]
    if status_code != 202:
        logger.error(
            "Target invocation failed with status %s", status_code
        )
        return {
            "statusCode": 502,
            "body": f"Target invocation failed with status {status_code}",
        }

    logger.info(
        "Successfully invoked %s for channel %s", target_arn, response_channel
    )
    return {"statusCode": 200, "body": "OK"}
