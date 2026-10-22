"""Hospital operations world model (Meterless-style entities + relations)."""

from __future__ import annotations

import json
import os
import re
from collections import Counter

from logger import log
from sources import live_snapshot, reference_data

LIVE = "live_api"
REF = "snowflake_ref"


def _eid(kind: str, native_id: str) -> str:
    return f"{kind}:{native_id}"


def _norm_space(text) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _attrs_from_item(item: dict, *, skip: set[str] | None = None) -> dict:
    skip = skip or set()
    out = {}
    for k, v in item.items():
        if k in skip or k == "updated_at" or v is None:
            continue
        out[k] = v
    return out


class WorldModel:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.relations: list[dict] = []
        self._relation_index: set[tuple] = set()
        self.last_diff: dict = {
            "new_entities": [],
            "new_relations": [],
            "changed_values": [],
        }

    def reset_diff(self):
        self.last_diff = {
            "new_entities": [],
            "new_relations": [],
            "changed_values": [],
        }

    def upsert(self, kind, native_id, attrs, source, as_of):
        native_id = str(native_id)
        eid = _eid(kind, native_id)
        changed = False
        changed_attrs = []
        is_new = False

        if eid not in self.entities:
            self.entities[eid] = {
                "kind": kind,
                "native_id": native_id,
                "attrs": {},
            }
            self.last_diff["new_entities"].append(eid)
            is_new = True
            changed = True

        ent = self.entities[eid]
        for name, value in (attrs or {}).items():
            slots = ent["attrs"].setdefault(name, {})
            prev = slots.get(source)
            entry = {"value": value, "as_of": as_of}
            prev_as_of = (prev or {}).get("as_of") or ""
            new_as_of = as_of or ""
            if prev is None:
                should_write = True
            elif prev.get("value") == value:
                # same value: only advance as_of when newer
                should_write = bool(new_as_of) and new_as_of > prev_as_of
            else:
                # different value: keep the newer observation (equal as_of → last write wins)
                should_write = (not prev_as_of) or (new_as_of >= prev_as_of)
            if should_write:
                slots[source] = entry
                self.last_diff["changed_values"].append(
                    {"entity": eid, "attribute": name, "source": source, "value": value}
                )
                changed_attrs.append(name)
                changed = True

        if changed:
            log(
                "world_model",
                "upsert",
                {
                    "entity": eid,
                    "source": source,
                    "attrs": changed_attrs,
                    "new": is_new,
                },
            )
        return eid

    def relate(self, subject, relation, object, source, as_of):
        key = (subject, relation, object, source)
        if key in self._relation_index:
            for rel in self.relations:
                if (
                    rel["subject"] == subject
                    and rel["relation"] == relation
                    and rel["object"] == object
                    and rel["source"] == source
                ):
                    prev_as_of = rel.get("as_of") or ""
                    new_as_of = as_of or ""
                    if new_as_of and new_as_of > prev_as_of:
                        rel["as_of"] = as_of
                        self.last_diff["changed_values"].append(
                            {"relation": list(key), "as_of": as_of}
                        )
                        log(
                            "world_model",
                            "relate",
                            {
                                "subject": subject,
                                "relation": relation,
                                "object": object,
                                "source": source,
                                "as_of": as_of,
                            },
                        )
                    return
            return

        edge = {
            "subject": subject,
            "relation": relation,
            "object": object,
            "source": source,
            "as_of": as_of,
        }
        self.relations.append(edge)
        self._relation_index.add(key)
        self.last_diff["new_relations"].append(edge)
        log(
            "world_model",
            "relate",
            {
                "subject": subject,
                "relation": relation,
                "object": object,
                "source": source,
            },
        )

    def ingest_live(self, snapshot: dict):
        staff_by_label: dict[str, str] = {}

        for bed in snapshot.get("beds") or []:
            as_of = bed.get("updated_at")
            bed_id = bed.get("bed_id") or bed.get("id")
            if not bed_id:
                continue
            eid = self.upsert(
                "bed",
                bed_id,
                _attrs_from_item(bed, skip={"bed_id"}),
                LIVE,
                as_of,
            )
            unit_id = bed.get("unit_id")
            if unit_id:
                self.upsert("unit", unit_id, {}, LIVE, as_of)
                self.relate(eid, "in_unit", _eid("unit", unit_id), LIVE, as_of)
            patient_id = bed.get("patient_id")
            if patient_id:
                # bed occupancy also expressed via patient in_bed below
                pass

        for patient in snapshot.get("patients") or []:
            as_of = patient.get("updated_at")
            pid = patient.get("patient_id") or patient.get("id")
            if not pid:
                continue
            eid = self.upsert(
                "patient",
                pid,
                _attrs_from_item(patient, skip={"patient_id"}),
                LIVE,
                as_of,
            )
            bed_id = patient.get("bed_id") or patient.get("assigned_bed")
            if bed_id:
                self.upsert("bed", bed_id, {}, LIVE, as_of)
                self.relate(eid, "in_bed", _eid("bed", bed_id), LIVE, as_of)

        for staff in snapshot.get("staff") or []:
            as_of = staff.get("updated_at")
            sid = staff.get("id") or staff.get("staff_id")
            if not sid:
                continue
            label = staff.get("label")
            if label:
                staff_by_label[label] = str(sid)
            eid = self.upsert(
                "staff",
                sid,
                _attrs_from_item(staff, skip={"id", "kind"}),
                LIVE,
                as_of,
            )
            loc = staff.get("location")
            if loc:
                self.upsert("location", loc, {"name": loc}, LIVE, as_of)
                self.relate(eid, "located_at", _eid("location", loc), LIVE, as_of)
            floor = staff.get("floor")
            floor_name = staff.get("floor_name")
            if floor is not None and floor_name is not None:
                self.upsert(
                    "location",
                    f"floor:{floor}",
                    {"floor_name": floor_name, "floor": str(floor)},
                    LIVE,
                    as_of,
                )

        # patient → assigned_nurse after staff labels are known
        for patient in snapshot.get("patients") or []:
            as_of = patient.get("updated_at")
            pid = patient.get("patient_id") or patient.get("id")
            nurse = patient.get("assigned_nurse")
            if not pid or not nurse:
                continue
            sid = staff_by_label.get(nurse)
            if sid:
                self.relate(
                    _eid("patient", pid),
                    "assigned_nurse",
                    _eid("staff", sid),
                    LIVE,
                    as_of,
                )

        for amb in snapshot.get("ambulances") or []:
            as_of = amb.get("updated_at")
            aid = amb.get("id")
            if not aid:
                continue
            self.upsert(
                "ambulance",
                aid,
                _attrs_from_item(amb, skip={"id", "kind"}),
                LIVE,
                as_of,
            )

        for task in snapshot.get("cleaning_tasks") or []:
            as_of = task.get("updated_at")
            bed_id = task.get("bed_id")
            if not bed_id:
                continue
            attrs = {
                "cleaning_task_id": task.get("task_id"),
                "cleaning_status": task.get("status"),
                "cleaning_type": task.get("clean_type"),
                "cleaning_priority": task.get("priority"),
                "cleaning_assigned_to": task.get("assigned_to"),
            }
            attrs = {k: v for k, v in attrs.items() if v is not None}
            self.upsert("bed", bed_id, attrs, LIVE, as_of)
            assigned = task.get("assigned_to")
            if assigned and assigned in staff_by_label:
                self.relate(
                    _eid("bed", bed_id),
                    "cleaning_assigned_to",
                    _eid("staff", staff_by_label[assigned]),
                    LIVE,
                    as_of,
                )

        for req in snapshot.get("transport_requests") or []:
            as_of = req.get("updated_at")
            pid = req.get("patient_id")
            if not pid:
                continue
            attrs = {
                "transport_request_id": req.get("request_id"),
                "transport_status": req.get("status"),
                "transport_from": req.get("from"),
                "transport_to": req.get("to"),
                "transport_priority": req.get("priority"),
                "transporter": req.get("transporter"),
            }
            attrs = {k: v for k, v in attrs.items() if v is not None}
            self.upsert("patient", pid, attrs, LIVE, as_of)

        return self.last_diff

    def ingest_reference(self, ref: dict):
        floor_name_by_floor = {
            str(row["FLOOR"]): row["FLOOR_NAME"]
            for row in (ref.get("floors") or [])
            if row.get("FLOOR") is not None and row.get("FLOOR_NAME") is not None
        }

        for unit in ref.get("units") or []:
            uid = unit.get("UNIT_ID")
            if not uid:
                continue
            as_of = unit.get("UPDATED_AT")
            attrs = {
                k: unit[k]
                for k in ("UNIT_NAME", "FLOOR", "UNIT_TYPE", "BED_COUNT")
                if unit.get(k) is not None
            }
            self.upsert("unit", uid, attrs, REF, as_of)
            floor = unit.get("FLOOR")
            if floor is not None and str(floor) in floor_name_by_floor:
                self.upsert(
                    "location",
                    f"floor:{floor}",
                    {
                        "floor_name": floor_name_by_floor[str(floor)],
                        "floor": str(floor),
                    },
                    REF,
                    as_of,
                )

        for row in ref.get("staff_roster") or []:
            sid = row.get("STAFF_ID")
            if not sid:
                continue
            as_of = row.get("UPDATED_AT")
            attrs = {
                k: row[k]
                for k in ("ROLE", "DEPARTMENT", "SHIFT", "PHONE_EXT")
                if row.get(k) is not None
            }
            eid = self.upsert("staff", sid, attrs, REF, as_of)
            dept = row.get("DEPARTMENT")
            if dept:
                self.upsert("unit", dept, {}, REF, as_of)
                self.relate(eid, "rostered_to", _eid("unit", dept), REF, as_of)

        for row in ref.get("ambulances") or []:
            call_sign = row.get("CALL_SIGN")
            if not call_sign:
                continue
            as_of = row.get("UPDATED_AT")
            attrs = {
                k: row[k]
                for k in ("CALL_SIGN", "TYPE", "HOME_STATION", "CREW")
                if row.get(k) is not None
            }
            self.upsert("ambulance", call_sign, attrs, REF, as_of)

        return self.last_diff

    def find_conflicts(self) -> list[dict]:
        conflicts: list[dict] = []

        # (1) + (4) cross-source attribute disagreements
        for eid, ent in self.entities.items():
            for attr, sources in ent["attrs"].items():
                if len(sources) < 2:
                    continue
                by_source = {src: slot["value"] for src, slot in sources.items()}
                values = list(by_source.values())
                encoded = {json.dumps(v, sort_keys=True, default=str) for v in values}
                if len(encoded) == 1:
                    continue

                if attr == "floor_name":
                    norms = {_norm_space(v) for v in values}
                    if len(norms) == 1 and next(iter(norms)) != "":
                        conflicts.append(
                            {
                                "entity": eid,
                                "attribute": attr,
                                "values": by_source,
                                "reason": "floor_name differs only in spacing",
                            }
                        )
                        continue

                conflicts.append(
                    {
                        "entity": eid,
                        "attribute": attr,
                        "values": by_source,
                        "reason": "same attribute has different values across sources",
                    }
                )

        # (2) live bed count per unit vs UNITS.BED_COUNT
        live_beds = Counter()
        for ent in self.entities.values():
            if ent["kind"] != "bed":
                continue
            unit_slot = (ent["attrs"].get("unit_id") or {}).get(LIVE)
            if unit_slot and unit_slot.get("value") is not None:
                live_beds[str(unit_slot["value"])] += 1

        for eid, ent in self.entities.items():
            if ent["kind"] != "unit":
                continue
            bed_count_slot = (ent["attrs"].get("BED_COUNT") or {}).get(REF)
            if not bed_count_slot:
                continue
            try:
                expected = int(bed_count_slot["value"])
            except (TypeError, ValueError):
                continue
            uid = ent["native_id"]
            actual = live_beds.get(uid, 0)
            if actual != expected:
                conflicts.append(
                    {
                        "entity": eid,
                        "attribute": "bed_count",
                        "values": {LIVE: actual, REF: expected},
                        "reason": f"live bed count ({actual}) != UNITS.BED_COUNT ({expected})",
                    }
                )

        # (3) on-duty staff whose live location is outside rostered department
        for eid, ent in self.entities.items():
            if ent["kind"] != "staff":
                continue
            status_slot = (ent["attrs"].get("status") or {}).get(LIVE)
            if not status_slot or str(status_slot["value"]).lower() != "on_duty":
                continue
            dept_slot = (ent["attrs"].get("DEPARTMENT") or {}).get(REF)
            if not dept_slot:
                continue
            department = str(dept_slot["value"])
            zone_slot = (ent["attrs"].get("zone") or {}).get(LIVE)
            loc_slot = (ent["attrs"].get("location") or {}).get(LIVE)
            zone = str(zone_slot["value"]) if zone_slot else None
            location = str(loc_slot["value"]) if loc_slot else None
            in_dept = False
            if zone and zone == department:
                in_dept = True
            elif location and (
                location == department
                or location.startswith(department + "-")
                or location.startswith(department + " ")
            ):
                in_dept = True
            if not in_dept:
                conflicts.append(
                    {
                        "entity": eid,
                        "attribute": "location",
                        "values": {LIVE: location or zone, REF: department},
                        "reason": "on-duty staff location is outside rostered department",
                    }
                )

        return conflicts

    def context(self, entity_ids) -> str:
        lines: list[str] = []
        wanted = set(entity_ids)
        for eid in entity_ids:
            ent = self.entities.get(eid)
            if not ent:
                lines.append(f"{eid}: (missing)")
                continue
            lines.append(f"{eid} ({ent['kind']})")
            for attr, sources in sorted(ent["attrs"].items()):
                parts = []
                for src, slot in sources.items():
                    parts.append(f"{src}={slot['value']!r}@{slot['as_of']}")
                lines.append(f"  {attr}: " + "; ".join(parts))

        for rel in self.relations:
            if rel["subject"] in wanted or rel["object"] in wanted:
                lines.append(
                    f"  REL {rel['subject']} -{rel['relation']}-> {rel['object']} "
                    f"[{rel['source']} @{rel['as_of']}]"
                )
        return "\n".join(lines)

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "entities": self.entities,
            "relations": self.relations,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)

    def entity_counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = Counter()
        for ent in self.entities.values():
            counts[ent["kind"]] += 1
        return dict(counts)


def build_and_save():
    live = live_snapshot()
    ref = reference_data()

    os.makedirs("logs", exist_ok=True)
    with open("logs/test_snapshot.json", "w", encoding="utf-8") as f:
        json.dump({"live": live, "reference": ref}, f, indent=2, default=str)

    wm = WorldModel()
    wm.reset_diff()
    wm.ingest_live(live)
    wm.reset_diff()
    wm.ingest_reference(ref)

    counts = wm.entity_counts_by_kind()
    conflicts = wm.find_conflicts()

    print("entity counts by kind:", counts)
    print("relation count:", len(wm.relations))
    print("conflicts:", len(conflicts))
    print("first 5 conflicts:")
    for c in conflicts[:5]:
        print(" ", c)

    wm.save("logs/world_model_snapshot.json")
    return wm


if __name__ == "__main__":
    build_and_save()
