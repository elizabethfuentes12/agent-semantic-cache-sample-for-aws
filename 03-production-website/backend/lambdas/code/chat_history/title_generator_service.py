"""Title generation service backed by Amazon Bedrock.

Generates a short, human-friendly conversation title from the dialogue so
far. Uses the Bedrock Runtime ``converse`` API (available through the boto3
version bundled in the Lambda runtime) — no extra dependencies or layers.

The service is intentionally small and self-contained so it can be swapped
for a Strands Agent implementation later without touching the callers.
"""

import logging
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Hard limits to keep titles tidy and cheap to generate.
MAX_TITLE_CHARS = 60
MAX_TRANSCRIPT_CHARS = 6000

_SYSTEM_PROMPT = (
    "You generate short, specific titles for chat conversations. "
    "Given a transcript, respond with a single title of 2 to 4 words that "
    "names the concrete subject of the conversation. Use the distinctive "
    "keywords (the specific technology, error, task, or entity discussed) "
    "so it is instantly recognizable. Do NOT use vague or generic wording "
    "such as 'help with', 'assistance', 'question about', 'analysis of', or "
    "'conversation about'. Prefer nouns; drop filler words. Reply with the "
    "title only — no quotes, no trailing punctuation, no preamble. Write it "
    "in the same language the user used."
)


class TitleGeneratorService:
    """Generates conversation titles using a Bedrock model."""

    def __init__(self, model_id: str, region_name: str | None = None):
        """Initialize with the default model id.

        Args:
            model_id: The Bedrock model (or inference profile) id to use.
            region_name: Optional region override for the Bedrock client.
        """
        self.model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region_name)

    @staticmethod
    def _sanitize(text: str) -> str:
        """Reduce model output to a single clean title line.

        Strips whitespace/newlines, surrounding quotes, and trailing
        punctuation, then caps the length.
        """
        # Collapse to the first non-empty line and normalize whitespace.
        first_line = ""
        for line in text.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        title = re.sub(r"\s+", " ", first_line).strip()

        # Strip surrounding quotes and trailing punctuation.
        title = title.strip("\"'“”‘’")
        title = title.rstrip(" .,:;-–—")

        if len(title) > MAX_TITLE_CHARS:
            title = title[:MAX_TITLE_CHARS].rstrip()

        return title

    def generate_title(self, transcript: str, model_id: str | None = None) -> str:
        """Generate a title from a conversation transcript.

        Args:
            transcript: The formatted conversation transcript.
            model_id: Optional per-request model override.

        Returns:
            A short single-line title.

        Raises:
            ValueError: If the transcript is empty.
            RuntimeError: If the model returns no usable text.
        """
        if not transcript or not transcript.strip():
            raise ValueError("Transcript must not be empty")

        transcript = transcript[:MAX_TRANSCRIPT_CHARS]

        response = self._client.converse(
            modelId=model_id or self.model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                "Suggest a title for this conversation:\n\n"
                                f"{transcript}"
                            )
                        }
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 30, "temperature": 0.2},
        )

        parts = (
            response.get("output", {})
            .get("message", {})
            .get("content", [])
        )
        raw = "".join(p.get("text", "") for p in parts if isinstance(p, dict))

        title = self._sanitize(raw)
        if not title:
            raise RuntimeError("Model returned an empty title")

        logger.info("Generated conversation title: %s", title)
        return title
