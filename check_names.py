from sources import api_items
from zetaris_tool import run_sql

names = ["Patricia Wright", "Patricia Ibarra", "Marc Murphy",
         "Sonya Pierce", "Stacey Chandler", "Taylor Jones"]

api = {f"{p.get('first_name')} {p.get('last_name')}": p.get("patient_id")
       for p in api_items("api.patients")}
db = {f"{r['FIRST_NAME']} {r['LAST_NAME']}": r["PATIENT_ID"]
      for r in run_sql("SELECT PATIENT_ID, FIRST_NAME, LAST_NAME FROM riverside.PATIENTS", limit=2000)}

for n in names:
    print(f"{n:18} live API: {api.get(n, '-'):10}  Snowflake: {db.get(n, '-')}")