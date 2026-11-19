"""Exercise real orchestration and independently check the outputs at the HTTP boundary."""
import json
from pathlib import Path
from uuid import uuid4
import sys
import requests
from visitor_dialogues import send,write

def chat(session,sid,question):
    req={"session":sid,"query":question,"request_id":uuid4().hex,"diagnostics":True}
    turn=send(session,"http://127.0.0.1:18943",req)
    return {"request":req,**turn}

def run(folder,case):
    folder.mkdir(parents=True,exist_ok=True)
    sid="delivery-"+uuid4().hex
    session=requests.Session()
    session.trust_env=False
    questions={"alternatives":"给我一个武汉一日游的行程，再给我一个两日游的形成，比较一下两个行程有什么不同。",
               "partial":"我和同事分别要一套行程。我想用一天逛武汉；同事只有上午九点到九点十分这十分钟，却必须在湖北省博物馆参观九十分钟。请分别排一天，并比较两套安排。另外，江岸数命社区在哪个街区？",
               "scopes":"周日我们想在两种武汉玩法里挑一个，两套都上午十点出发。第一套只逛黄鹤楼；第二套只逛黎黄陂路和江汉关。帮我各排一份，比较一下景点。"}
    path=folder/(case+".json")
    first=chat(session,sid,questions[case])
    archive={"first":first};write(path,archive)
    result=first["result"];rows=result.get("deliverables",[])
    plans=[r for r in rows if r["kind"]=="plan"]
    comps=[r for r in rows if r["kind"]=="compare"]
    ok=[r for r in plans if r["status"]=="passed"]
    checks={"two_plans":len(plans)==2,"comparison_dependencies":len(comps)==1 and set(comps[0]["inputs"])=={r["id"] for r in plans},
            "no_unrequested_adoption":result.get("days")=={}}
    if case=="alternatives":
        checks["exact_days"]=sorted(len(r["cards"]) for r in ok)==[1,2]
        checks["comparison_verified"]=bool(comps and comps[0]["status"]=="passed" and len(ok)==2 and all(
            comps[0]["metrics"][r["id"]]["stops"]==sum(len(c["audit"]["stops"]) for c in r["cards"].values())
            and comps[0]["metrics"][r["id"]]["transfer_min"]==sum(sum(s["leg"] for s in c["audit"]["stops"])+c["audit"]["last_leg"] for c in r["cards"].values())
            for r in ok))
        if checks["exact_days"]:
            repeat=send(session,"http://127.0.0.1:18943",first["request"])
            checks["idempotent"]=repeat["result"].get("deliverables")==rows
            adopt=chat(session,sid,"那就用刚才的两日游，定为我的正式行程。")
            archive["adopt"]=adopt
            checks["adopts_displayed_cards"]=adopt["result"].get("days")==next(r["cards"] for r in ok if len(r["cards"])==2)
    elif case=="scopes":
        sets=[set(r["cards"]["1"]["order"]) for r in ok]
        checks.update(common_start=len(ok)==2 and all(len(r["cards"])==1 and r["cards"]["1"]["contract"]["start"]==600 for r in ok),
                      branch_constraints={"黄鹤楼"} in sets and {"黎黄陂路","江汉关"} in sets,
                      no_overlap=bool(comps and comps[0]["status"]=="passed" and "没有重复景点" in comps[0]["answer"]))
    else:
        infos=[r for r in rows if r["kind"]=="info"]
        checks.update(feasible_delivered=len(ok)==1,infeasible_reported=any(r["status"]=="failed" for r in plans),
                      incomplete_comparison_blocked=bool(comps and comps[0]["status"]=="blocked"),
                      independent_answer=any(r["status"]=="passed" and "智民里" in r["answer"] and r.get("citations") for r in infos))
    archive["checks"]=checks;write(path,archive)
    print(case,checks,[(r["kind"],r["status"],r["answer"][:80]) for r in rows],flush=True)
    if not all(checks.values()):raise SystemExit(1)

if __name__=="__main__":run(Path(sys.argv[1]),sys.argv[2])
