"""A2 — Distilled Strategy Memory agent (ReasoningBank/Memp pattern).

Based on arXiv:2509.25140 (ICLR 2026) and arXiv:2508.06433 (ACL 2026): after
each run, distill a SHORT transferable strategy ("for multi-topic travel
questions, resolve the destination first; query Wikipedia with 'Visa policy
of X'"), not the raw trajectory. On similar questions the top strategies are
injected into the system prompt: the agent still reasons, but guided, which
cuts exploration. Failures also produce strategies ("do not retry a failed
tool with title variations").

Key design choices from the literature:
- store distilled abstractions, never raw trajectories (consensus finding,
  arXiv:2604.27003)
- cap the pool and refresh duplicates instead of appending forever (ReMe,
  arXiv:2512.10696)
- report distillation cost as overhead_tokens (arXiv:2606.15017)
"""

import json
import logging
import time
import uuid

from bedrock_agentcore import BedrockAgentCoreApp

import agent_common as common
from tools import ALL_TOOLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

STRAT_INDEX = "idx:stratmem"
PREFIX_STRAT_VEC = "stratmem:vec:"
PREFIX_STRAT_TXT = "stratmem:txt:"
THRESHOLD = 0.80   # strategies generalize; looser than answer caching
TOP_K = 3
TTL = 7 * 86400
MAX_STRATEGY_CHARS = 400

SYSTEM_PROMPT = (
    "You are a travel research assistant. Use the tools to gather real data. "
    "If a tool fails, do not retry it with variations more than once. "
    "Maximum 4 sentences, plain text, in the user's language."
)

DISTILL_SYSTEM = (
    "You distill ONE reusable strategy from an agent run. Given the QUESTION, "
    "the TOOL CALLS (with success/failure), and TOKENS spent, write a single "
    "imperative strategy (max 2 sentences, under 300 characters) that would "
    "make a SIMILAR future question cheaper or more reliable. Generalize: no "
    "specific city/country names — use placeholders like <destination>. "
    "Output the strategy text only."
)


def _top_strategies(client, question: str) -> tuple[list, list]:
    """Retrieve up to TOP_K distinct strategies above threshold."""
    from embeddings import embedding_to_bytes, generate_embedding

    query_vec = embedding_to_bytes(generate_embedding(question))
    result = client.execute_command(
        "FT.SEARCH", STRAT_INDEX,
        f"*=>[KNN {TOP_K} @embedding $vec AS score]",
        "PARAMS", "2", "vec", query_vec,
        "RETURN", "2", "entry_id", "score",
        "DIALECT", "2",
    )
    strategies, ids = [], []
    if not result or int(result[0]) == 0:
        return strategies, ids
    for i in range(1, len(result), 2):
        fields = result[i + 1]
        doc = {}
        for j in range(0, len(fields), 2):
            k = fields[j].decode() if isinstance(fields[j], bytes) else fields[j]
            v = fields[j + 1].decode() if isinstance(fields[j + 1], bytes) else fields[j + 1]
            doc[k] = v
        similarity = 1.0 - (float(doc["score"]) / 2.0)
        if similarity < THRESHOLD:
            continue
        text = client.get(f"{PREFIX_STRAT_TXT}{doc['entry_id']}")
        if text:
            strategies.append(text.decode())
            ids.append(doc["entry_id"])
    return strategies, ids


@app.entrypoint
def invoke(payload):
    """Payload: {"prompt": "..."}"""
    question = (payload.get("prompt") or "").strip()
    if not question:
        return {"error": "payload must include a 'prompt' string"}
    started = time.time()
    node, _ = common.get_clients()
    common.ensure_vector_index(node, STRAT_INDEX, PREFIX_STRAT_VEC)
    flow = []
    overhead = 0

    flow.append({"step": "strategy_lookup", "store": "node-based",
                 "detail": f"KNN for top-{TOP_K} strategies"})
    strategies, _ids = _top_strategies(node, question)

    system_prompt = SYSTEM_PROMPT
    if strategies:
        guidance = "\n".join(f"- {s}" for s in strategies)
        system_prompt += (
            "\n\nStrategies learned from similar past tasks (follow them "
            "unless clearly inapplicable):\n" + guidance
        )
        flow.append({"step": "strategies_injected", "kind": "hit",
                     "detail": f"{len(strategies)} distilled strategies added to prompt"})
    else:
        flow.append({"step": "strategy_miss", "kind": "miss",
                     "detail": "no strategies yet for this kind of question"})

    from strands import Agent
    from strands.hooks import AfterToolCallEvent

    trajectory = []

    def capture(event):
        failed = isinstance(event.result, Exception) or (
            isinstance(event.result, dict) and event.result.get("status") == "error"
        )
        trajectory.append({"tool": event.tool_use["name"],
                           "args": dict(event.tool_use["input"]),
                           "failed": failed})

    agent = Agent(model=common.get_model(), system_prompt=system_prompt, tools=ALL_TOOLS)
    agent.add_hook(capture, AfterToolCallEvent)
    result = agent(question)
    usage = dict(result.metrics.accumulated_usage)
    answer = common.clean_answer(str(result))

    # --- distill ONE strategy from this run (successes and failures alike) ---
    baseline_key = f"stratmem:baseline:{'-'.join(sorted({t['tool'] for t in trajectory}))}"
    prior_baseline = node.get(baseline_key)
    baseline = int(prior_baseline) if (prior_baseline and strategies) else 0

    strategy_text, distill_tokens = common.llm_call(
        DISTILL_SYSTEM,
        f"QUESTION: {question}\nTOOL CALLS: {json.dumps(trajectory, default=str)}\n"
        f"TOKENS: {usage.get('totalTokens', 0)}",
    )
    overhead += distill_tokens
    strategy_text = strategy_text.strip()[:MAX_STRATEGY_CHARS]
    if strategy_text:
        entry_id = str(uuid.uuid4())
        node.set(f"{PREFIX_STRAT_TXT}{entry_id}", strategy_text, ex=TTL)
        common.store_vector(node, PREFIX_STRAT_VEC, entry_id, question, TTL)
        flow.append({"step": "strategy_stored", "kind": "store", "store": "node-based",
                     "detail": strategy_text[:110]})
    if not strategies:
        # first run for this tool-set: record its cost as the cold baseline
        node.set(baseline_key, str(usage.get("totalTokens", 0)), ex=TTL)

    return common.response_payload(
        answer, usage, overhead, baseline, flow, started,
        extra={"source": "strategy-memory" if strategies else "agent",
               "cycles": result.metrics.cycle_count,
               "strategies_used": len(strategies)},
    )


if __name__ == "__main__":
    app.run()
