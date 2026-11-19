"""Stricter review for generalization probes and whole journeys. Keep the first score for comparison."""
from pathlib import Path
import argparse,json

def evaluate(archive):
    def read(name):
        return json.loads((archive/name).read_text(encoding="utf8"))
    transfers={r["id"]:r for r in read("audit_transfer.json")}
    result={}
    for key,r in transfers.items():
        a=r["actual"] if isinstance(r["actual"],dict) else {}
        checks={"original":r["passed"]}
        if key=="preserve_origin":
            ops=a.get("days",[])
            checks["no_new_endpoint_or_persistent_ban"]=bool(ops) and all(
                not op.get("exclude") and set(op.get("set",{}))<={"origin","max_stops"} for op in ops)
        if key=="unknown_station":
            explanation=a.get("question","")+" ".join(a.get("unsupported",[]))
            checks["explains_actual_data_limit"]="武汉站" in explanation and any(w in explanation for w in ("核实","目录","未收录","无法","不能","缺少"))
        if key=="recall_without_write":
            checks["lookup_uses_session_only"]=not a.get("tools")
        result[key]={"original":r["passed"],"checks":checks,"accepted":all(checks.values())}
    visitor=read("audit_handoffs.json")
    v={r["id"]:r["accepted"] for r in visitor["rows"]}
    business={name:{"turns":ids,"passed":all(results[k] for k in ids)} for name,ids,results in [
        ("四项服务与再改线",["j-city","j-plan","j-community","j-event","j-feedback"],v),
        ("预览确认恢复",["preview","accept","restore"],v),
        ("亲子投诉再澄清",["family_start","family_vague","family_resolve"],{k:r["accepted"] for k,r in result.items()})]}
    extras={r["id"]:r for r in read("audit_dissatisfaction.json")}
    extra={k:r["passed"] for k,r in extras.items()}
    for name,ids in [("质疑知识回答要求出处",["first","challenge"]),("矛盾反馈和撤回",["conflict","withdraw"])]:
        business[name]={"turns":ids,"passed":all(extra[k] for k in ids)}
    from knowledge import Knowledge
    from planning import evaluate
    meal=extras["delegated_choice"]["result"].get("days",{}).get("1",{})
    quality={}
    if meal:
        other=["江汉路","山海关路","智民里"]
        guide=Knowledge().by_id["book.167.1"]["text"]
        alternative=evaluate(meal["contract"],other)
        minutes=lambda audit:sum(s["leg"] for s in audit["stops"])+audit["last_leg"]
        quality={"delivered":meal["order"],"delivered_travel":minutes(meal["audit"]),
                 "comparison":other,"comparison_travel":minutes(alternative),
                 "same_contract_violations":alternative["violations"],"source":"book.167.1",
                 "breakfast_evidence":"山海关路以地道早餐和市井小吃闻名" in guide}
    report={"transfer":result,"journeys":business,"delegated_breakfast_quality":quality}
    (archive/"review.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("archive",type=Path)
    evaluate(p.parse_args().archive)
