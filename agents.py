"""Multi-agent loop over the World Model.

Collector -> Monitor -> Investigator <-> Critic -> Explainer

The Investigator explains a problem using only World Model evidence.
The Critic verifies every cited claim in code, then reviews the reasoning
with the LLM, and sends weak drafts back (up to MAX_ROUNDS).
"""

from __future__ import annotations

import argparse
import json
import os
import re

from issues import find_issues
from logger import RUN_ID, log
from sources import live_snapshot, reference_data
from world_model import WorldModel

MAX_ROUNDS = 3
SEV_RANK = {"high": 0, "medium": 1, "low": 2}
TYPE_RANK = {"boarder_blocked": 0, "boarder_no_bed": 0, "unit_full": 1,
             "stale_bed": 2, "cleaning_overdue": 3, "discharge_backlog": 4,
             "feed_mismatch": 5}
KEY_ATTRS = {
    "patient": ["status", "bed_id", "assigned_bed", "unit_id", "admit_time",
                "transport_status", "esi_acuity", "expected_discharge"],
    "bed": ["status", "status_since", "unit_id", "patient_id", "cleaning_status",
            "cleaning_assigned_to", "cleaning_created_at", "cleaning_target_minutes"],
    "staff": ["label", "role", "status", "location", "zone", "DEPARTMENT", "SHIFT"],
    "unit": ["UNIT_NAME", "BED_COUNT", "FLOOR"],
}
EID_RE = re.compile(r"\b(?:bed|patient|staff|unit|ambulance):[A-Za-z0-9&_\-]+")


# ---------- helpers ----------

def _llm(prompt, system):
    from llm import generator  # imported lazily so tests run without API keys
    return generator(prompt, system)


