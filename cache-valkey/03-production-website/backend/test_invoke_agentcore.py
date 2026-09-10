"""Invoke AgentCore with a research query and show progress."""
import json, time, boto3
from botocore.config import Config

cfg = Config(read_timeout=900, connect_timeout=30, retries={"max_attempts": 0})
client = boto3.client("bedrock-agentcore", region_name="us-east-1", config=cfg)

start = time.time()
response = client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:us-east-1:657343904323:runtime/ResearchExpert-Zfkhho2K7U",
    qualifier="DEFAULT",
    payload=json.dumps({"prompt": "buscame informacion de las diferencias de modelos tesla apreciables desde el exterior"}).encode("utf-8"),
    runtimeSessionId="test-tesla-fresh-20260414070000000",
)

print(f"Content-Type: {response.get('contentType', '')}", flush=True)

count = 0
with open("agentcore_raw_events.txt", "w", encoding="utf-8") as f:
    if "text/event-stream" in response.get("contentType", ""):
        for line in response["response"].iter_lines(chunk_size=1):
            if line:
                decoded = line.decode("utf-8")
                f.write(decoded + "\n")
                f.flush()
                count += 1
                elapsed = int(time.time() - start)
                if decoded.startswith("data: "):
                    payload = decoded[6:]
                    try:
                        d = json.loads(payload)
                        if isinstance(d, dict):
                            t = d.get("type")
                            if t:
                                content = d.get("content", d.get("answer", d.get("tool", "")))
                                preview = str(content)[:100] if content else ""
                                print(f"  [{elapsed}s] #{count} type={t} {preview}", flush=True)
                            elif "message" in d and isinstance(d["message"], dict):
                                role = d["message"].get("role", "")
                                content = d["message"].get("content", [])
                                tools = sum(1 for b in content if isinstance(b, dict) and ("toolUse" in b or "toolResult" in b))
                                texts = sum(1 for b in content if isinstance(b, dict) and "text" in b)
                                print(f"  [{elapsed}s] #{count} message role={role} texts={texts} tools={tools}", flush=True)
                    except:  # nosec B110 - best-effort cleanup in a test
                        pass

elapsed = int(time.time() - start)
print(f"\nDone in {elapsed}s. Total lines: {count}", flush=True)
