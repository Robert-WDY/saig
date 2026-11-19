"""Score the fixed visitor conversations against state, provider and published-source evidence."""
from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from knowledge import Knowledge

def load(path):
    return json.loads(path.read_text("utf8"))

def valid_card(card):
    c,a=card["contract"],card["audit"]
    stops=a["stops"]
    cursor=c["start"]
    for stop in stops:
        if stop["start"]<cursor+stop["leg"] or stop["end"]<=stop["start"]:
            return False
        cursor=stop["end"]
    return (card["order"]==[s["place"] for s in stops] and len(set(card["order"]))==len(stops)
            and set(c["must"])<=set(card["order"]) and not set(c["exclude"]).intersection(card["order"])
            and len(stops)<=c["max_stops"] and a["arrival"]==cursor+a["last_leg"]
            and a["arrival"]+c["buffer"]<=min(c["end"],c["start"]+c["max_minutes"]))

def has(answer,*items):
    return all(s in answer for s in items)

def person(r,name):
    facts={(f["subject"],f["relation"],f["object"]) for f in r["facts"]}
    return ({("self","name","林川"),("self.mother","name",name),("self.mother","likes","老建筑")}<=facts
            and len([f for f in facts if f[:2]==("self.mother","name")])==1)

def cases(case,turns,provider):
    for i,t in enumerate(turns):
        r=t["result"]
        days=r.get("days",{})
        prior=turns[i-1]["result"]["days"] if i else {}
        first=turns[0]["result"]["days"]
        answer=r.get("answer","")
        refs={c["id"] for c in r.get("citations",[])}
        preview=r.get("preview") or {}
        card=days.get("1",{})
        if case=="metro":
            if i==0:
                legs=card.get("audit",{}).get("legs",[])
                matches=[row for row in provider["strategies"]["0"] if row["all_metro"] and legs and
                         legs[0].get("minutes")==ceil(row["seconds"]/60) and legs[0].get("walk_m")==row["walk_m"]
                         and legs[0].get("group_fare")==2*float(row["ticket"]) and
                         all(line["from"] in answer and line["to"] in answer for line in row["lines"])]
                c=card.get("contract",{})
                yield {"起终点和时限":c.get("origin")=="黄鹤楼" and c.get("end")==705 and c.get("start")==540 and card.get("order")==["湖北省博物馆"],
                       "真实地铁、两人费用、换乘与步行":bool(matches and legs[0]["mode"]=="metro" and str(legs[0]["walk_m"]) in answer and provider["date"] in legs[0]["source"])}
            elif i==1:
                yield {"原卡保留":bool(first) and days==first and first.get("1",{}).get("contract",{}).get("origin")=="黄鹤楼" and first["1"]["order"]==["湖北省博物馆"],"500米方案未获证实":not preview and "500" in answer and any(v in answer for v in ("缺少","无法","未找到"))}
            else:
                yield {"读取原卡":bool(first) and days==first,"换乘和到达均回答":has(answer,"徐家棚","10:08")}
        elif case=="community":
            if i==0:
                yield {"正确会场及定位证据":"智民里" in answer and bool(refs & {"venue","community.3.1","community.10.1"}) and not any(n in answer for n in ("新建社区","新荣社区")),
                       "真实订单带教":"订单" in answer and any(x in answer for x in ("带领","带教","带学","实战")) and "community.7.1" in refs}
            elif i==1:
                yield {"两处及合计面积":has(answer,"智民里","光谷创新天地","8000") and any(x in answer for x in ("合计","合起来","总面积")) and "community.3.1" in refs}
            else:
                # The visitor explicitly requests separate answers; a blanket restatement is incomplete.
                clauses=[s for s in answer.replace("？","。").replace("；","。").replace("\n","。").split("。") if s]
                def addressed(words):
                    return any(any(w in s for w in words) and any(w in s for w in ("不详","不足以确认","无法确认","不能保证","无法保证","没有","未提供","未公布","未说明","暂无","无法核实","查不到")) and "你要求的条件" not in s and "说清楚" not in s for s in clauses)
                yield {"晚间免费入场单独说明":addressed(("入场","开放","免费","进场")),"值班资料单独说明":addressed(("值班","前台","排班"))}
        elif case=="family_event":
            if i==0:
                yield {"人物关系":person(r,"晓岚"),"赛事四项":has(answer,"介绍武汉","社区","旅游","SAIG") and "challenge" in refs}
            elif i==1:
                yield {"两人姓名":has(answer,"林川","晓岚"),"视频必交":has(answer,"视频","主页") and "register" in refs and any(x in answer for x in ("必","仍需","需要","不能替代","还要"))}
            elif i==2:
                yield {"更正名字保留喜好":person(r,"晓兰"),"答报名费用":has(answer,"免费") and "register" in refs}
            else:
                yield {"正确姓名和喜好":has(answer,"晓兰","老建筑") and "晓岚" not in answer,"仅查看且绑定正确":r["facts"]==turns[i-1]["result"]["facts"] and person(r,"晓兰")}
        elif case=="edit":
            def spec(mapping,second):
                return (set(mapping)=={"1","2"} and all(mapping[k]["contract"]["origin"]==a and mapping[k]["contract"]["start"]==b
                      and c in mapping[k]["order"] and mapping[k]["contract"]["max_stops"]<=2
                      for k,a,b,c in [("1","江汉路",540,"黎黄陂路"),("2","户部巷",second,"黄鹤楼")]))
            if i==0: yield {"两天原始约束":spec(days,540)}
            if i==1: yield {"正式卡不动":bool(first) and first==days,"备选只改第二天":spec(preview,600) and preview["1"]==first.get("1") and preview["2"]["order"]==first.get("2",{}).get("order")}
            if i==2: yield {"完整采纳备选":bool(days) and days==turns[1]["result"]["preview"] and spec(days,600)}
            if i==3:
                second=days.get("2",{})
                c=second.get("contract",{})
                yield {"保留第一天及第二天游览":spec(days,600) and days["1"]==first.get("1"),
                       "赶车与缓冲":c.get("destination")=="汉口站" and c.get("end")==960 and c.get("buffer")==40 and second["audit"]["arrival"]<=920 and "汉口站" in answer}

