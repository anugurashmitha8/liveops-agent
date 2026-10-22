import json
from zetaris_tool import run_sql

def api_items(table):
    row = run_sql(f"SELECT * FROM {table} LIMIT 1", limit=1)[0]
    return json.loads(row["items"])

def get_id(item, *keys):
    for k in keys:
        if item.get(k):
            return item[k]

api_patients = {get_id(p, "patient_id", "id") for p in api_items("api.patients")}
api_staff = {a["id"] for a in api_items("api.assets") if a.get("kind") == "staff"}

db_patients = {r["PATIENT_ID"] for r in run_sql("SELECT PATIENT_ID FROM riverside.PATIENTS", limit=1000)}
db_staff = {r["STAFF_ID"] for r in run_sql("SELECT STAFF_ID FROM riverside.STAFF", limit=1000)}

print(f"Patients  api={len(api_patients)}  db={len(db_patients)}  shared={len(api_patients & db_patients)}")
print(f"Staff     api={len(api_staff)}  db={len(db_staff)}  shared={len(api_staff & db_staff)}")
print("Sample api patients:", sorted(api_patients)[:5])
print("Sample db patients: ", sorted(db_patients)[:5])

print("\n--- riverside API_* copies vs live api ---")
for db_table, api_table, key in [
    ("riverside.API_PATIENTS", "api.patients", "patient_id"),
    ("riverside.API_BEDS", "api.beds", "bed_id"),
]:
    try:
        rows = run_sql(f"SELECT * FROM {db_table}", limit=1000)
        cols = list(rows[0].keys()) if rows else []
        print(f"\n{db_table}: {len(rows)} rows, columns: {cols}")
        if rows and "items" in rows[0]:
            db_ids = {get_id(i, key, "id") for i in json.loads(rows[0]["items"])}
        else:
            id_col = next((c for c in cols if c.lower() in (key, "id")), None)
            db_ids = {r[id_col] for r in rows} if id_col else set()
        live_ids = {get_id(i, key, "id") for i in api_items(api_table)}
        print(f"  live={len(live_ids)}  copy={len(db_ids)}  shared={len(live_ids & db_ids)}")
    except Exception as e:
        print(f"\n{db_table}: ERROR {e}")