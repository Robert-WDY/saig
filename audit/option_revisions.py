"""Live conversations and independent checks for scoped itinerary revisions."""
from pathlib import Path
from uuid import uuid4
import sys

import requests
from task_delivery import chat
from visitor_dialogues import write

CASES={
    "departure": [
        "第一次来武汉，帮我出个一日游，再出个两日游，对比下怎么玩。",
        "两日游第二天想轻松点，下午四点要到汉口站，一日游不动，再帮我比较一下。",
        "还是只改两日游那天，车改签了，下午三点半就得赶到汉口站。帮我再更新下对比。",
    ],
    "separate": [
        "给我两套备选。一日游上午十点开始，只逛黄鹤楼。两日游每天上午九点开始，第一天要去黎黄陂路，第二天一定要去湖北省博物馆。帮我比较一下。",
        "我再说准确点，一日游改成上午十一点出发。两日游只把第二天改成十点出发，还是得去省博，第一天照原计划。两套再对比下。",
    ],
    "same_length": [
        "只有一天，想在汉口和武昌里二选一。汉口那份只安排黎黄陂路和江汉关，武昌那份只安排黄鹤楼和户部巷，都十点开始。各给我一份。",
        "我妈说武昌那条别排户部巷了，换成昙华林，黄鹤楼还是要去。汉口那份照旧。现在两条怎么选，景点上差在哪？",
        "我们就用刚才改过的武昌那条。",
    ],
    "infeasible": [
        "周末可能只玩一天，也可能玩两天，武汉都帮我排一套吧。",
        "试试看让两日游第二天九点出发，九点十分结束，但湖北省博物馆还要待九十分钟。我先看看，顺便跟一日游比比。",
        "那还是用原来的一日游，直接定下来吧。",
    ],
    "preview": [
        "我还没定在武汉待多久，先给我两天版和三天版各一份。",
        "想看看三天版的最后一天如果只去武汉大学会怎样，先试排，不要替换原版。跟两天版比一下。",
        "还是把三天版的原版定为正式行程，刚才的试排不用了。",
    ],
}

def passed(turn,kind):
    return [row for row in turn["result"].get("deliverables",[]) if row["kind"]==kind and row["status"]=="passed"]

def compared(turn,revision,untouched,old_reference=None):
    rows=passed(turn,"compare")
    assert len(rows)==1
    row=rows[0]
    sources={(v["option_id"],v["version"]) for v in row["versions"]}
    expected={(p["option_id"],p["version"]) for p in [revision,untouched]}
    if old_reference:
        expected.add((old_reference["option_id"],old_reference["version"]))
    assert sources==expected,(sources,expected)
    for opt in (revision,untouched):
        ref=next(v["input"] for v in row["versions"] if v["option_id"]==opt["option_id"] and v["version"]==opt["version"])
        cards=opt["cards"]
        m=row["metrics"][ref]
        assert m["daily_stops"]==[len(c["order"]) for c in cards.values()]
        assert m["transfer_min"]==sum(sum(s["leg"] for s in c["audit"]["stops"])+c["audit"]["last_leg"] for c in cards.values())
        assert m["arrivals"]==[{"day":n,"destination":c["contract"]["destination"],"arrival":c["audit"]["arrival"],
                               "deadline":c["contract"]["end"]-c["contract"]["buffer"]}
                              for n,c in cards.items() if c["contract"]["destination"]]

def revision(before,after,*days):
    assert after["option_id"]==before["option_id"] and after["version"]==before["version"]+1
    assert set(after["replanned_days"])==set(days)
    assert set(after["cards"])==set(before["cards"])
    touched={str(d) for d in days}
    assert all(after["cards"][d]==before["cards"][d] for d in before["cards"] if d not in touched)
    actual={str(s["day"]) for s in after["execution"] if s.get("step")=="admitted"}
    assert actual==touched,(actual,touched)

