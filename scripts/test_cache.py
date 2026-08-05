"""End-to-end test: paraphrased question pairs against the deployed Lambda.

For each pair, the first phrasing should MISS (agent runs, tokens spent) and
the paraphrase should HIT (cached answer, zero agent tokens). Prints per-pair
results and a savings summary.

Usage:
    python3 scripts/test_cache.py --function <FunctionName> [--profile p] [--region r]
"""

import argparse
import json

import boto3

QUESTION_PAIRS = [
    (
        "What documents do I need to travel to Japan?",
        "Which papers are required for a trip to Japan?",
    ),
    (
        "When is the best season to visit Patagonia?",
        "What time of year should I go to Patagonia?",
    ),
    (
        "Do I need a visa to visit Brazil as a US citizen?",
        "Is a visa required for US citizens traveling to Brazil?",
    ),
]


def invoke(client, function_name: str, question: str) -> dict:
    response = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps({"question": question}).encode(),
    )
    payload = json.loads(response["Payload"].read())
    if "error" in payload or "errorMessage" in payload:
        raise RuntimeError(f"Lambda error: {payload}")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--function", required=True)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default=None)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("lambda")

    total_spent = 0
    total_saved = 0
    hits = 0

    for original, paraphrase in QUESTION_PAIRS:
        print(f"\nQ1 (expect miss): {original}")
        first = invoke(client, args.function, original)
        usage = first.get("usage", {})
        spent = usage.get("totalTokens", 0)
        total_spent += spent
        print(f"   source={first['source']} tokens={spent} latency={first['latency_ms']}ms")

        print(f"Q2 (expect hit):  {paraphrase}")
        second = invoke(client, args.function, paraphrase)
        if second["source"] == "cache":
            hits += 1
            total_saved += second["tokens_saved"]
            print(
                f"   source=cache similarity={second['similarity']} "
                f"tokens_saved={second['tokens_saved']} latency={second['latency_ms']}ms"
            )
        else:
            spent2 = second.get("usage", {}).get("totalTokens", 0)
            total_spent += spent2
            print(f"   source=agent (MISS) tokens={spent2} latency={second['latency_ms']}ms")

    print("\n--- Summary ---")
    print(f"Hit ratio on paraphrases: {hits}/{len(QUESTION_PAIRS)}")
    print(f"Tokens spent (misses):    {total_spent}")
    print(f"Tokens saved (hits):      {total_saved}")


if __name__ == "__main__":
    main()
