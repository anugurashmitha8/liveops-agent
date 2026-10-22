from agents import verify_claims
from world_model import LIVE, WorldModel


def _wm():
    wm = WorldModel()
    wm.upsert("bed", "4E-410A", {"status": "dirty"}, LIVE, "2026-10-22T16:30:00Z")
    return wm


def test_critic_rejects_wrong_value_and_invented_entities():
    draft = {
        "cause": "x",
        "explanation": "Bed bed:4E-999Z is blocked.",
        "actions": [],
        "claims": [
            {"entity": "bed:4E-410A", "attribute": "status", "value": "available"},
            {"entity": "patient:P0", "attribute": "status", "value": "boarding"},
        ],
    }
    problems = verify_claims(_wm(), draft)
    assert any("not 'available'" in p for p in problems)
    assert any("patient:P0" in p for p in problems)
    assert any("bed:4E-999Z" in p for p in problems)


def test_critic_accepts_correct_claims():
    draft = {
        "cause": "Bed bed:4E-410A is dirty.",
        "explanation": "It needs cleaning.",
        "actions": [],
        "claims": [{"entity": "bed:4E-410A", "attribute": "status", "value": "dirty"}],
    }
    assert verify_claims(_wm(), draft) == []

def test_claim_that_attribute_is_unset_is_accepted():
    draft = {
        "cause": "c", "explanation": "e", "actions": [],
        "claims": [{"entity": "bed:4E-410A", "attribute": "patient_id", "value": None}],
    }
    assert verify_claims(_wm(), draft) == []

def test_claim_matching_monitor_evidence_is_accepted():
    evidence = [{"entity": "unit:ICU", "attribute": "live_status_counts",
                 "value": {"occupied": 11, "dirty": 1}}]
    draft = {"cause": "c", "explanation": "e", "actions": [],
             "claims": [{"entity": "unit:ICU", "attribute": "live_status_counts",
                         "value": {"occupied": 11}}]}
    assert verify_claims(WorldModel(), draft, None, evidence) == []