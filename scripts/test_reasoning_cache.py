"""Demo 02 test: measure in-loop savings (reasoning + tool execution).

Sequence:
  1. COLD:   multi-tool question -> agent explores, executes tools.
             Trajectory + tool results get cached.
  2. WARM-A: paraphrased question (same intent) -> plan hint injected
             (reasoning savings) + tool results served from cache
             (execution savings).
  3. WARM-B: different phrasing, partly overlapping tools -> shows the
             tool cache working independently of the plan hint.

Compares cycles, tokens, tool executions per run.

Usage:
    python3 scripts/test_reasoning_cache.py --function <ReasoningFunctionName> [--profile p] [--region r]
"""

import argparse
import json

import boto3

RUNS = [
    ("COLD  (expect full exploration)",
     "I'm a US citizen planning a trip to Tokyo. Do I need a visa, and "
     "when is the best time of year to go?"),
    ("WARM-A (paraphrase: expect plan hint + tool cache hits)",
     "I'm American and thinking about visiting Tokyo — what are the visa "
     "requirements and which season is best?"),
    ("WARM-B (overlapping tools only)",
     "When should I visit Tokyo?"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", required=True)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default=None)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("lambda", config=boto3.session.Config(read_timeout=180))

    # Clean slate so COLD is genuinely cold.
    flush = client.invoke(
        FunctionName=args.function,
        Payload=json.dumps({"action": "flush"}).encode(),
    )
    print("cache flushed:", json.loads(flush["Payload"].read()))

    rows = []
    for label, question in RUNS:
        response = client.invoke(
            FunctionName=args.function,
            Payload=json.dumps({"question": question}).encode(),
        )
        payload = json.loads(response["Payload"].read())
        if "errorMessage" in payload:
            raise RuntimeError(f"Lambda error: {payload['errorMessage']}")
        rows.append((label, payload))
        print(f"\n{label}")
        print(f"  cycles={payload['cycles']}  tokens={payload['usage']['totalTokens']}"
              f"  (in={payload['usage']['inputTokens']} out={payload['usage']['outputTokens']})")
        print(f"  plan_hint={payload['plan_hint_used']}  tool_cache_hits={payload['tool_cache_hits']}"
              f"  tool_executions={payload['tool_executions']}  latency={payload['latency_ms']}ms")

    cold = rows[0][1]
    warm = rows[1][1]
    print("\n--- Cold vs Warm-A (same intent, paraphrased) ---")
    for metric, c, w in [
        ("event-loop cycles", cold["cycles"], warm["cycles"]),
        ("total tokens", cold["usage"]["totalTokens"], warm["usage"]["totalTokens"]),
        ("output tokens", cold["usage"]["outputTokens"], warm["usage"]["outputTokens"]),
        ("tool executions", cold["tool_executions"], warm["tool_executions"]),
    ]:
        delta = c - w
        pct = (delta / c * 100) if c else 0
        print(f"  {metric:18} {c:>6} -> {w:>6}   ({pct:+.0f}% saved)" if delta >= 0
              else f"  {metric:18} {c:>6} -> {w:>6}   (WORSE by {-delta})")


if __name__ == "__main__":
    main()
