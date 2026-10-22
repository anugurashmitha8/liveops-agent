from issues import find_issues
from world_model import LIVE, WorldModel


def test_boarder_blocked_by_dirty_bed_with_cleaner_on_break():
    wm = WorldModel()
    t = "2026-10-22T16:30:00Z"
    wm.upsert("staff", "S1", {"label": "Amber Kidd", "status": "on_break",
                              "role": "EVS Technician"}, LIVE, t)
    wm.upsert("bed", "4E-410A", {
        "status": "dirty", "unit_id": "4E",
        "cleaning_status": "assigned", "cleaning_assigned_to": "Amber Kidd",
        "cleaning_created_at": "2026-10-22T15:30:00Z",
        "cleaning_target_minutes": 45}, LIVE, t)
    wm.upsert("patient", "P1", {
        "status": "boarding", "bed_id": "ED-05", "assigned_bed": "4E-410A",
        "admit_time": "2026-10-22T15:00:00Z"}, LIVE, "2026-10-22T16:40:00Z")

    issues = find_issues(wm)
    types = {i["type"] for i in issues}
    assert "boarder_blocked" in types
    assert "cleaning_overdue" in types

    boarder = next(i for i in issues if i["type"] == "boarder_blocked")
    assert "staff:S1" in boarder["entities"]
    assert "on_break" in boarder["summary"]