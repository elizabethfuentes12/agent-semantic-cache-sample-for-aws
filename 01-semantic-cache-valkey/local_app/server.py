"""Local dashboard for the semantic-cache sample.

Small Flask app that invokes the two deployed Lambdas and renders a
dashboard: chat panel, live cache inventory (both stores), and per-session
token/latency history.

Usage:
    uv pip install flask boto3
    AWS_PROFILE=<profile> python3 local_app/server.py \
        --stack SemanticCacheStack --region us-east-1
"""

import argparse
import json
import time
import uuid

import boto3
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

lambda_client = None
functions = {"demo01": None, "demo02": None}
# Per-session invocation history, in memory (local tool only).
sessions: dict[str, list] = {}


def resolve_functions(stack: str, region: str, profile: str | None):
    global lambda_client
    session = boto3.Session(profile_name=profile, region_name=region)
    lambda_client = session.client(
        "lambda", config=boto3.session.Config(read_timeout=180)
    )
    cfn = session.client("cloudformation")
    outputs = cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
    for out in outputs:
        if out["OutputKey"] == "FunctionName":
            functions["demo01"] = out["OutputValue"]
        elif out["OutputKey"] == "ReasoningFunctionName":
            functions["demo02"] = out["OutputValue"]
    missing = [k for k, v in functions.items() if not v]
    if missing:
        raise SystemExit(f"Stack outputs missing for: {missing}")


def invoke(function_name: str, payload: dict) -> dict:
    response = lambda_client.invoke(
        FunctionName=function_name, Payload=json.dumps(payload).encode()
    )
    return json.loads(response["Payload"].read())


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/ask")
def ask():
    body = request.get_json(force=True)
    demo = body.get("demo", "demo01")
    session_id = body.get("session_id") or str(uuid.uuid4())
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question required"}), 400
    if demo not in functions:
        return jsonify({"error": f"unknown demo '{demo}'"}), 400

    result = invoke(functions[demo], {"question": question})
    if "errorMessage" in result:
        return jsonify({"error": result["errorMessage"]}), 502

    usage = result.get("usage", {})
    entry = {
        "ts": time.time(),
        "demo": demo,
        "question": question,
        "answer": result.get("answer", ""),
        "source": result.get("source", "agent"),
        "similarity": result.get("similarity"),
        "cycles": result.get("cycles"),
        "plan_hint_used": result.get("plan_hint_used"),
        "tool_cache_hits": result.get("tool_cache_hits", 0),
        "tool_executions": result.get("tool_executions", 0),
        "stale_served": result.get("stale_served", 0),
        "tokens_consumed": usage.get("totalTokens", 0),
        "tokens_saved": result.get("tokens_saved", 0),
        "latency_ms": result.get("latency_ms"),
    }
    sessions.setdefault(session_id, []).append(entry)
    return jsonify({"session_id": session_id, "result": entry})


@app.get("/api/sessions")
def get_sessions():
    summary = []
    for sid, entries in sessions.items():
        summary.append({
            "session_id": sid,
            "questions": len(entries),
            "tokens_consumed": sum(e["tokens_consumed"] for e in entries),
            "tokens_saved": sum(e["tokens_saved"] for e in entries),
            "entries": entries,
        })
    return jsonify(summary)


@app.get("/api/cache")
def cache_contents():
    result = invoke(functions["demo02"], {"action": "cache_stats"})
    return jsonify(result)


@app.post("/api/flush")
def flush():
    result = invoke(functions["demo02"], {"action": "flush"})
    sessions.clear()
    return jsonify(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack", default="SemanticCacheStack")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    resolve_functions(args.stack, args.region, args.profile)
    print(f"demo01 -> {functions['demo01']}")
    print(f"demo02 -> {functions['demo02']}")
    app.run(host="127.0.0.1", port=args.port, debug=False)
