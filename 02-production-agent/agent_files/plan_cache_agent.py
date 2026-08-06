"""A1 — Plan Template Cache agent (Agentic Plan Caching pattern).

Based on arXiv:2506.14852 (NeurIPS 2025, reported -50.31% cost): cache the
PLAN as a template with slots, not the trajectory. On a hit the expensive
planning loop is skipped entirely:

    cold:  agent loop plans + executes  -> extract template (cheap LLM call)
    warm:  match template -> cheap LLM fills slots -> execute tools DIRECTLY
           (no agent loop) -> one synthesis call writes the answer

The reasoning saving is structural: deliberation cycles are replaced by one
small slot-filling call. overhead_tokens reports extraction + adaptation so
savings are budget-honest (arXiv:2606.15017).
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

PLAN_INDEX = "idx:plancache"
PREFIX_PLAN_VEC = "plancache:vec:"
PREFIX_PLAN_TPL = "plancache:tpl:"
THRESHOLD = 0.85
TTL = 86400

TOOLS_BY_NAME = {t.tool_name: t for t in ALL_TOOLS}

SYSTEM_PROMPT = (
    "You are a travel research assistant. Use the tools to gather real data. "
    "If a tool fails, do not retry it with variations more than once. "
    "Maximum 4 sentences, plain text, in the user's language."
)

EXTRACT_SYSTEM = (
    "You extract reusable plan templates from an executed tool sequence. "
    "Given a QUESTION and the TOOL CALLS that answered it, output JSON only:\n"
    '{"intent": "<short intent label>", "slots": {"<slot>": "<value from the question>"},\n'
    ' "steps": [{"tool": "<name>", "args": {"<arg>": "<literal or {slot}>"}}]}\n'
    "Replace question-specific values in args with {slot} placeholders. "
    "Keep args that never change literal."
)

ADAPT_SYSTEM = (
    "You fill a plan template's slots using a new question. Given the TEMPLATE "
    "and the QUESTION, output JSON only: {\"slots\": {\"<slot>\": \"<value>\"}}. "
    "If the question does not fit the template's intent, output {\"slots\": null}."
)

SYNTH_SYSTEM = (
    "You are a travel research assistant. Using ONLY the tool results given, "
    "answer the user's question. Maximum 4 sentences, plain text, in the "
    "user's language."
)


def _execute_steps(steps: list, slots: dict, flow: list) -> list:
    """Run the planned tool calls directly — no agent loop. @tool functions
    remain plain callables in Strands, so this is a straight function call."""
    results = []
    for step in steps:
        name = step["tool"]
        tool_fn = TOOLS_BY_NAME.get(name)
        if not tool_fn:
            continue
        args = {}
        for key, value in step["args"].items():
            if isinstance(value, str):
                for slot, filled in slots.items():
                    value = value.replace("{" + slot + "}", str(filled))
            args[key] = value
        try:
            # prior steps' outputs may feed later args ({geocode.latitude})
            for i, prior in enumerate(results):
                if isinstance(prior["output"], str) and prior["output"].startswith("{"):
                    try:
                        parsed = json.loads(prior["output"])
                        for pk, pv in parsed.items():
                            token = "{" + prior["tool"] + "." + pk + "}"
                            args = {k: (str(pv) if v == token else v) for k, v in args.items()}
                    except (json.JSONDecodeError, TypeError):
                        pass
            coerced = {}
            for k, v in args.items():
                if isinstance(v, str) and k in ("latitude", "longitude"):
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                coerced[k] = v
            output = tool_fn(**coerced)
            results.append({"tool": name, "args": coerced, "output": output})
            flow.append({"step": "tool_executed", "kind": "miss", "tool": name,
                         "detail": "executed directly from cached plan"})
        except Exception as exc:
            logger.exception("planned step failed")
            results.append({"tool": name, "args": args, "output": f"error: {exc}"})
    return results


@app.entrypoint
def invoke(payload):
    """Payload: {"prompt": "..."}"""
    question = (payload.get("prompt") or "").strip()
    if not question:
        return {"error": "payload must include a 'prompt' string"}
    started = time.time()
    node, _ = common.get_clients()
    common.ensure_vector_index(node, PLAN_INDEX, PREFIX_PLAN_VEC)
    flow = []
    overhead = 0

    # --- lookup: is there a plan template for a similar question? ---
    flow.append({"step": "plan_lookup", "store": "node-based",
                 "detail": "KNN over cached plan templates"})
    entry_id, similarity = common.knn_lookup(node, PLAN_INDEX, question, THRESHOLD)

    if entry_id:
        raw = node.get(f"{PREFIX_PLAN_TPL}{entry_id}")
        template = json.loads(raw) if raw else None
        if template:
            baseline = int(template.get("cold_tokens", 0))
            # --- adapt: cheap slot-filling call (the ONLY reasoning spent) ---
            adapted, adapt_tokens = common.llm_call(
                ADAPT_SYSTEM,
                f"TEMPLATE: {json.dumps({k: template[k] for k in ('intent', 'slots', 'steps')})}\n"
                f"QUESTION: {question}",
            )
            overhead += adapt_tokens
            try:
                slots = common.parse_json_block(adapted).get("slots")
            except (ValueError, json.JSONDecodeError):
                slots = None
            if slots:
                flow.append({"step": "plan_hit", "kind": "hit",
                             "detail": f"similarity {similarity:.2f} — planner SKIPPED, "
                                       f"slots adapted with {adapt_tokens} tokens"})
                results = _execute_steps(template["steps"], slots, flow)
                summary = "\n".join(
                    f"[{r['tool']}({json.dumps(r['args'], default=str)})]: {str(r['output'])[:600]}"
                    for r in results
                )
                answer, synth_tokens = common.llm_call(
                    SYNTH_SYSTEM, f"QUESTION: {question}\nTOOL RESULTS:\n{summary}"
                )
                flow.append({"step": "synthesis", "kind": "hit",
                             "detail": f"single synthesis call ({synth_tokens} tokens)"})
                return common.response_payload(
                    answer, {"totalTokens": synth_tokens}, overhead, baseline,
                    flow, started, extra={"source": "plan-cache", "similarity": round(similarity, 4)},
                )
            flow.append({"step": "plan_adapt_failed", "kind": "miss",
                         "detail": "template did not fit — falling back to full agent"})

    # --- miss: full agent loop, then extract + store the template ---
    flow.append({"step": "plan_miss", "kind": "miss",
                 "detail": "no matching plan — running the full agent loop"})
    from strands import Agent

    trajectory = []

    def capture(event):
        trajectory.append({"tool": event.tool_use["name"],
                           "args": dict(event.tool_use["input"])})

    from strands.hooks import BeforeToolCallEvent

    agent = Agent(model=common.get_model(), system_prompt=SYSTEM_PROMPT, tools=ALL_TOOLS)
    agent.add_hook(capture, BeforeToolCallEvent)
    result = agent(question)
    usage = dict(result.metrics.accumulated_usage)
    answer = common.clean_answer(str(result))

    if trajectory:
        extracted, extract_tokens = common.llm_call(
            EXTRACT_SYSTEM,
            f"QUESTION: {question}\nTOOL CALLS: {json.dumps(trajectory, default=str)}",
        )
        overhead += extract_tokens
        try:
            template = common.parse_json_block(extracted)
            template["cold_tokens"] = usage.get("totalTokens", 0)
            entry_id = str(uuid.uuid4())
            node.set(f"{PREFIX_PLAN_TPL}{entry_id}", json.dumps(template), ex=TTL)
            common.store_vector(node, PREFIX_PLAN_VEC, entry_id, question, TTL)
            flow.append({"step": "plan_stored", "kind": "store", "store": "node-based",
                         "detail": f"template '{template.get('intent', '?')}' extracted "
                                   f"({extract_tokens} tokens overhead)"})
        except (ValueError, json.JSONDecodeError):
            logger.warning("template extraction returned invalid JSON, skipping store")

    return common.response_payload(
        answer, usage, overhead, 0, flow, started,
        extra={"source": "agent", "cycles": result.metrics.cycle_count},
    )


if __name__ == "__main__":
    app.run()
