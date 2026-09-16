"""B6 — Calibration harness for the semantic-cache similarity threshold.

Motivation: "choosing an embedding model for semantic caching is a
calibration problem, not a ranking one" (arXiv:2606.19719). This script
measures, for OUR embedding model (Titan V2) on OUR domain, how cosine
similarity maps to answer-equivalence, so the threshold is chosen from
data instead of by hand.

It embeds labeled question pairs (duplicates vs distinct), reports the
similarity distribution per class, and prints precision/recall for a sweep
of thresholds. Numbers are reported on the same scale the caches threshold,
`(1 + cosine) / 2`, so a threshold read off this output can be pasted into the
config as-is; raw cosine is printed beside it for reference. Run it locally
with Bedrock access:

    python3 scripts/calibrate_threshold.py [--model amazon.titan-embed-text-v2:0]
"""

import argparse
import json

import boto3

# Labeled pairs for the travel-FAQ domain. duplicate=True means a cache hit
# would be CORRECT (same answer applies). Extend with production near-miss
# logs (`cache_miss_best_similarity` entries) for real calibration.
PAIRS = [
    # duplicates: paraphrases, cross-language, reorderings
    ("Do I need a visa to visit Brazil as a US citizen?",
     "Is a visa required for US citizens traveling to Brazil?", True),
    ("Do I need a visa to visit Brazil as a US citizen?",
     "Necesito visa para ir a Brasil siendo estadounidense?", True),
    ("When is the best season to visit Patagonia?",
     "What time of year should I go to Patagonia?", True),
    ("What documents do I need to travel to Japan?",
     "Which papers are required for a trip to Japan?", True),
    ("Cheapest flight from JFK to Tokyo on 2026-09-15",
     "What is the lowest fare JFK to Tokyo for September 15, 2026?", True),
    ("I'm a US citizen planning a trip to Tokyo. Do I need a visa, and when is the best time to go?",
     "As an American visiting Tokyo, what visa do I need and which season is nicest?", True),
    # distinct: same surface, different answer required
    ("Do I need a visa to visit Brazil as a US citizen?",
     "Do I need a visa to visit Brazil as a Canadian citizen?", False),
    ("Do I need a visa to visit Brazil as a US citizen?",
     "Do I need a visa to visit Argentina as a US citizen?", False),
    ("When is the best season to visit Patagonia?",
     "When is the best season to visit Iceland?", False),
    ("Cheapest flight from JFK to Tokyo on 2026-09-15",
     "Cheapest flight from JFK to Tokyo on 2026-12-15", False),
    ("What documents do I need to travel to Japan?",
     "What documents do I need to work in Japan?", False),
    ("What's the weather like in Tokyo?",
     "What's the population of Tokyo?", False),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="amazon.titan-embed-text-v2:0")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    bedrock = session.client("bedrock-runtime")

    def embed(text):
        response = bedrock.invoke_model(
            modelId=args.model,
            body=json.dumps({"inputText": text, "dimensions": 1024}),
        )
        return json.loads(response["body"].read())["embedding"]

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
        return dot / norm if norm else 0.0

    def to_cache_scale(cos: float) -> float:
        """Raw cosine -> the number the caches actually threshold.

        Both stores return a COSINE *distance* (0 identical, 2 opposite), which
        the caches convert with `similarity = 1 - score/2`. Since that distance
        is `1 - cosine`, the converted value is `(1 + cosine) / 2`. Calibrating
        on raw cosine would pick a threshold on the wrong scale: the shipped
        `similarity_threshold = 0.85` corresponds to a raw cosine of 0.70.
        """
        return (1.0 + cos) / 2.0

    print(f"  {'':6} {'cache':>7} {'raw':>7}")
    results = []
    for q1, q2, is_dup in PAIRS:
        cos = cosine(embed(q1), embed(q2))
        sim = to_cache_scale(cos)
        results.append((sim, is_dup, q1, q2))
        marker = "DUP " if is_dup else "DIFF"
        print(f"  [{marker}] {sim:>7.4f} {cos:>7.4f}  {q1[:40]!r} vs {q2[:40]!r}")

    print("\nThreshold sweep on the CACHE scale (hit = similarity >= t),")
    print("the same scale as `similarity_threshold` in the config:")
    print(f"{'t':>6} {'precision':>10} {'recall':>8} {'false hits':>11}")
    for t100 in range(85, 100):
        t = t100 / 100
        tp = sum(1 for s, d, *_ in results if s >= t and d)
        fp = sum(1 for s, d, *_ in results if s >= t and not d)
        fn = sum(1 for s, d, *_ in results if s < t and d)
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        flag = "  <-- false hits!" if fp else ""
        shipped = "  (shipped default)" if t100 == 85 else ""
        print(f"{t:>6.2f} {precision:>10.2f} {recall:>8.2f} {fp:>11}{flag}{shipped}")

    dup_sims = sorted(s for s, d, *_ in results if d)
    diff_sims = sorted(s for s, d, *_ in results if not d)
    print(f"\nduplicates:  min {dup_sims[0]:.4f}  max {dup_sims[-1]:.4f}")
    print(f"distinct:    min {diff_sims[0]:.4f}  max {diff_sims[-1]:.4f}")
    if diff_sims[-1] >= dup_sims[0]:
        print("⚠️  Classes OVERLAP: no single threshold is clean. The overlap "
              "here is the date pair, which is what the critical-parameter "
              "guard exists for: it compares the dates and numbers separately, "
              "so similarity never has to separate them on its own.")
    else:
        safe_low, safe_high = diff_sims[-1], dup_sims[0]
        print(f"✅ Clean margin: any threshold in ({safe_low:.4f}, {safe_high:.4f}) "
              "separates the classes on this dataset.")


if __name__ == "__main__":
    main()
