"""Run distinct visitor journeys against the real Agent or an already running HTTP API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from uuid import uuid4
import requests
from agent import Agent
from planning import evaluate
from trip_contract import GUIDES,settings

CASES={
    "source":["请以旅游手册的地铁三日游为底稿，给我排三天，保留每个地点所属的那一天。每天可以按时间取舍。",
              "第二天的江汉关只停留20分钟，其余安排照旧。"],
    "family":["两位成人游两天。第一天必须去户部巷和黄鹤楼；第二天外婆加入，三人一起去江汉路和江汉关，外婆的每段转场步行最多500米。"],
    "cars":["我们六人只坐普通出租车，从江汉路集合，到江汉关游览后去黎黄陂路。两段车都是每辆每段一口价30元，今天全团交通预算130元。",
            "其他安排不动，把今天全团交通预算压到90元。"],
    "train":["安排两天：第一天必须游江汉路；第二天从黄鹤楼出发，必须去户部巷。",
             "只改第二天，最后到汉口站赶下午四点的火车，进站提前四十分钟。第一天照旧。"]
}
def verify(case,turns):
    cards=turns[0]["days"]
    checks={"initial_route":turns[0]["mode"]=="plan" and bool(cards)}
    try:
        checks["shared_audit"]=all(evaluate(c["contract"],c["order"])==c["audit"] for c in cards.values())
        if case=="source":
            guide=next(g for g in GUIDES if g["id"]=="metro-three")
            checks["original_dates"]=set(cards)=={"1","2","3"} and all(c["template"]["id"]==guide["id"] and
                c["template"]["day"]==int(k) and set(c["order"])<=set(guide["days"][int(k)-1]) for k,c in cards.items())
            edit=turns[1]["days"]
            checks["edit_scope"]=edit["1"]==cards["1"] and edit["3"]==cards["3"] and edit["2"]["order"]==cards["2"]["order"] and edit["2"]["contract"]["durations"].get("江汉关")==20
        if case=="family":
            first,second=[settings(cards[k]["contract"]["mobility"]) for k in ("1","2")]
            checks["members_by_day"]=first["人数"]==2 and second["人数"]==3 and "单段步行上限米" not in first and second["单段步行上限米"]==500
            checks["bound_person"]=any(r["field"]=="单段步行上限米" and "外婆" in r["subject"] for r in cards["2"]["contract"]["mobility"]["rules"])
            legs=cards["2"]["audit"]["legs"]
            checks["walk_network"]=bool(legs) and {"江汉路","江汉关"}<=set(cards["2"]["order"]) and all(l["walk_m"] is not None and l["walk_m"]<=500 for l in legs)
        if case=="cars":
            c=cards["1"]
            legs=[l for l in c["audit"]["legs"] if l["origin"]!=l["destination"]]
            checks["capacity_cost"]=len(legs)==2 and {"黎黄陂路","江汉关"}<=set(c["order"]) and all(l["mode"]=="taxi" and l["cars"]==2 and l["fare_bound"]==60 for l in legs) and c["audit"]["group_fare_bound"]==120
            checks["budget_atomic"]=turns[1]["mode"]=="clarify" and turns[1]["days"]==cards and "预算" in turns[1]["answer"]
        if case=="train":
            edited=turns[1]["days"]; c=edited["2"]
            checks["deadline"]=c["contract"]["destination"]=="汉口站" and c["contract"]["buffer"]==40 and c["contract"]["end"]==960 and c["audit"]["arrival"]+40<=960
            checks["local_edit"]=cards["1"]==edited["1"] and "户部巷" in c["order"] and c["audit"]["legs"][-1]["destination"]=="汉口站"
    except (KeyError,IndexError,TypeError,ValueError) as exc:checks["complete_business_chain"]=False
    return checks

def run(case,out,base):
    with tempfile.TemporaryDirectory() as tmp:
        agent=None if base else Agent(str(Path(tmp)/"session.db"))
        sid="trip-verification-"+uuid4().hex
        turns=[]
        session=requests.Session(); session.trust_env=False
        for q in CASES[case]:
            if base:
                response=session.post(base+"/chat",json={"session":sid,"query":q},timeout=600)
                response.raise_for_status();result=response.json()
            else:result=agent.respond(sid,q)
            turns.append(result)
            (out/(case+".json")).write_text(json.dumps({"inputs":CASES[case],"turns":turns},ensure_ascii=False,indent=2),"utf8")
        checks=verify(case,turns)
        (out/(case+".json")).write_text(json.dumps({"inputs":CASES[case],"turns":turns,"checks":checks},ensure_ascii=False,indent=2),"utf8")
        print(case,checks,flush=True)
        return all(checks.values())

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True);p.add_argument("--base");p.add_argument("--cases",nargs="+",choices=CASES,default=list(CASES))
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda c:run(c,args.out,args.base),args.cases))
    raise SystemExit(not all(results))

