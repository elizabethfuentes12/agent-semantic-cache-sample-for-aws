"""A3 — Skill Induction agent (Agent Skills / Trace2Skill pattern).

Based on arXiv:2603.25158 and the Agent Skills open standard
(agentskills.io) that Strands supports: consolidate trajectories into
SKILL.md-style SOPs (standard operating procedures). Unlike A2's per-run
strategies, skills are induced from SEVERAL trajectories of the same intent
(consolidation threshold) and are ALWAYS in context via progressive
disclosure: only name+description in the prompt; the agent loads the full
SOP with a tool when the task matches — no retrieval infrastructure.

The skill body is markdown the agent itself wrote from its own repeated
reasoning: the "agent codifies its own patterns" story, on Valkey.
"""

import json
import logging
import time
import uuid

from bedrock_agentcore import BedrockAgentCoreApp
from strands import tool

import agent_common as common
from tools import ALL_TOOLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

SKILL_LIST = "skills:index"          # hash: skill_id -> name|description
PREFIX_SKILL = "skills:body:"        # full SKILL.md body
PREFIX_TRAJ = "skills:traj:"         # raw trajectories awaiting consolidation
TRAJ_LIST = "skills:traj:pending"
CONSOLIDATE_AFTER = 2                # induce a skill once N similar runs exist
TTL = 14 * 86400

SYSTEM_PROMPT = (
    "You are a travel research assistant. Use the tools to gather real data. "
    "If a tool fails, do not retry it with variations more than once. "
    "Maximum 4 sentences, plain text, in the user's language.\n\n"
    "You may have SKILLS: proven procedures induced from your own past work. "
    "Their names and descriptions are listed below; call load_skill(name) "
    "BEFORE planning if one matches the task — following a skill is cheaper "
    "and more reliable than reasoning from scratch.\n{skill_index}"
)

INDUCE_SYSTEM = (
    "You write an agent skill (SOP) by consolidating several tool-call "
    "trajectories that solved the same kind of task. Output markdown with "
    "EXACTLY this structure:\n"
    "NAME: <kebab-case-name>\n"
    "DESCRIPTION: <one line: when to use this skill>\n"
    "STEPS:\n1. <tool>(<args pattern>) — <why>\n...\n"
    "NOTES:\n- <pitfalls seen in the trajectories, e.g. failed retries>\n"
    "Generalize argument values with <placeholders>."
)


def _skill_index(client) -> str:
    entries = client.hgetall(SKILL_LIST)
    if not entries:
        return "(no skills induced yet)"
    lines = []
    for _sid, meta in entries.items():
        name, description = meta.decode().split("|", 1)
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)


def _make_load_skill(client):
    @tool
    def load_skill(name: str) -> str:
        """Load the full procedure (SOP) for a named skill from the skill
        library. Call this before planning when a listed skill matches.

        Args:
            name: The skill name exactly as listed in the system prompt.
        """
        for sid, meta in client.hgetall(SKILL_LIST).items():
            skill_name = meta.decode().split("|", 1)[0]
            if skill_name == name.strip():
                body = client.get(f"{PREFIX_SKILL}{sid.decode()}")
                return body.decode() if body else "Skill body expired."
        return f"No skill named '{name}'."

    return load_skill


def _maybe_consolidate(client, flow: list) -> int:
    """Induce a skill when enough pending trajectories share an intent.
    Returns overhead tokens spent on induction."""
    pending = client.lrange(TRAJ_LIST, 0, -1)
    if len(pending) < CONSOLIDATE_AFTER:
        return 0
    trajectories = [json.loads(client.get(p) or b"{}") for p in pending]
    trajectories = [t for t in trajectories if t]
    if len(trajectories) < CONSOLIDATE_AFTER:
        client.delete(TRAJ_LIST)
        return 0
    induced, tokens = common.llm_call(
        INDUCE_SYSTEM, json.dumps(trajectories[:4], default=str)
    )
    name, description = "unnamed-skill", ""
    for line in induced.splitlines():
        if line.startswith("NAME:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("DESCRIPTION:"):
            description = line.split(":", 1)[1].strip()
    sid = str(uuid.uuid4())
    client.hset(SKILL_LIST, sid, f"{name}|{description}")
    client.set(f"{PREFIX_SKILL}{sid}", induced, ex=TTL)
    for p in pending:
        client.delete(p)
    client.delete(TRAJ_LIST)
    flow.append({"step": "skill_induced", "kind": "store", "store": "node-based",
                 "detail": f"'{name}' consolidated from {len(trajectories)} trajectories "
                           f"({tokens} tokens overhead)"})
    return tokens


@app.entrypoint
def invoke(payload):
    """Payload: {"prompt": "..."}"""
    question = (payload.get("prompt") or "").strip()
    if not question:
        return {"error": "payload must include a 'prompt' string"}
    started = time.time()
    node, _ = common.get_clients()
    flow = []
    overhead = 0

    index = _skill_index(node)
    has_skills = index != "(no skills induced yet)"
    flow.append({
        "step": "skill_index_loaded",
        "kind": "hit" if has_skills else "miss",
        "detail": index if has_skills else "skill library empty — cold phase",
    })

    from strands import Agent
    from strands.hooks import AfterToolCallEvent

    trajectory = []
    skill_loaded = []

    def capture(event):
        name = event.tool_use["name"]
        if name == "load_skill":
            skill_loaded.append(event.tool_use["input"].get("name", "?"))
        else:
            trajectory.append({"tool": name, "args": dict(event.tool_use["input"])})

    agent = Agent(
        model=common.get_model(),
        system_prompt=SYSTEM_PROMPT.format(skill_index=index),
        tools=ALL_TOOLS + [_make_load_skill(node)],
    )
    agent.add_hook(capture, AfterToolCallEvent)
    result = agent(question)
    usage = dict(result.metrics.accumulated_usage)
    answer = common.clean_answer(str(result))

    if skill_loaded:
        flow.append({"step": "skill_followed", "kind": "hit",
                     "detail": f"agent loaded and followed: {', '.join(skill_loaded)}"})

    # queue this trajectory for consolidation; induce when enough accumulate
    if trajectory and not skill_loaded:
        tid = str(uuid.uuid4())
        node.set(f"{PREFIX_TRAJ}{tid}",
                 json.dumps({"question": question, "calls": trajectory}, default=str),
                 ex=TTL)
        node.rpush(TRAJ_LIST, f"{PREFIX_TRAJ}{tid}")
        flow.append({"step": "trajectory_queued", "kind": "store",
                     "detail": f"pending consolidation ({node.llen(TRAJ_LIST)}/{CONSOLIDATE_AFTER})"})
    overhead += _maybe_consolidate(node, flow)

    # baseline: first cold run cost for this tool-set (best-effort)
    baseline_key = "skills:baseline"
    if skill_loaded:
        prior = node.get(baseline_key)
        baseline = int(prior) if prior else 0
    else:
        baseline = 0
        node.set(baseline_key, str(usage.get("totalTokens", 0)), ex=TTL)

    return common.response_payload(
        answer, usage, overhead, baseline, flow, started,
        extra={"source": "skill" if skill_loaded else "agent",
               "cycles": result.metrics.cycle_count,
               "skills_used": skill_loaded},
    )


if __name__ == "__main__":
    app.run()
