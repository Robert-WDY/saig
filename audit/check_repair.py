"""Additional invariants identified while manually checking the repaired application's transcripts."""
import json
from pathlib import Path
import sys

def check(directory):
    read=lambda name:json.loads((directory/name).read_text(encoding="utf8"))
    tests={r["case"]:r for r in read("eval_agent.json")}
    first=tests["新建"]["result"]["days"].get("1",{}).get("contract",{})
    binding={"origin":first.get("origin"),"start":first.get("start"),"end":first.get("end"),"must":first.get("must",[])}
    rows=[{"id":"residence_and_required_visit","actual":binding,
           "passed":binding["origin"]=="江汉路" and (binding["start"],binding["end"])==(540,780) and "智民里" in binding["must"]}]
    recall=tests["指代"]["result"]
    refs=[ref for t in recall["trace"] if t.get("step")=="session_read" for ref in t["records"]]
    unchanged=recall["facts"]==tests["关系"]["result"]["facts"]
    rows.append({"id":"relationship_read_uses_storage","actual":{"refs":refs,"source_facts_unchanged":unchanged},
                 "passed":bool(refs) and unchanged and not recall["citations"]})
    feedback={r["id"]:r for r in read("audit_dissatisfaction.json")}
    meal=feedback["delegated_choice"]["result"]["days"]["1"]
    proof=meal.get("replacement_evidence",[])
    rows.append({"id":"breakfast_replacement_cites_its_own_activity","actual":proof,
        "passed":any(p["place"]==meal["order"][1] and any(term in p["quote"] for term in ("过早","早餐","早点","早饭"))
        and p["source_id"] for p in proof)})
    state={r["id"]:r for r in read("audit_visitors.json")}
    combined=state["compound"]["result"]
    wrong=[t for t in combined["trace"] if t.get("tool") not in (None,"guide","saig")]
    rows.append({"id":"infeasible_edit_plus_independent_event_question","actual":{"wrong_tools":wrong,"answer":combined["answer"]},
        "passed":not wrong and state["compound"]["passed"]})
    (directory/"repair_checks.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
    return all(r["passed"] for r in rows)
if __name__=="__main__":
    sys.exit(not check(Path(sys.argv[1])))
