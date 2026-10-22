from zetaris_tool import run_sql

TABLES = [
    "api.beds",
    "api.patients",
    "api.cleaning_tasks",
    "api.transport_requests",
    "api.assets",
    "riverside.BEDS",
    "riverside.PATIENTS",
    "riverside.STAFF",
    "riverside.AMBULANCES",
    "riverside.UNITS",
    "riverside.FLOORS",
    "riverside.LOCATIONS",
    "riverside.CLEANING_TASKS",
    "riverside.TRANSPORT_REQUESTS",
    "riverside.API_EVENTS",
    "riverside.API_SUMMARY",
]

if __name__ == "__main__":
    for table in TABLES:
        try:
            rows = run_sql(f"SELECT * FROM {table} LIMIT 1")
            columns = list(rows[0].keys()) if rows else []
            print(f"{table}: {columns}")
            print(rows[0] if rows else None)
        except Exception as e:
            print(f"{table}: ERROR {e}")
        print()
