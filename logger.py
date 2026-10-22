import json, os, time, uuid

RUN_ID = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
os.makedirs("logs", exist_ok=True)

def log(agent, action, data=None):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "run_id": RUN_ID,
             "agent": agent, "action": action, "data": data}
    with open(f"logs/{RUN_ID}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry
    