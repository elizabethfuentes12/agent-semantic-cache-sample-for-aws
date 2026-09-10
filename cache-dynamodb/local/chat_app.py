"""chat_app.py: a Streamlit chat that showcases the cache power.

Run it after deploying the table in the notebook:

    streamlit run chat_app.py

What you see per answer:
- a badge: CACHE HIT (0 tokens), CACHE HIT rewritten to your language, or AGENT RAN, with the similarity.
- a tokens-saved vs tokens-used bar.
- the cache flow timeline (what happened inside).
- a live sidebar inventory of the table, cumulative token savings, and a Flush button.

Everything talks to the same DynamoDB table the notebook created: no SSM,
no CDK, no server. Just the CachedTravelAgent from cache_lib.
"""

import os
import time

import streamlit as st

from cache_lib import CacheConfig, CachedTravelAgent, cache_stats, flush_all
from cache_lib.table import table_exists

# ---------------------------------------------------------------------------
# Page + theme
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Semantic Cache Chat · DynamoDB + Strands",
    page_icon="⚡",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; }
      .badge {
        display:inline-block; padding:4px 12px; border-radius:999px;
        font-size:0.8rem; font-weight:700; letter-spacing:0.02em; margin-bottom:6px;
      }
      .badge-hit    { background:#0e7c3a; color:#fff; }
      .badge-rewrite{ background:#1f6feb; color:#fff; }
      .badge-agent  { background:#8250df; color:#fff; }
      .meta { color:#8b949e; font-size:0.78rem; margin-top:2px; }
      .flow-hit   { color:#2ea043; }
      .flow-miss  { color:#d29922; }
      .flow-store { color:#58a6ff; }
      .flow-line  { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:0.8rem; }
      .big-metric { font-size:2.0rem; font-weight:800; line-height:1; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: configuration + inventory + controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Configuration")
    region = st.text_input("AWS region", value=os.environ.get("AWS_REGION", "us-east-1"))
    table_name = st.text_input("DynamoDB table", value="agent-cache-dynamodb-local")
    threshold = st.slider("Similarity threshold", 0.50, 0.99, 0.85, 0.01,
                          help="A hit must meet this cosine similarity. Higher = stricter.")
    cache_mode = st.radio(
        "Cache mode",
        ["both", "response-cache", "reasoning-cache"],
        help="both = level 1 in front of level 2.",
    )
    st.caption("Flight tool: set DUFFEL_API_KEY in the environment before launching "
               "Streamlit. It is never entered in the UI, so it is not exposed on "
               "screen during a live demo.")

cfg = CacheConfig(
    region=region,
    table_name=table_name,
    similarity_threshold=threshold,
)


@st.cache_resource(show_spinner=False)
def _get_agent(region: str, table_name: str, threshold: float, cache_mode: str):
    # One agent instance is reused across reruns (its boto3 client and hooks are
    # expensive to rebuild). The hook state is per-invocation and reset at the
    # start of each ask(), which is safe because Streamlit serializes a session's
    # script runs. This is a single-user local demo; a multi-user server would
    # build a fresh agent per request (or move counters into invocation_state).
    c = CacheConfig(region=region, table_name=table_name, similarity_threshold=threshold)
    return CachedTravelAgent(c, cache_mode=cache_mode)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("⚡ Semantic + Reasoning Cache Chat")
st.caption(
    "A Strands travel agent with a **semantic response cache** (level 1) in front "
    "of an **in-loop reasoning cache** (level 2), both on one DynamoDB table. "
    "Ask a question, then ask it again (or paraphrase it, or switch language) and "
    "watch the tokens drop to zero."
)

# Table existence check: friendly nudge to run the notebook first.
if "table_ok" not in st.session_state:
    try:
        st.session_state.table_ok = table_exists(cfg)
    except Exception as exc:  # credentials / region issues
        st.session_state.table_ok = False
        st.session_state.table_err = str(exc)

if not st.session_state.get("table_ok"):
    st.warning(
        f"Table **{table_name}** not found in **{region}**. "
        "Open `01_deploy_and_test.ipynb` and run the deploy cell first "
        "(or check your AWS credentials/region)."
    )
    if st.session_state.get("table_err"):
        st.caption(f"Detail: {st.session_state.table_err}")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []          # list of dicts: role, content, meta
if "total_saved" not in st.session_state:
    st.session_state.total_saved = 0
if "total_used" not in st.session_state:
    st.session_state.total_used = 0


def _badge(meta: dict) -> str:
    source = meta.get("source")
    sim = meta.get("similarity")
    sim_txt = f" · sim {sim}" if sim is not None else ""
    if source == "cache":
        rt = meta.get("rewrite_tokens", 0)
        # A reworded same-language hit (below the verbatim threshold) still runs
        # one cheap rewrite-check that confirms the language matches, so it is not
        # literally 0 tokens. A truly verbatim hit is.
        cost = "0 tokens" if not rt else f"~0 tokens (+{rt} rewrite-check)"
        return f'<span class="badge badge-hit">⚡ CACHE HIT · {cost}{sim_txt}</span>'
    if source == "cache-rewrite":
        rt = meta.get("rewrite_tokens", 0)
        return (f'<span class="badge badge-rewrite">🌐 CACHE HIT · rewritten to your '
                f'language · {rt} tokens{sim_txt}</span>')
    return '<span class="badge badge-agent">🧠 AGENT RAN</span>'


def _render_meta(meta: dict):
    cols = st.columns(4)
    cols[0].markdown(f'<div class="meta">latency</div><div class="big-metric">{meta.get("latency_ms","–")}<span class="meta"> ms</span></div>', unsafe_allow_html=True)
    cols[1].markdown(f'<div class="meta">tokens used</div><div class="big-metric">{meta.get("usage",{}).get("totalTokens",0)}</div>', unsafe_allow_html=True)
    cols[2].markdown(f'<div class="meta">tokens saved</div><div class="big-metric" style="color:#2ea043">{meta.get("tokens_saved",0)}</div>', unsafe_allow_html=True)
    cols[3].markdown(f'<div class="meta">cycles</div><div class="big-metric">{meta.get("cycles",0)}</div>', unsafe_allow_html=True)

    if meta.get("plan_hint_used") or meta.get("tool_cache_hits"):
        extras = []
        if meta.get("plan_hint_used"):
            extras.append("🧭 plan hint used")
        if meta.get("tool_cache_hits"):
            extras.append(f"🔧 {meta['tool_cache_hits']} tool-cache hit(s)")
        if meta.get("tool_executions"):
            extras.append(f"🌐 {meta['tool_executions']} real API call(s)")
        st.caption("  ·  ".join(extras))

    flow = meta.get("flow") or []
    if flow:
        with st.expander("🔎 cache flow (what happened inside)"):
            for step in flow:
                kind = step.get("kind", "")
                cls = {"hit": "flow-hit", "miss": "flow-miss", "store": "flow-store"}.get(kind, "")
                icon = {"hit": "✅", "miss": "➖", "store": "💾"}.get(kind, "•")
                tool = f" [{step['tool']}]" if step.get("tool") else ""
                st.markdown(
                    f'<div class="flow-line {cls}">{icon} <b>{step["step"]}</b>{tool}: {step.get("detail","")}</div>',
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Render chat history
# ---------------------------------------------------------------------------

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and msg.get("meta"):
            st.markdown(_badge(msg["meta"]), unsafe_allow_html=True)
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("meta"):
            _render_meta(msg["meta"])


# ---------------------------------------------------------------------------
# Suggested prompts (only before the first message)
# ---------------------------------------------------------------------------

def _submit(text):
    st.session_state._pending = text


if not st.session_state.messages:
    st.markdown("**Try this demo sequence.** 1 runs the agent. 2 is a reworded "
                "level-1 hit (the answer is served, plus one cheap rewrite-check). "
                "3 asks in Spanish: a cross-language hit that rewrites the answer "
                "to your language. 4 runs a fresh destination, and 5 is similar to "
                "it so the level-2 reasoning cache kicks in (plan hint and "
                "tool-cache hits).")
    c = st.columns(2)
    c[0].button("1. Best time to visit Japan + visa? (cold)",
                on_click=_submit, args=("What is the best time of year to visit Japan and do I need a visa?",),
                use_container_width=True)
    c[1].button("2. Reworded (level-1 hit)",
                on_click=_submit, args=("When should I travel to Japan, and are visas required for tourists?",),
                use_container_width=True)
    c[0].button("3. In Spanish (cross-language hit)",
                on_click=_submit, args=("¿Cuál es la mejor época para visitar Japón y necesito visa?",),
                use_container_width=True)
    c[1].button("4. A new destination: Oslo (cold)",
                on_click=_submit, args=("What is the weather like in Oslo and do I need a visa?",),
                use_container_width=True)
    c[0].button("5. Similar to Oslo (level-2 reasoning cache)",
                on_click=_submit, args=("Tell me about the climate in Oslo and visa requirements.",),
                use_container_width=True)
    c[1].button("6. Flights BOS to Tokyo (cold, then repeat)",
                on_click=_submit, args=("Find flights from Boston to Tokyo on 2026-10-15.",),
                use_container_width=True)


# ---------------------------------------------------------------------------
# Handle input (typed or suggested)
# ---------------------------------------------------------------------------

prompt = st.chat_input("Ask about a destination: season, visa, flights")
if not prompt and st.session_state.get("_pending"):
    prompt = st.session_state.pop("_pending")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("_thinking…_")
        try:
            agent = _get_agent(region, table_name, threshold, cache_mode)
            result = agent.ask(prompt)
        except Exception as exc:
            placeholder.empty()
            st.error(f"Request failed: {exc}")
            st.session_state.messages.append(
                {"role": "assistant", "content": f"⚠️ {exc}", "meta": None}
            )
            st.stop()

        placeholder.empty()
        st.markdown(_badge(result), unsafe_allow_html=True)
        st.markdown(result["answer"])
        _render_meta(result)

    st.session_state.total_saved += result.get("tokens_saved", 0)
    st.session_state.total_used += result.get("usage", {}).get("totalTokens", 0)
    st.session_state.messages.append(
        {"role": "assistant", "content": result["answer"], "meta": result}
    )
    st.rerun()


# ---------------------------------------------------------------------------
# Sidebar: live stats + inventory + flush (rendered after a turn so it's fresh)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.divider()
    st.header("📊 This session")
    saved = st.session_state.total_saved
    used = st.session_state.total_used
    total = saved + used
    pct = int(100 * saved / total) if total else 0
    st.metric("Tokens saved", f"{saved:,}", delta=f"{pct}% of would-be spend" if total else None)
    st.progress(pct / 100 if total else 0.0)
    st.caption(f"Tokens actually spent: {used:,}")

    st.divider()
    st.header("🗄️ Cache inventory")
    if st.button("↻ Refresh inventory", use_container_width=True):
        pass  # button press triggers a rerun which re-reads below
    if st.session_state.get("table_ok"):
        try:
            stats = cache_stats(cfg)
            labels = {
                "response": "Level 1 · answers",
                "trajectory": "Level 2 · tool plans",
                "tool_result": "Level 2 · tool results",
                "total": "Total items",
            }
            for k in ("response", "trajectory", "tool_result", "total"):
                st.markdown(f"**{stats.get(k,0)}**: {labels[k]}")
        except Exception as exc:
            st.caption(f"inventory unavailable: {exc}")

    st.divider()
    st.header("🧹 Reset")
    st.caption("Flush the table for a clean cold-run demo.")
    if st.button("Flush all cache entries", type="secondary", use_container_width=True):
        try:
            n = flush_all(cfg)
            st.session_state.total_saved = 0
            st.session_state.total_used = 0
            st.success(f"Deleted {n} item(s).")
            time.sleep(0.6)
            st.rerun()
        except Exception as exc:
            st.error(f"Flush failed: {exc}")
