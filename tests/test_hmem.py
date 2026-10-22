from datetime import datetime, timedelta, timezone

from hmem import HMem
from world_model import LIVE, WorldModel

T0 = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)
ISSUE = {"type": "unit_full", "summary": "ICU full",
         "entities": ["unit:ICU"], "evidence": []}


def test_issue_duration_then_resolution(tmp_path):
    mem = HMem(root=str(tmp_path))
    wm = WorldModel()
    assert mem.observe(wm, [ISSUE], T0)["new"] == ["unit_full|unit:ICU"]
    mem.observe(wm, [ISSUE], T0 + timedelta(minutes=20))
    assert "20 min ago" in mem.recall(ISSUE, T0 + timedelta(minutes=20))
    seen = mem.observe(wm, [], T0 + timedelta(minutes=30))
    assert seen["resolved"] == ["unit_full|unit:ICU"]
    resolved = [e for e in mem.episodes() if e["kind"] == "resolved"]
    assert resolved[0]["minutes_open"] == 30


def test_newer_status_replaces_older_and_is_ledgered(tmp_path):
    mem = HMem(root=str(tmp_path))
    wm = WorldModel()
    wm.upsert("patient", "P1", {"status": "discharge_ordered"}, LIVE, "2026-10-22T16:00:00Z")
    mem.observe(wm, [], T0)
    assert mem.status_age("patient:P1", T0 + timedelta(minutes=15)) == ("discharge_ordered", 15)
    wm.upsert("patient", "P1", {"status": "boarding"}, LIVE, "2026-10-22T16:20:00Z")
    mem.observe(wm, [], T0 + timedelta(minutes=20))
    assert mem.status_age("patient:P1", T0 + timedelta(minutes=20)) == ("boarding", 0)
    ledger = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert '"replaced": "discharge_ordered"' in ledger


def test_memory_persists_across_sessions(tmp_path):
    mem = HMem(root=str(tmp_path))
    mem.observe(WorldModel(), [ISSUE], T0)
    mem.save()
    again = HMem(root=str(tmp_path))
    assert "unit_full|unit:ICU" in again.working["issues"]


def test_repeated_episodes_become_a_lesson(tmp_path):
    mem = HMem(root=str(tmp_path))
    wm = WorldModel()
    for start in (0, 60):
        mem.observe(wm, [ISSUE], T0 + timedelta(minutes=start))
        mem.observe(wm, [], T0 + timedelta(minutes=start + 10))
    lessons = mem.consolidate()
    assert "cleared 2 time(s)" in lessons["unit_full|unit:ICU"]["text"]