from zetaris_tool import run_sql

for t in ["api.assets", "api.beds", "api.patients", "api.cleaning_tasks", "api.transport_requests"]:
    try:
        rows = run_sql(f"SELECT * FROM {t} LIMIT 3", limit=3)
        print(f"\n=== {t}: {len(rows)} rows ===")
        if rows:
            for col, val in rows[0].items():
                print(f"  {col}: {type(val).__name__} -> {str(val)[:150]}")
    except Exception as e:
        print(f"\n=== {t}: ERROR {e}")