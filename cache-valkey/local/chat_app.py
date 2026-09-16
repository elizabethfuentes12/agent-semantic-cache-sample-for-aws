"""chat_app.py: a Streamlit chat showcasing the cache power on local Valkey.

Run it after starting Valkey + creating indexes in the notebook:

    streamlit run chat_app.py

Same visual UX as the DynamoDB local track (badges, token bars, cache-flow
timeline, live inventory, flush), but the vector store is a local Valkey
container instead of DynamoDB.
"""

import os
import time

import streamlit as st

from cache_lib import (
    CachedTravelAgent,
    ValkeyCacheConfig,
    cache_stats,
    ensure_indexes,
    flush_all,
    get_client,
    start_local_valkey,
    supports_ft_search,
)

st.set_page_config(page_title="Semantic Cache Chat · Valkey + Strands",
                   page_icon="⚡", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; }
      .badge { display:inline-block; padding:4px 12px; border-radius:999px;
        font-size:0.8rem; font-weight:700; letter-spacing:0.02em; margin-bottom:6px; }
      .badge-hit    { background:#0e7c3a; color:#fff; }
      .badge-rewrite{ background:#1f6feb; color:#fff; }
      .badge-agent  { background:#8250df; color:#fff; }
      .meta { color:#8b949e; font-size:0.78rem; margin-top:2px; }
      .flow-hit { color:#2ea043; } .flow-miss { color:#d29922; } .flow-store { color:#58a6ff; }
      .flow-line { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:0.8rem; }
      .big-metric { font-size:2.0rem; font-weight:800; line-height:1; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: configuration
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Configuration")
    region = st.text_input("AWS region", value=os.environ.get("AWS_REGION", "us-east-1"))
    host = st.text_input("Valkey host", value="localhost")
    port = st.number_input("Valkey port", value=6380, step=1,
                           help="6379 is often taken by a native Valkey/Redis.")
    threshold = st.slider("Similarity threshold", 0.50, 0.99, 0.85, 0.01)
    cache_mode = st.radio("Cache mode", ["both", "response-cache", "reasoning-cache"])
    auto_start = st.checkbox("Auto-start Valkey container", value=True,
                             help="Runs valkey/valkey-bundle via Docker if not already up.")
    st.caption("Flight tool: set DUFFEL_API_KEY in the environment before launching "
               "Streamlit. It is never entered in the UI, so it is not exposed on "
               "screen during a live demo.")

cfg = ValkeyCacheConfig(region=region, host=host, port=int(port),
                        similarity_threshold=threshold)


@st.cache_resource(show_spinner=False)
def _get_agent(region, host, port, threshold, cache_mode):
    # One agent instance is reused across reruns (its Valkey client and hooks are
    # expensive to rebuild). Hook state is per-invocation and reset at the start
    # of each ask(), safe because Streamlit serializes a session's script runs.
    # This is a single-user local demo; a multi-user server would build a fresh
    # agent per request (or move counters into invocation_state).
    c = ValkeyCacheConfig(region=region, host=host, port=int(port),
                          similarity_threshold=threshold)
    return CachedTravelAgent(c, cache_mode=cache_mode)


# ---------------------------------------------------------------------------
# Header + Valkey readiness
# ---------------------------------------------------------------------------

st.title("⚡ Semantic + Reasoning Cache Chat · Valkey")
st.caption(
    "A Strands travel agent with a **semantic response cache** (level 1) in front "
    "of an **in-loop reasoning cache** (level 2), both on a **local Valkey** with "
    "vector search. Ask a question, then ask it again (or paraphrase, or switch "
    "language) and watch the tokens drop to zero."
)


def _valkey_ready() -> tuple[bool, str]:
    try:
        c = get_client(cfg)
        if not c.ping():
            return False, "no ping"
        if not supports_ft_search(c):
            return False, "no FT.* module (need valkey/valkey-bundle)"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


if "valkey_ready" not in st.session_state:
    ready, why = _valkey_ready()
    if not ready and auto_start:
        with st.spinner("Starting local Valkey container…"):
            try:
                start_local_valkey(cfg)
                ensure_indexes(get_client(cfg))
                ready, why = _valkey_ready()
            except Exception as exc:
                why = str(exc)
    st.session_state.valkey_ready = ready
    st.session_state.valkey_why = why

if not st.session_state.get("valkey_ready"):
    st.warning(
        f"Valkey not ready at {host}:{int(port)}: {st.session_state.get('valkey_why','')}. "
        "Start it in the notebook (`start_local_valkey`) or enable auto-start in the sidebar. "
        "It must be the `valkey/valkey-bundle` image (has the FT.* search module)."
    )

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
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
        # Identical and same-language hits never reach the rewrite model, so
        # they are literally 0 tokens. A cross-language hit the model reports as
        # already matching keeps source="cache" but did spend its tokens.
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


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and msg.get("meta"):
            st.markdown(_badge(msg["meta"]), unsafe_allow_html=True)
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("meta"):
            _render_meta(msg["meta"])


def _submit(text):
    st.session_state._pending = text


if not st.session_state.messages:
    st.markdown("**Try this demo sequence.** 1 runs the agent. 2 is a reworded "
                "level-1 hit, served verbatim at 0 tokens. "
                "3 asks in Spanish: a cross-language hit that rewrites the answer "
                "to your language. 4 runs a fresh destination, and 5 is similar to "
                "it so the level-2 reasoning cache kicks in (plan hint and "
                "tool-cache hits).")
    c = st.columns(2)
    c[0].button("1. Best time to visit Japan + visa? (cold)", on_click=_submit,
                args=("What is the best time of year to visit Japan and do I need a visa?",),
                use_container_width=True)
    c[1].button("2. Reworded (level-1 hit)", on_click=_submit,
                args=("When should I travel to Japan, and are visas required for tourists?",),
                use_container_width=True)
    c[0].button("3. In Spanish (cross-language hit)", on_click=_submit,
                args=("¿Cuál es la mejor época para visitar Japón y necesito visa?",),
                use_container_width=True)
    c[1].button("4. A new destination: Oslo (cold)", on_click=_submit,
                args=("What is the weather like in Oslo and do I need a visa?",),
                use_container_width=True)
    c[0].button("5. Similar to Oslo (level-2 reasoning cache)", on_click=_submit,
                args=("Tell me about the climate in Oslo and visa requirements.",),
                use_container_width=True)
    c[1].button("6. Flights BOS to Tokyo (cold, then repeat)", on_click=_submit,
                args=("Find flights from Boston to Tokyo on 2026-10-15.",),
                use_container_width=True)


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
            agent = _get_agent(region, host, int(port), threshold, cache_mode)
            result = agent.ask(prompt)
        except Exception as exc:
            placeholder.empty()
            st.error(f"Request failed: {exc}")
            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ {exc}", "meta": None})
            st.stop()

        placeholder.empty()
        st.markdown(_badge(result), unsafe_allow_html=True)
        st.markdown(result["answer"])
        _render_meta(result)

    st.session_state.total_saved += result.get("tokens_saved", 0)
    st.session_state.total_used += result.get("usage", {}).get("totalTokens", 0)
    st.session_state.messages.append({"role": "assistant", "content": result["answer"], "meta": result})
    st.rerun()


# ---------------------------------------------------------------------------
# Sidebar: live stats + inventory + flush
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
        pass
    if st.session_state.get("valkey_ready"):
        try:
            stats = cache_stats(cfg)
            labels = {"response": "Level 1 · answers",
                      "trajectory": "Level 2 · tool plans",
                      "tool_result": "Level 2 · tool results",
                      "total": "Total keys"}
            for k in ("response", "trajectory", "tool_result", "total"):
                st.markdown(f"**{stats.get(k,0)}**: {labels[k]}")
        except Exception as exc:
            st.caption(f"inventory unavailable: {exc}")

    st.divider()
    st.header("🧹 Reset")
    st.caption("Flush the store for a clean cold-run demo.")
    if st.button("Flush all cache entries", type="secondary", use_container_width=True):
        try:
            n = flush_all(cfg)
            st.session_state.total_saved = 0
            st.session_state.total_used = 0
            st.success(f"Flushed {n} key(s); indexes recreated.")
            time.sleep(0.6)  # nosemgrep: arbitrary-sleep - intentional wait for UI poll
            st.rerun()
        except Exception as exc:
            st.error(f"Flush failed: {exc}")
