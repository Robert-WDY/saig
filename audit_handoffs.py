"""Replay observed HTTP results without running the production compiler or scheduler."""
import argparse
from copy import deepcopy
from datetime import time
import json
from pathlib import Path
from audit_visitors import fixture, public_card

def minute(v):
    if isinstance(v,int):
        return v
    t=time.fromisoformat(v)
    return t.hour*60+t.minute

def contract_from(previous,op):
    contract=deepcopy(previous)
    for key,value in op.get("set",{}).items():
        if key in ("start","end"):
            contract[key]=minute(value)
        elif key=="windows":
            contract[key].update({name:list(map(minute,bounds)) for name,bounds in value.items()})
        elif key=="durations":
            contract[key].update(value)
        else:
            contract[key]=value
    for field,remove,add in (("must","unrequire","require"),("exclude","allow","exclude")):
        keep=[name for name in contract[field] if name not in op.get(remove,[])]
        contract[field]=list(dict.fromkeys(keep+op.get(add,[])))
    return contract

def check_cards(r):
    trace=r.get("trace",[])
    checks={}
    initial={"start":540,"end":1080,"origin":None,"destination":None,"buffer":0,"must":[],
             "exclude":[],"durations":{},"windows":{},"regions":[],"max_stops":12,"max_minutes":1440}
    for event in trace:
        if event.get("step")!="frozen_day":
            continue
        day=event["day"]
        ops=[op for step in trace for op in step.get("affected_days",[]) if str(op["day"])==day]
        frozen=event["constraints"]
        checks[day+"/patch_to_frozen"]=len(ops)==1 and contract_from(event["before"] or initial,ops[0])==frozen
        admitted=next((step for step in trace if step.get("day")==day and step.get("step")=="admitted"),None)
        if not admitted:
            checks[day+"/rejection_visible"]=r["mode"]=="clarify" and bool(r.get("answer"))
            continue
        hits={h for step in trace if step.get("tool")=="guide" and (step.get("day")==day or "replan" in step) for h in step["hits"]}
        checks[day+"/guide_to_execution"]=admitted["guide"] in hits
        checks[day+"/frozen_to_auditor"]=frozen==admitted["constraints"] and not admitted["audit"]["violations"]
        if r["mode"] not in ("edit","preview","plan"):
            continue  # Whole-request rollback can discard a successfully audited first day.
        card=(r["preview"] if r["mode"]=="preview" else r["days"])[day]
        checks[day+"/auditor_to_card"]=all(admitted[k]==card[k] for k in ("order","audit")) and frozen==card["contract"]
        checks[day+"/card_to_text"]=public_card(r)
    return checks

def detailed(rows):
    results=[]
    for row in rows:
        i=row["id"];r=row["result"];s=r.get("answer","")
        checks=check_cards(r)
        if i=="compound":
            errors=[t for t in r.get("trace",[]) if t.get("audit_error")]
            checks["conflict_demonstrated"]=bool(errors) and any(t.get("step")=="frozen_day" and
                (t["constraints"]["start"],t["constraints"]["end"])==(1018,1020) for t in r["trace"])
        if i=="ambiguous":
            checks["asks_which_original_stop"]=r.get("mode")=="clarify" and ("哪" in s or "具体" in s) and any(n in s for n in fixture()["days"]["1"]["order"])
        if i=="j-feedback":
            checks["dissatisfaction_preserves_order"]=bool(r.get("days",{})) and any(t.get("step")=="frozen_day" and
                [n for n in t["prior_stops"] if n in r["days"]["1"]["order"]]==r["days"]["1"]["order"] for t in r.get("trace",[]))
        results.append({"id":i,"applicable":checks,"original_assertions":row["passed"],"accepted":row["passed"] and all(checks.values())})
    return results

def run(path,out):
    rows=json.loads(path.read_text(encoding="utf8"))
    assert len(rows)==19, "Incomplete visitor run"
    captured=detailed(rows)
    response=next((r["result"] for r in rows if any(t.get("step")=="admitted" for t in r["result"].get("trace",[]))
                   and r["result"].get("mode") in ("edit","plan","preview")),None)
    mutations={}
    if response:
        for name in ("frozen_to_auditor","auditor_to_card","guide_to_execution"):
            x=deepcopy(response)
            step=next(t for t in x["trace"] if t.get("step")=="admitted")
            if name=="frozen_to_auditor": step["constraints"]["buffer"]+=1
            elif name=="auditor_to_card": step["audit"]["arrival"]+=1
            else: step["guide"]="unretrieved-source"
            mutations[name]=check_cards(x).get(step["day"]+"/"+name) is False
    out.write_text(json.dumps({"data":path.name,"rows":captured,"deliberate_corruptions_rejected":mutations},ensure_ascii=False,indent=2),encoding="utf8")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("path",type=Path);parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args();run(args.path,args.out)
