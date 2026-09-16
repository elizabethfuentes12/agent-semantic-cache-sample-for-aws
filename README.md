![Semantic and reasoning caching for AI agents on Amazon ElastiCache for Valkey and Amazon DynamoDB](./images/cover.png)

# Prompt Caching Isn't Enough: Semantic and Reasoning Caches for AI Agents

AI agents answer the same questions over and over, and every repeat costs the full
LLM (Large Language Model) invocation. This sample adds two caching layers to a
Strands agent: a **semantic response cache** (repeated questions cost 0 tokens)
and an **in-loop reasoning cache** (new-but-similar questions skip exploration
cycles and tool executions). It ships them on **two backends** you pick by
workload: in-memory
[Amazon ElastiCache for Valkey](https://aws.amazon.com/elasticache/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
and serverless
[Amazon DynamoDB vector search](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).
AWS's published benchmark for semantic caching reports up to
[86% cost savings and 88% latency reduction](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/semantic-caching-overview.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).

This sample works with Amazon Bedrock, Amazon ElastiCache for Valkey, and Amazon
DynamoDB.

> 💡 Built on [Strands Agents](https://strandsagents.com/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).
> Semantic caching is a general agent pattern and carries over to other agent frameworks.

> ⚠️ **This is a demo, not production code.** Everything here is meant to teach
> the caching pattern. It is provided "as is", is not officially supported by
> Amazon, and is not safe for personal data as shipped (see [Is this cache safe
> for personal data?](#is-this-cache-safe-for-personal-data-read-before-production)).
> Validate, add PII detection, and partition per tenant before using any of this
> in production.

## Which track should I pick?

Two parallel tracks: the same agent, tools, and web UI, each with its own cache
infrastructure and its own way of reusing reasoning. Each track's README has the
full deep dive: architecture, deploy steps, measured results, costs, and
troubleshooting.

| Track | Cache backend | Best for | Deep dive |
|-------|---------------|----------|-----------|
| [cache-valkey/](./cache-valkey/) | In-memory ElastiCache for Valkey (node-based vector search + Serverless tool cache) | Sustained hot-path traffic, lowest lookup latency, already in a VPC | [cache-valkey/README.md](./cache-valkey/README.md) |
| [cache-dynamodb/](./cache-dynamodb/) | Serverless DynamoDB vector search (one table) | Spiky traffic, no idle compute cost, no VPC | [cache-dynamodb/README.md](./cache-dynamodb/README.md) |

> 🧑‍🏫 **New to this? Start with a local tutorial, no CDK (Cloud Development
> Kit).** Each track has a `local/` folder that caches a Strands agent with three
> hooks from a Jupyter notebook, plus a Streamlit chat:
> [cache-dynamodb/local](./cache-dynamodb/local/) (nothing to run locally, only
> AWS credentials) or [cache-valkey/local](./cache-valkey/local/) (a local Valkey
> container). They teach the same caching pattern the production stacks use, in
> plain readable Python.

## What does each cache layer save?

![The five cache layers for an AI agent: prompt caching, conversation management, response cache, reasoning cache, and tool-result cache](./images/five-layers.png)

Not every cache saves tokens. Being precise about WHAT each layer saves is the
point of the sample:

| Layer | Provided by | What it saves |
|---|---|---|
| 1. Native prompt caching | The model provider | **Input-token price** on repeated prompt prefixes; the model still generates every response |
| 2. Conversation management | Your agent framework | History tokens re-sent every turn |
| 3. **Semantic response cache** | This sample | **LLM tokens: the entire generation is skipped on a hit** |
| 4. **Reasoning cache** | This sample | **Deliberation tokens: fewer planning cycles on similar questions** |
| 5. **Tool-result cache** | This sample | **The external API invocation itself**: latency, third-party cost, and rate limits |

The two headline caches fire on different repeats: a **response cache** fires
when the *question* repeats, a **reasoning cache** fires when the *reasoning*
repeats. And each track reuses reasoning its own way: the Valkey track hints the
agent while it thinks (plan hints via hooks), the DynamoDB track saves the
finished plan and reuses it as a template.

![Response cache versus reasoning cache: a response cache returns a stored answer when the question repeats, a reasoning cache reuses the plan when the reasoning repeats](./images/two-cache-types.png)

## How is this different from the LLM providers' native caching?

Every major provider ships *prompt caching* (Gemini calls it *context caching*):
the processed prefix of your prompt is reused so you pay less for repeated input
tokens. It never returns a stored response; the model reasons and generates
every time (in Anthropic's words, ["prompt caching has no effect on output token
generation"](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
This sample's caches skip the generation, the deliberation, or the external API
call entirely, and the two layers **stack**: prompt caching cuts the price of
the input tokens you DO send; these caches remove the generations and API calls
you DON'T need to make at all. Check your provider's documentation for current
activation, lifetime, and pricing details.

These caches also live outside the model. In the notebooks and the local apps each
one is a Strands hook on the agent's lifecycle events; in the production stacks
the reasoning cache stays a hook and the response cache is checked around the
agent, before it runs. Either way the lookup, the threshold comparison, and the
store all run in your own code: no model is asked whether two questions match,
and the hit/miss decision is a comparison you can read
(`similarity = 1.0 - (score / 2.0)`, then `if similarity < threshold`). That also
makes the pattern independent of the model behind the agent. The agent model and
the embedding model are configuration values in every track, never hard-coded
(`agent_model_id` and `embedding_model_id` locally, `agent-model-id` and
`embedding-model-id` in Parameter Store in production). In each track's production
response cache the model id is also part of the lookup filter, so an answer
generated by one model is not served as if another had produced it. Changing the
embedding model does require re-indexing, because the index dimensions have to
match its output.

## What are the prerequisites?

**Start here: an AWS account and credentials.** If you do not have an account,
[create a free one](https://aws.amazon.com/free/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) and set up credentials with
`aws configure` ([how to get access keys](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)).

| Requirement | Needed for | Details |
|-------------|-----------|---------|
| AWS account + credentials | Everything | [Create an account](https://aws.amazon.com/free/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el), then `aws configure` |
| Bedrock model access | Everything | Enable Amazon Nova Lite + Titan Text Embeddings V2 in `us-east-1` from the [model access console](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el). It is a checkbox, not code |
| Python 3.11+ | The local notebooks | `pip install -r requirements.txt` in either `local/` folder |
| Python 3.13 + [uv](https://docs.astral.sh/uv/), Node.js 22+ with the CDK CLI | Production CDK stacks | See each track's README for the full deploy steps |

> 🧑‍🏫 **Want the shortest path?** The `local/` tutorials need only the first
> three rows. No CDK, no VPC. Start there, then deploy the track that matches
> your workload following its README.

## Which model provider? (you are not tied to Bedrock)

The agent runs on [Strands Agents](https://strandsagents.com/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
which is model-provider agnostic: swapping the provider is two lines and touches
nothing else (not the tools, not the hooks, not the cache).

```python
# Using an OpenAI-compatible interface via the Strands SDK (not direct OpenAI usage)
from strands.models.openai import OpenAIModel

model = OpenAIModel(client_args={"api_key": "<key>"}, model_id="gpt-4o")
agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=ALL_TOOLS)
```

Strands ships providers for
[Amazon Bedrock](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
[Anthropic](https://strandsagents.com/docs/user-guide/concepts/model-providers/anthropic/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
[OpenAI](https://strandsagents.com/docs/user-guide/concepts/model-providers/openai/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
[Ollama](https://strandsagents.com/docs/user-guide/concepts/model-providers/ollama/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
and more. One thing stays on Bedrock in this sample: the **embeddings** (Titan
Text Embeddings V2), because the embedding is what decides a cache hit. The
generation model and the embedding model are independent choices.

## What savings were measured?

Both tracks ship the same demos. The headline numbers below come from real
deployments of the in-memory track (Amazon Nova Lite, `us-east-1`); each track's
README has its full tables and how to reproduce them on your account:

- Repeated question: **0 tokens, 112 to 146 ms** (vs ~3 s and full price on the miss)
- Warm reasoning run: **58% of tokens saved** (7,000 to 2,965) and tool executions dropped to zero; across runs the savings ranged from 40% to 85%
- Cross-language hit (Spanish question, English cache): similarity **0.93**, answer rewritten for ~195 tokens

Reproduce them in [cache-valkey/README.md](./cache-valkey/README.md) and
[cache-dynamodb/README.md](./cache-dynamodb/README.md).

## Is this cache safe for personal data? (Read before production)

**No, this is a demo.** Nothing in this sample inspects what gets written to
the cache. In production, a shared semantic cache is a data-exfiltration and
poisoning surface: a cached answer containing one user's personal data can be
served to another user whose question is merely *similar*, and content read
from untrusted sources (web pages, documents) can plant instructions that get
cached and replayed. Before taking this pattern to production:

- **Validate before the agent writes to memory or cache.** Techniques and
  Strands examples: [Stop AI Agent Memory Poisoning at the Write
  Path](https://dev.to/aws/stop-ai-agent-memory-poisoning-at-the-write-path-1m9f),
  [Stop AI Agent Hallucinations: Validate Before the Agent Writes to
  Memory](https://dev.to/aws/stop-ai-agent-hallucinations-validate-before-the-agent-writes-to-memory-57om)
  and [How to Stop RAG Hallucinations Poisoning Your Vector
  Store](https://dev.to/aws/how-to-stop-rag-hallucinations-poisoning-your-vector-store-2l59).
- **Guard against prompt injection in tool outputs** before they reach the
  cache: [How to Stop Prompt Injection in AI Agents That Read Untrusted
  Content](https://dev.to/aws/how-to-stop-prompt-injection-in-ai-agents-that-read-untrusted-content-2j53).
- **Detect PII (Personally Identifiable Information) at the cache boundary**
  with a write-path hook: run entries through [Amazon Comprehend PII
  detection](https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
  or [Amazon Bedrock Guardrails sensitive-information
  filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
  and skip caching (or redact) anything flagged.
- **Partition the cache per tenant/user** the moment answers can depend on who
  is asking.

## What does this demo cost, and how do I clean up?

The cost profile is one of the main differences between the two tracks, and each
track's README breaks its costs down service by service:

| Track | Cost profile | Detail |
|---|---|---|
| [cache-valkey/](./cache-valkey/) | Always-on infrastructure billed by the hour, independent of traffic | [cost table](./cache-valkey/README.md#what-does-this-track-cost-to-run) |
| [cache-dynamodb/](./cache-dynamodb/) | Billed per request plus storage, no idle compute | [track README](./cache-dynamodb/README.md) |

Either way, when you finish testing:

```bash
cdk destroy
```

Every resource uses `RemovalPolicy.DESTROY`, so nothing is left behind.

## FAQ

**Is the cache per user or per session?**
Global: an answer cached for one user serves every user. That is correct for
factual FAQ content; partition per tenant if answers become user-specific.

**Does this replace Bedrock prompt caching?**
No, they stack. Prompt caching cuts input-token cost but still generates every
response; the semantic cache skips generation entirely on a hit.

**What happens if two questions are similar but need different answers?**
The similarity threshold (0.85 default) controls that risk, dates and numbers
must match exactly (critical-parameter guard), and every hit reports its
similarity so false hits are auditable.

**Can I use a different embedding model?**
Yes: change `EMBEDDING_MODEL_ID`, but the vector index dimensions must match the
model's output exactly, and changing models requires re-indexing.

**Which track should I start with?**
Neither, at first: start with a `local/` notebook tutorial (no CDK). Then deploy
the Valkey track for sustained hot-path traffic inside a VPC, or the DynamoDB
track for spiky traffic with no infrastructure to manage.

## References

- [Semantic caching with ElastiCache (AWS documentation)](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/semantic-caching-overview.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Amazon DynamoDB vector search (AWS documentation)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Vector search for Amazon ElastiCache announcement](https://aws.amazon.com/blogs/database/announcing-vector-search-for-amazon-elasticache/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Strands Agents hooks documentation](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Well-Architected Agentic AI Lens: agent caching layers](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentperf03-bp04.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Valkey project](https://valkey.io/)

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file for details.
