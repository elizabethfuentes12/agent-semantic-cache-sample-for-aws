"""A1 — Plan Template Cache agent (DynamoDB variant).

Based on arXiv:2506.14852 (NeurIPS 2025, reported -50.31% cost): cache the
PLAN as a template with slots, not the trajectory. On a hit the expensive
planning loop is skipped entirely:

    cold:  agent loop plans + executes  -> extract template (cheap LLM call)
    warm:  match template -> cheap LLM fills slots -> execute tools DIRECTLY
           (no agent loop) -> one synthesis call writes the answer

DynamoDB replaces the two Valkey KV+vector stores. No VPC required.
PlanTemplateCache from dynamodb_cache handles all storage.
"""

import json
import logging
import time
import uuid

from bedrock_agentcore import BedrockAgentCoreApp

import agent_common as common
from dynamodb_cache import PlanTemplateCache
from tools import ALL_TOOLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

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
    "Rules:\n"
    "- Replace question-specific values (destination names, dates) with {slot} placeholders.\n"
    "- For args derived from a prior step's output (e.g. latitude/longitude from geocode_destination), "
    "use the format {tool_name.key} — for example {geocode_destination.latitude}. "
    "Never use short aliases like {lat} or {latitude} for derived values.\n"
    "- Keep args that never change as literal values."
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

_plan_cache = None


def _get_plan_cache() -> PlanTemplateCache:
    global _plan_cache
    if _plan_cache is None:
        import boto3
        params = common.get_params()
        _plan_cache = PlanTemplateCache(
            ddb_client=boto3.client("dynamodb"),
            table_name=params["table-name"],
            vector_index=params["vector-index-name"],
            threshold=THRESHOLD,
            ttl=TTL,
        )
    return _plan_cache


def _execute_steps(steps: list, slots: dict, flow: list) -> list:
    """Run the planned tool calls directly — no agent loop.

    @tool functions remain plain callables in Strands (straight function call).
    Accumulates derived key-value pairs from each successful step's JSON output
    so later steps can reference them as {tool_name.key} tokens.
    """
    results = []
    derived: dict = {}

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
                for derived_key, derived_val in derived.items():
                    value = value.replace("{" + derived_key + "}", str(derived_val))
                _lat = derived.get("geocode_destination.latitude")
                _lon = derived.get("geocode_destination.longitude")
                if value in ("{latitude}", "{lat}") and _lat is not None:
                    value = str(_lat)
                elif value in ("{longitude}", "{lon}", "{lng}") and _lon is not None:
                    value = str(_lon)
            args[key] = value

        coerced = {}
        for k, v in args.items():
            if isinstance(v, str) and k in ("latitude", "longitude"):
                try:
                    v = float(v)
                except ValueError:
                    pass
            coerced[k] = v

        try:
            output = tool_fn(**coerced)
            results.append({"tool": name, "args": coerced, "output": output})
            flow.append({"step": "tool_executed", "kind": "miss", "tool": name,
                         "detail": "executed directly from cached plan"})
            if isinstance(output, str) and output.startswith("{"):
                try:
                    for pk, pv in json.loads(output).items():
                        derived[f"{name}.{pk}"] = pv
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception as exc:
            logger.exception("planned step failed: %s args=%s", name, coerced)
            results.append({"tool": name, "args": args, "output": f"error: {exc}"})
            flow.append({"step": "tool_failed", "kind": "miss", "tool": name,
                         "detail": str(exc)[:120]})

    return results


@app.entrypoint
def invoke(payload):
    """Payload: {"prompt": "..."} or {"action": "flush_plan"}"""
    if payload.get("action") == "flush_plan":
        count = _get_plan_cache().flush()
        return {"flushed_plan_entries": count}

    question = (payload.get("prompt") or "").strip()
    if not question:
        return {"error": "payload must include a 'prompt' string"}

    started = time.time()
    plan_cache = _get_plan_cache()
    flow = []
    overhead = 0

    flow.append({"step": "plan_lookup", "store": "dynamodb",
                 "detail": "KNN over cached plan templates"})
    template_str, baseline = plan_cache.lookup(question)

    if template_str:
        try:
            template = json.loads(template_str)
        except json.JSONDecodeError:
            template = None

        if template:
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
                             "detail": f"planner SKIPPED, slots adapted with {adapt_tokens} tokens"})
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
                    flow, started, extra={"source": "plan-cache"},
                )
            flow.append({"step": "plan_adapt_failed", "kind": "miss",
                         "detail": "template did not fit — falling back to full agent"})

    flow.append({"step": "plan_miss", "kind": "miss",
                 "detail": "no matching plan — running the full agent loop"})

    from strands import Agent
    from strands.hooks import BeforeToolCallEvent

    trajectory = []

    def capture(event):
        trajectory.append({"tool": event.tool_use["name"],
                           "args": dict(event.tool_use["input"])})

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
            plan_cache.store(question, template, usage.get("totalTokens", 0))
            flow.append({"step": "plan_stored", "kind": "store", "store": "dynamodb",
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
