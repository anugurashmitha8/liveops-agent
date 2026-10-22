"""World model tests — load cached snapshot so they run without Zetaris."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from world_model import LIVE, REF, WorldModel

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "logs" / "test_snapshot.json"


@pytest.fixture(scope="module")
def snapshot():
    if not SNAPSHOT_PATH.exists():
        pytest.skip(
            f"{SNAPSHOT_PATH} missing — run `python world_model.py` once with Zetaris"
        )
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        return json.load(f)


def _ingest_both(wm: WorldModel, snapshot: dict):
    wm.ingest_live(snapshot["live"])
    wm.ingest_reference(snapshot["reference"])


def test_idempotency(snapshot):
    wm = WorldModel()
    _ingest_both(wm, snapshot)

    n_entities = len(wm.entities)
    n_relations = len(wm.relations)
    values_before = json.dumps(wm.entities, sort_keys=True, default=str)

    wm.reset_diff()
    _ingest_both(wm, snapshot)
    diff = wm.last_diff

    assert len(wm.entities) == n_entities
    assert len(wm.relations) == n_relations
    assert diff["new_entities"] == []
    assert diff["new_relations"] == []
    assert diff["changed_values"] == []
    assert json.dumps(wm.entities, sort_keys=True, default=str) == values_before


def test_stable_ids(snapshot):
    a = WorldModel()
    b = WorldModel()
    _ingest_both(a, snapshot)
    _ingest_both(b, snapshot)

    beds_a = sorted(e for e in a.entities if e.startswith("bed:"))
    beds_b = sorted(e for e in b.entities if e.startswith("bed:"))
    patients_a = sorted(e for e in a.entities if e.startswith("patient:"))
    patients_b = sorted(e for e in b.entities if e.startswith("patient:"))
    staff_a = sorted(e for e in a.entities if e.startswith("staff:"))
    staff_b = sorted(e for e in b.entities if e.startswith("staff:"))

    assert beds_a
    assert patients_a
    assert staff_a
    assert beds_a == beds_b
    assert patients_a == patients_b
    assert staff_a == staff_b


def test_conflict_staff_outside_department(snapshot):
    wm = WorldModel()
    _ingest_both(wm, snapshot)

    # Hand-made on-duty nurse badged in ICU while rostered to ED
    wm.upsert(
        "staff",
        "S_TEST_BADGE",
        {
            "label": "Test Badge",
            "status": "on_duty",
            "location": "ICU-201",
            "zone": "ICU",
        },
        LIVE,
        "2026-10-22T12:00:00Z",
    )
    wm.upsert(
        "staff",
        "S_TEST_BADGE",
        {"ROLE": "Registered Nurse", "DEPARTMENT": "ED", "SHIFT": "Day", "PHONE_EXT": "x9999"},
        REF,
        "2026-10-22T12:00:00Z",
    )

    conflicts = wm.find_conflicts()
    hits = [
        c
        for c in conflicts
        if c.get("entity") == "staff:S_TEST_BADGE"
        and "outside rostered department" in c.get("reason", "")
    ]
    assert hits, f"expected department conflict, got: {conflicts[:10]}"
    assert hits[0]["values"][LIVE] in ("ICU-201", "ICU")
    assert hits[0]["values"][REF] == "ED"
