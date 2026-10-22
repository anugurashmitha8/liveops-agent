"""HTTP API for the Live Ops agents, so any screen (including Live Ops) can use them.

GET  /issues       current ranked issues, with how long memory has seen each one
POST /investigate  run the agent team on one issue; returns the verified answer
GET  /memory       what H-MEM remembers: open issues, lessons, recent episodes
"""

from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import agents
from hmem import HMem, issue_key
from issues import _model_now

app = FastAPI(title="Live Ops Copilot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)
_data_lock = threading.Lock()  # one World Model build / memory update at a time
_job_lock = threading.Lock()   # one investigation at a time


class InvestigateRequest(BaseModel):
    key: str | None = None
    question: str | None = None


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/issues")
def list_issues():
    with _data_lock:
        wm = agents.collector()
        found = agents.monitor(wm)
        mem = HMem()
        now = _model_now(wm)
        mem.observe(wm, found, now)
        mem.save()
    out = []
    for issue in found:
        key = issue_key(issue)
        rec = mem.working["issues"].get(key, {})
        out.append({"key": key, "type": issue["type"], "severity": issue["severity"],
                    "summary": issue["summary"], "entities": issue["entities"],
                    "first_seen": rec.get("first_seen"),
                    "seen_count": rec.get("seen_count")})
    return {"as_of": now.isoformat(), "issues": out}


@app.post("/investigate")
def investigate(req: InvestigateRequest):
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "An investigation is already running")
    try:
        with _data_lock:  # waits for any list refresh to finish first
            result = agents.run(question=req.question, key=req.key)
    finally:
        _job_lock.release()
    if result is None:
        raise HTTPException(404, "That issue is no longer present")
    return {
        "verified": result["verified"],
        "message": result["message"],
        "issue": {"key": issue_key(result["issue"]),
                  "summary": result["issue"]["summary"]},
        "memory": result["memory"],
        "rounds": [
            {"round": r["round"],
             "cause": r["draft"].get("cause"),
             "explanation": r["draft"].get("explanation"),
             "actions": r["draft"].get("actions"),
             "verdict": r["review"]["verdict"],
             "problems": r["review"]["problems"]}
            for r in result["rounds"]
        ],
        "run_id": result["run_id"],
    }


@app.get("/memory")
def memory():
    mem = HMem()
    return {"open_issues": mem.working["issues"],
            "lessons": mem.semantic["lessons"],
            "recent_episodes": mem.episodes()[-20:]}
