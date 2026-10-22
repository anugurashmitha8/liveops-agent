import json
from collections import Counter
from sources import live_snapshot

live = live_snapshot()

print("patient statuses:", Counter(p.get("status") for p in live["patients"]))
print("bed statuses:", Counter(b.get("status") for b in live["beds"]))
print("cleaning statuses:", Counter(t.get("status") for t in live["cleaning_tasks"]))
print("transport statuses:", Counter(t.get("status") for t in live["transport_requests"]))

print("\ncleaning task fields:", sorted(live["cleaning_tasks"][0].keys()))
print("transport fields:", sorted(live["transport_requests"][0].keys()))
print("patient fields:", sorted(live["patients"][0].keys()))
print("bed fields:", sorted(live["beds"][0].keys()))

boarders = [p for p in live["patients"] if p.get("status") == "boarding"]
print(f"\nboarders: {len(boarders)}")
for p in boarders[:3]:
    print(json.dumps({k: p.get(k) for k in ("patient_id", "bed_id", "assigned_bed",
          "admit_time", "updated_at", "transport_status")}, default=str))

open_clean = [t for t in live["cleaning_tasks"] if t.get("status") != "completed"]
print(f"\nopen cleaning tasks: {len(open_clean)}")
for t in open_clean[:3]:
    print(json.dumps(t, default=str))