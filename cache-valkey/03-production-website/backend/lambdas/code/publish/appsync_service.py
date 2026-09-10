import json
import logging
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class AppsyncService:
    """HTTP client for publishing events to the AppSync Events API."""

    def __init__(self, api_endpoint, api_key):
        self.api_endpoint = api_endpoint
        self.api_key = api_key

    def publish_event(self, channel, events):
        """Publish an event to the AppSync Events API.

        Args:
            channel: The channel path to publish to.
            events: A list of event payloads.

        Returns:
            True if the publish was successful (HTTP 200), False otherwise.
        """
        url = f"https://{self.api_endpoint}/event"
        payload = json.dumps({"channel": channel, "events": events}).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            response = urllib.request.urlopen(request)  # nosemgrep: dynamic-urllib-use-detected  # nosec B310 - URL built from a fixed AppSync endpoint, not user-controlled
            if response.status == 200:
                return True
            logger.error(
                "AppSync publish failed with status %d: %s",
                response.status,
                response.read().decode("utf-8", errors="replace"),
            )
            return False
        except Exception:
            logger.exception("Exception during AppSync publish to channel %s", channel)
            return False
