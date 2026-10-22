# Live Ops Agent

**Team Mirror Works · Open Agent Hackathon 2026 · Track 1: Solving Fragmented Intelligence**

Hospital operations data is scattered across systems that don't talk to each other. A live operations feed knows where patients, beds, cleaners and transporters are right now. A separate data warehouse holds the official unit capacities, staff rosters and ambulance crews. The problems that back up a hospital, like an ED full of patients waiting for beds that are held by people who could already go home, only become visible when you join the two.

Live Ops Agent pulls these sources together through **Zetaris**, builds one shared, source-tracked picture of the hospital with the **Meterless World Model**, and detects operational bottlenecks that no single system shows on its own. Multi-agent reasoning on **NVIDIA Nemotron** (in progress) explains each problem and backs every claim with evidence.

---

## Example finding (from live data)

> 5 units have **0 available beds** (ED, ICU, CVU and others), while **25 patients** across the hospital are **cleared for discharge with no transport arranged**, still holding beds.

Neither source shows this alone. The live feed has bed and patient statuses; the warehouse has official unit capacities. The World Model joins them.

---

## Architecture

```
Live hospital API ──┐
                    ├──► Zetaris ──► sources.py ──► World Model ──► Issue detector ──► Agents (in progress)
Snowflake warehouse ┘    (federated      (both        (Meterless:      (bottlenecks        (Nemotron:
                          SQL access)     sources)     entities,         with evidence)      explain, critique,
                                                       relations,                            recommend)
                                                       provenance)
                                    every step ──► logs/*.jsonl
```

| Component | File | What it does |
|---|---|---|
| Data access | `zetaris_tool.py` | Runs SQL against Zetaris with automatic login and token refresh |
| Sources | `sources.py` | Live snapshot (patients, beds, cleaning, transport, staff, ambulances) and reference data (units, roster, ambulance crews, floors, locations) |
| World Model | `world_model.py` | Meterless World Model: stable IDs (`kind:id`), multi-source attributes with provenance, relations, idempotent ingest, conflict detection |
| Issue detector | `issues.py` | Finds discharge backlog, full units, blocked ED boarders, overdue cleaning, stale bed records, feed mismatches |
| LLM | `llm.py` | NVIDIA Nemotron via an OpenAI-compatible endpoint |
| Logging | `logger.py` | JSONL trace of every step, one file per run, in `logs/` |

---

## Sponsor technology

**Zetaris**: the data layer. One SQL interface over two very different sources, a live REST API and a Snowflake warehouse, without copying data. All reads in this project go through Zetaris.

**Meterless (World Model engine)**: the shared state every agent reads and writes. Each entity has a stable ID; each attribute keeps its value per source with a timestamp; relations link patients, beds, units, staff and locations. Ingest is idempotent: loading the same data twice produces an empty diff, which is tested. **H-MEM** (incident memory) is planned next.

**NVIDIA Nemotron**: the reasoning model for the agents (`nemotron-3.5-lightning-30b-a3b` via the NVIDIA API).

**AI coding tools**: the World Model and its tests were built with Cursor's agent (screenshots in the submission); later work was done with Claude.

---

## Status

**Working now**
- Zetaris access to both sources
- World Model with provenance, relations and conflict checks
- Issue detector running on live data
- Test suite: 4 passing tests

**In progress**
- Agents: Investigator (explains cause), Critic (verifies evidence, sends weak answers back), Explainer (operator-facing answer)
- H-MEM memory: when problems started, what resolved them before
- Operator screen: hospital view, alerts, "Why?" panel, agent activity feed
- Sample mode that runs without credentials

---

## Setup

Requirements: Python 3.11+, a running Zetaris instance with two data sources configured (`api` for the live hospital feed, `riverside` for the Snowflake warehouse), and an NVIDIA API key.

```bash
git clone https://github.com/anugurashmitha8/liveops-agent.git
cd liveops-agent
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your Zetaris and NVIDIA settings. `.env` is git-ignored; never commit it.

## Run

```bash
python sources.py       # check both sources load
python world_model.py   # build the World Model, save logs/world_model_snapshot.json
python issues.py        # detect bottlenecks, save logs/issues_latest.json
python -m pytest tests/ -v
```

Every run writes a trace to `logs/run_*.jsonl`.

---

## Notes on the data

The hospital data is **simulated**: no real patients are involved.

The Snowflake warehouse runs its own separate simulator for patients. Because its patients never match the live feed, this project uses Snowflake **only for reference data** (unit capacities, staff roster and shifts, ambulance crews, floors and locations) and takes all live activity from the API. Staff and bed IDs match across both sources (74 of 74 staff, 118 of 118 beds), which is what the World Model joins on.

## Pre-existing components

Built before the hackathon and used here as infrastructure: the Zetaris instance and its source connections, the live hospital API simulator, and the Snowflake warehouse and its simulator. Everything in this repository was written during the hackathon, starting 22 October 2026.

## License

MIT