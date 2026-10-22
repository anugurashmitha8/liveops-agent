import json
from zetaris_tool import run_sql


def api_items(table):
    row = run_sql(f"SELECT * FROM {table} LIMIT 1", limit=1)[0]
    return json.loads(row["items"])


def live_snapshot():
    assets = api_items("api.assets")
    return {
        "beds": api_items("api.beds"),
        "patients": api_items("api.patients"),
        "cleaning_tasks": api_items("api.cleaning_tasks"),
        "transport_requests": api_items("api.transport_requests"),
        "staff": [item for item in assets if item.get("kind") == "staff"],
        "ambulances": [item for item in assets if item.get("kind") == "ambulance"],
    }


def reference_data():
    return {
        "units": run_sql("SELECT * FROM riverside.UNITS", limit=1000),
        "staff_roster": run_sql("SELECT * FROM riverside.STAFF", limit=1000),
        "ambulances": run_sql("SELECT * FROM riverside.AMBULANCES", limit=1000),
        "floors": run_sql("SELECT * FROM riverside.FLOORS", limit=1000),
        "locations": run_sql("SELECT * FROM riverside.LOCATIONS", limit=1000),
    }


if __name__ == "__main__":
    live = live_snapshot()
    ref = reference_data()
    print("live_snapshot")
    for name, items in live.items():
        print(f"  {name}: {len(items)}")
    print("reference_data")
    for name, items in ref.items():
        print(f"  {name}: {len(items)}")
