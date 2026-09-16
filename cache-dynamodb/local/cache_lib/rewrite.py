"""Cross-language rewrite on a response-cache hit (a cheap Nova Lite call).

Titan Text Embeddings V2 is multilingual, so a question asked in Spanish can hit
an answer that was cached in English (measured similarity ~0.93). The embedding
does the MATCHING; it does not translate the stored text. Without a rewrite, the
hit would return the English answer to a Spanish question.

Rewrite (option 2) fixes only the language of the answer on such a hit:

* On a plain same-language hit the model does NOT run at all (the response cache
  already returned 0 tokens via ``event.cancel``). This module is only invoked
  by the harness AFTER a hit, and only when we want the answer in the question's
  language.
* The rewrite is a single call to a CHEAP model (Amazon Nova Lite). It does not
  research or add facts; it only expresses the already-verified answer in the
  question's language. If the answer is already in that language, the model says
  so and returns it unchanged (no wasted translation).
* ``language_differs()`` decides whether that call is worth making at all,
  BEFORE paying for it. Asking the model "is this the same language?" costs the
  same as a translation, and on short answers the rewrite costs more tokens than
  the hit saves, so a same-language paraphrase is served verbatim. This mirrors
  the deployed travel-agent Lambda, which gates its rewrite the same way.

This uses Strands structured output (``structured_output_model=Localized``):
https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/
so the harness gets a typed, validated object instead of parsing free text.
"""

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_REWRITE_PROMPT = (
    "You adapt an already-verified answer so its language matches the question. "
    "Do not add facts, do not research, do not change meaning or numbers. If the "
    "answer is already written in the same language as the question, set "
    "same_language=true and return it unchanged. Otherwise translate it "
    "faithfully into the question's language and set same_language=false. Keep it "
    "plain text, no XML tags."
)


# Language markers - the same sets the deployed travel-agent Lambda uses.
_ES_MARKERS = {"que", "necesito", "para", "cuando", "cual", "como", "donde",
               "el", "la", "los", "las", "un", "una", "es", "si", "de", "mi"}
_EN_MARKERS = {"the", "what", "when", "which", "how", "where", "do", "does",
               "need", "is", "are", "a", "an", "to", "for", "my", "i"}


def language_differs(question: str, cached_answer: str) -> bool:
    """True when the question and the cached answer look like different languages.

    A cheap word-marker heuristic, deliberately run BEFORE the model call: the
    rewrite is only worth its tokens when the languages actually differ. On a
    same-language paraphrase this returns False and the cached answer is served
    verbatim at 0 tokens.
    """
    def score(text: str) -> int:
        words = set(text.lower().split())
        return len(words & _ES_MARKERS) - len(words & _EN_MARKERS)

    return (score(question) > 0) != (score(cached_answer) > 0)


class Localized(BaseModel):
    """The cached answer, expressed in the SAME language as the question."""

    same_language: bool = Field(
        description="true if the cached answer was already in the question's language"
    )
    answer: str = Field(
        description="the answer in the question's language; unchanged if already matching"
    )


def rewrite_to_question_language(question: str, cached_answer: str,
                                 model_id: str, region: str) -> dict:
    """Return the cached answer in the question's language.

    Runs one cheap structured-output call. On any error it fails open: the
    original answer is returned unchanged, so a rewrite failure never blocks a
    cache hit.

    Returns a dict: ``{answer, rewritten (bool), tokens}``.
    """
    try:
        from strands import Agent
        from strands.models import BedrockModel

        model = BedrockModel(model_id=model_id, region_name=region)
        agent = Agent(model=model, callback_handler=None,
                      system_prompt=_REWRITE_PROMPT)
        result = agent(
            f"QUESTION:\n{question}\n\nCACHED ANSWER:\n{cached_answer}",
            structured_output_model=Localized,
        )
        localized = result.structured_output
        tokens = int(result.metrics.accumulated_usage.get("totalTokens", 0))
        return {
            "answer": localized.answer or cached_answer,
            "rewritten": not localized.same_language,
            "tokens": tokens,
        }
    except Exception:
        logger.exception("cross-language rewrite failed, returning cached answer as-is")
        return {"answer": cached_answer, "rewritten": False, "tokens": 0}