def _parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = text.replace("```json", "").replace("```", "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


def ask_json(agent, system, prompt):
    for attempt in (1, 2):
        raw = _llm(prompt, system)
        try:
            return _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as err:
            log(agent, "bad_json", {"attempt": attempt, "error": str(err),
                                    "raw": (raw or "")[:500]})
            prompt += "\n\nYour last reply was not valid JSON. Reply with JSON only."
    return {}


def neighborhood(wm, seeds, limit=40):
    picked = list(dict.fromkeys(e for e in seeds if e in wm.entities))
    seedset = set(picked)
    for rel in wm.relations:
        if len(picked) >= limit:
            break
        if rel["subject"] in seedset and rel["object"] not in picked:
            picked.append(rel["object"])
        elif rel["object"] in seedset and rel["subject"] not in picked:
            picked.append(rel["subject"])
    return [e for e in picked if e in wm.entities][:limit]


def compact_context(wm, eids):
    lines = []
    for eid in eids:
        ent = wm.entities[eid]
        parts = []
        for attr in KEY_ATTRS.get(ent["kind"], []):
            for src, slot in (ent["attrs"].get(attr) or {}).items():
                parts.append(f"{attr}={slot['value']!r} ({src}"
                             + (f" @{slot['as_of']}" if attr == "status" else "")
                             + ")")
        lines.append(f"{eid}: " + ("; ".join(parts) or "(no key attributes)"))
    return "\n".join(lines)


# ---------- agents ----------

def collector():
    wm = WorldModel()
    wm.ingest_live(live_snapshot())
    wm.ingest_reference(reference_data())
    log("collector", "world_model_built",
        {"entities": len(wm.entities), "relations": len(wm.relations)})
    print(f"[Collector] World Model: {len(wm.entities)} entities, "
          f"{len(wm.relations)} relations")
    return wm


def monitor(wm):
    issues = find_issues(wm)
    issues.sort(key=lambda i: (SEV_RANK.get(i["severity"], 9),
                               TYPE_RANK.get(i["type"], 9)))
    log("monitor", "issues_ranked",
        {"count": len(issues), "top": [i["summary"] for i in issues[:5]]})
    print(f"[Monitor] {len(issues)} issue(s) found")
    for n, issue in enumerate(issues[:5]):
        print(f"   {n}. [{issue['severity']}] {issue['summary']}")
    return issues


INVESTIGATOR_SYSTEM = (
    "You are the Investigator agent on a hospital operations team. Explain the "
    "problem using ONLY the evidence provided. Every factual statement must be "
    "backed by a claim that cites an entity id and attribute exactly as they "
    "appear in the evidence, with the exact value shown. You may cite the "
    "Monitor's finding as entity \"issue\", attribute \"summary\". If the "
    "evidence is not enough to know the cause, say so and lower your confidence. "
    "Reply with JSON only."
)


def investigator(issue, context, question=None, feedback=None):
    prompt = (
        f"MONITOR FINDING:\n{issue['summary']}\n\n"
        f"FINDING EVIDENCE:\n{json.dumps(issue['evidence'], default=str)}\n\n"
        f"WORLD MODEL CONTEXT (entity: attribute=value (source)):\n{context}\n\n"
    )
    if question:
        prompt += f"OPERATOR QUESTION: {question}\n\n"
    if feedback:
        prompt += ("THE CRITIC REJECTED YOUR LAST DRAFT. Fix these problems:\n- "
                   + "\n- ".join(feedback) + "\n\n")
    prompt += (
        'Return JSON: {"cause": "one sentence", '
        '"explanation": "2-4 sentences", '
        '"actions": ["up to 3 concrete actions"], '
        '"claims": [{"entity": "bed:4E-410A", "attribute": "status", '
        '"value": "dirty"}], '
        '"confidence": "high|medium|low"}'
    )
    draft = ask_json("investigator", INVESTIGATOR_SYSTEM, prompt)
    log("investigator", "draft", draft)
    return draft


def verify_claims(wm, draft):
    """Deterministic checks: cited entities exist and values match."""
    problems = []
    claims = draft.get("claims") or []
    if not claims:
        problems.append("No claims cited. Every statement needs evidence.")
    for claim in claims:
        eid, attr = claim.get("entity"), claim.get("attribute")
        if eid == "issue":
            continue
        ent = wm.entities.get(eid)
        if ent is None:
            problems.append(f"Claim cites {eid}, which does not exist in the World Model.")
            continue
        slots = ent["attrs"].get(attr)
        if not slots:
            problems.append(f"{eid} has no attribute '{attr}'.")
            continue
        actual = {str(s["value"]).strip().lower() for s in slots.values()}
        if str(claim.get("value")).strip().lower() not in actual:
            problems.append(f"{eid}.{attr} is {sorted(actual)}, "
                            f"not {claim.get('value')!r}.")
    text = " ".join([str(draft.get("cause", "")), str(draft.get("explanation", ""))]
                    + [str(a) for a in draft.get("actions") or []])
    for eid in sorted(set(EID_RE.findall(text))):
        if eid not in wm.entities:
            problems.append(f"Text mentions {eid}, which does not exist.")
    return problems


CRITIC_SYSTEM = (
    "You are the Critic agent on a hospital operations team. Check another "
    "agent's explanation against the evidence. Reject it if it states facts not "
    "in the evidence, invents a cause, overstates certainty, or recommends "
    "actions that do not follow from the evidence. Reply with JSON only: "
    '{"verdict": "pass" or "revise", "problems": ["..."]}'
)


def critic(wm, issue, context, draft):
    code_problems = verify_claims(wm, draft)
    prompt = (
        f"MONITOR FINDING:\n{issue['summary']}\n\n"
        f"EVIDENCE:\n{context}\n\n"
        f"DRAFT TO REVIEW:\n{json.dumps(draft, default=str)}\n\n"
        f"AUTOMATED CLAIM CHECK FOUND: {code_problems or 'no problems'}"
    )
    review = ask_json("critic", CRITIC_SYSTEM, prompt)
    problems = code_problems + list(review.get("problems") or [])
    verdict = "pass" if not code_problems and review.get("verdict") == "pass" else "revise"
    result = {"verdict": verdict, "problems": problems,
              "code_problems": code_problems}
    log("critic", "review", result)
    return result


EXPLAINER_SYSTEM = (
    "You are the Explainer agent. Write a short message for the hospital bed "
    "manager from an approved analysis. Use only facts in the analysis. Format:\n"
    "WHAT: one sentence\nWHY: one or two sentences\n"
    "DO NOW: up to 3 bullet points\nEVIDENCE: the entity ids relied on"
)


def explainer(draft, verified):
    message = _llm(json.dumps(draft, default=str), EXPLAINER_SYSTEM)
    message = re.sub(r"<think>.*?</think>", "", message or "", flags=re.S).strip()
    if not verified:
        message = ("UNVERIFIED: the Critic did not approve this analysis.\n\n"
                   + message)
    log("explainer", "message", {"verified": verified, "message": message})
    return message


# ---------- orchestration ----------

def run(issue_index=0, question=None):
    wm = collector()
    issues = monitor(wm)
    if not issues:
        print("[Monitor] Nothing to investigate right now.")
        return None
    issue = issues[min(issue_index, len(issues) - 1)]
    context = compact_context(wm, neighborhood(wm, issue["entities"]))
    print(f"\n[Monitor] Investigating: {issue['summary']}")

    feedback, draft, review, rounds = None, {}, {"verdict": "revise"}, []
    for rnd in range(1, MAX_ROUNDS + 1):
        draft = investigator(issue, context, question, feedback)
        print(f"\n[Investigator] round {rnd}: {draft.get('cause', '(no cause)')}")
        review = critic(wm, issue, context, draft)
        rounds.append({"round": rnd, "draft": draft, "review": review})
        print(f"[Critic] round {rnd}: {review['verdict'].upper()}")
        for p in review["problems"][:5]:
            print(f"   - {p}")
        if review["verdict"] == "pass":
            break
        feedback = review["problems"]

    verified = review["verdict"] == "pass"
    message = explainer(draft, verified)
    print(f"\n[Explainer]\n{message}")

    result = {"run_id": RUN_ID, "issue": issue, "question": question,
              "rounds": rounds, "verified": verified, "message": message}
    os.makedirs("logs", exist_ok=True)
    with open(f"logs/answer_{RUN_ID}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    log("orchestrator", "done", {"verified": verified, "rounds": len(rounds)})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Ops multi-agent run")
    parser.add_argument("--issue", type=int, default=0,
                        help="which ranked issue to investigate (0 = most urgent)")
    parser.add_argument("--question", help="optional operator question")
    args = parser.parse_args()
    run(args.issue, args.question)