def evaluate(directory,refs,provider):
    manifest=load(directory/"manifest.json")
    expected={f"{case}-{n}.json" for case in manifest["inputs"] for n in range(1,manifest["repeats"]+1)}
    if {p.name for p in directory.glob("*-[0-9].json")}!=expected:
        raise ValueError("Missing or unexpected visitor sessions")
    scored=[]
    replies=[]
    stats={}
    chains={}
    verdicts={}
    for path in sorted(directory.glob("*-[0-9].json")):
        a=load(path); turns=a["turns"]; case=a["case"]
        if [t["request"]["query"] for t in turns]!=manifest["inputs"][case] or "replay" not in a:
            raise ValueError(f"Incomplete conversation: {path.name}")
        checks=list(cases(case,turns,provider))
        assert len(checks)==len(turns)
        flags=[]
        for i,(t,criteria) in enumerate(zip(turns,checks)):
            r=t["result"]; cites=r.get("citations",[])
            criteria["引用可回查"]=all(c["id"] in refs and c["quote"] and c["quote"] in refs[c["id"]]["text"] and c["source"]==refs[c["id"]]["source"] and c["locator"]==refs[c["id"]]["locator"] and c["claim"] in r["answer"] for c in cites)
            criteria["卡片时间算术"]=all(valid_card(c) for cards in (r.get("days") or {},r.get("preview") or {}) for c in cards.values())
            passed=all(criteria.values()) and t.get("http")==200
            flags.append(passed)
            verdicts.setdefault((case,i),[]).append(passed)
            scored.append({"case":case,"attempt":a["attempt"],"turn":i+1,"passed":passed,"checks":criteria,"wall_s":t["wall_s"],"http":t["http"],"model_calls":sum(e["stage"]=="model" for e in r.get("events",[])),"quotes":len(cites)})
        chains.setdefault(case,[]).append(all(flags))
        orig=turns[-1]["result"]; replay=a["replay"]["result"]
        replies.append({"archive":path.name,"same":{k:v for k,v in orig.items() if k!="events"}=={k:v for k,v in replay.items() if k!="events"} and a["replay"]["http"]==200,"wall_s":a["replay"]["wall_s"]})
    for case in ["all",*chains]:
        items=[r for r in scored if case=="all" or r["case"]==case]
        times=sorted(r["wall_s"] for r in items)
        stats[case]={"turns":len(items),"passed":sum(v["passed"] for v in items),"http200":sum(v["http"]==200 for v in items),"median_s":round(median(times),2),"p95_s":times[ceil(.95*len(times))-1],"max_s":max(times),"calls_median":median(v["model_calls"] for v in items)}
    return {"stats":stats,"chains":chains,"unstable":[f"{k[0]}/{k[1]+1}" for k,v in verdicts.items() if len(set(v))>1],"turns":scored,"replay":replies}

if __name__=="__main__":
    directory=Path(sys.argv[1]); out=directory/"score.json"
    provider=load(directory/"provider.json" if (directory/"provider.json").exists() else directory.parent/"provider.json")
    report=evaluate(directory,Knowledge().by_id,provider)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf8")
    print(report["stats"],report["unstable"],report["chains"])