def verify(case,turns):
    assert all(t["http"]==200 for t in turns)
    a,b,*later=turns
    base=passed(a,"plan")
    assert len(base)==2
    if case=="same_length":
        west=next(p for p in base if "黄鹤楼" in p["cards"]["1"]["order"])
        other=next(p for p in base if p!=west)
        assert set(other["cards"]["1"]["order"])=={"黎黄陂路","江汉关"}
        assert set(west["cards"]["1"]["order"])=={"户部巷","黄鹤楼"}
        changed,=passed(b,"revise")
        revision(west,changed,1)
        assert set(changed["cards"]["1"]["order"])=={"昙华林","黄鹤楼"}
        assert changed["cards"]["1"]["contract"]["start"]==600
        compared(b,changed,other)
        assert later[0]["result"]["days"]==changed["cards"]
        return
    if case=="preview":
        two,three=sorted(base,key=lambda p:len(p["cards"]))
        assert len(two["cards"])==2 and len(three["cards"])==3
        trial,=passed(b,"revise")
        assert trial["preview"] and trial["option_id"]!=three["option_id"]
        assert trial["replanned_days"]==[3] and trial["cards"]["3"]["order"]==["武汉大学"]
        assert all(trial["cards"][n]==three["cards"][n] for n in ("1","2"))
        compared(b,trial,two)
        assert later[0]["result"]["days"]==three["cards"]
        return
    one,two=sorted(base,key=lambda p:len(p["cards"]))
    assert len(one["cards"])==1 and len(two["cards"])==2
    if case=="departure":
        for turn,deadline in zip(turns[1:],(960,930)):
            changed,=passed(turn,"revise")
            revision(two,changed,2)
            day=changed["cards"]["2"]
            assert day["contract"]["destination"]=="汉口站" and day["contract"]["end"]==deadline
            assert day["audit"]["arrival"]+day["contract"]["buffer"]<=deadline
            assert 1<=len(day["order"])<=3
            compared(turn,changed,one)
            two=changed
    elif case=="separate":
        assert one["cards"]["1"]["contract"]["start"]==600 and one["cards"]["1"]["order"]==["黄鹤楼"]
        assert all(c["contract"]["start"]==540 for c in two["cards"].values())
        assert "黎黄陂路" in two["cards"]["1"]["order"] and "湖北省博物馆" in two["cards"]["2"]["order"]
        changed_one,changed_two=sorted(passed(b,"revise"),key=lambda p:len(p["cards"]))
        revision(one,changed_one,1)
        revision(two,changed_two,2)
        assert changed_one["cards"]["1"]["contract"]["start"]==660 and changed_one["cards"]["1"]["order"]==["黄鹤楼"]
        assert changed_two["cards"]["2"]["contract"]["start"]==600 and "湖北省博物馆" in changed_two["cards"]["2"]["order"]
        compared(b,changed_one,changed_two)
    else:
        status={r["kind"]:r["status"] for r in b["result"]["deliverables"]}
        assert status=={"revise":"failed","compare":"blocked"},status
        failure=next(r for r in b["result"]["deliverables"] if r["kind"]=="revise")
        contract=next(s["constraints"] for s in failure["execution"] if s.get("step")=="frozen_day")
        assert contract["start"]==540 and contract["end"]==550
        assert contract["durations"]["湖北省博物馆"]==90 and "湖北省博物馆" in contract["must"]
        assert any(s.get("audit_error") for s in failure["execution"])
        assert b["result"]["days"]=={}
        assert later[0]["result"]["days"]==one["cards"]

def run(root,case):
    root.mkdir(parents=True,exist_ok=True)
    turns=[]
    stats=[]
    sid="option-audit-"+uuid4().hex
    with requests.Session() as session:
        session.trust_env=False
        for question in CASES[case]:
            turn=chat(session,sid,question)
            turns.append(turn)
            calls=[e for e in turn["result"].get("events",[]) if e["stage"]=="model_http"]
            stats.append({"calls":len(calls),"retries":sum(e["attempt"]>1 for e in calls),"seconds":turn["wall_s"]})
            write(root/(case+".json"),{"turns":turns,"model_stats":stats})
    verify(case,turns)
    write(root/(case+".json"),{"turns":turns,"model_stats":stats,"passed":True})
    print(case,stats)

if __name__=="__main__":
    run(Path(sys.argv[1]),sys.argv[2])
