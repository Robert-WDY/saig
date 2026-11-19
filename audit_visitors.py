"""Fresh HTTP journeys and independent branches off a hand-written accepted itinerary.
Run twice with different --out paths to preserve observations before and after repair."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
from http.server import ThreadingHTTPServer
import requests
from agent import Agent
from serve import handler

ROOT=Path(__file__).resolve().parent
# Frozen input: a prior saved plan. Hand-calculated times, independent of the scheduler.
def fixture():
    contracts={"start":540,"end":1020,"origin":None,"destination":None,"buffer":0,"must":[],
               "exclude":[],"durations":{},"windows":{},"regions":[],"max_stops":12,"max_minutes":1440}
    days={}
    for key,places,times,durations,required in [
        ("1",["江汉路","黎黄陂路","智民里"],[540,605,665],[40,35,40],"智民里"),
        ("2",["户部巷","昙华林"],[540,600],[35,45],"昙华林")]:
        stops=[{"place":n,"leg":0 if i==0 else 25,"start":t,"end":t+d}
               for i,(n,t,d) in enumerate(zip(places,times,durations))]
        days[key]={"order":places,"contract":{**deepcopy(contracts),"origin":places[0],"must":[required]},
                   "audit":{"stops":stops,"arrival":stops[-1]["end"],"last_leg":0,"buffer":0,"violations":[]},
                   "guide":"oldtown" if key=="1" else "book.200.1","diff":{"added":[],"retimed":[],"removed":[]}}
    return {"days":days,"facts":[],"turns":[]}

def terms(s,*words):
    return any(w in s for w in words)

# Expected facts or protected state are declared before running against the model.
CASES=[
 ("cap","我妈觉得你第一天排得太满，不满意。最多两站，智民里照去，第二天别动。",
  "收紧单日容量；仅删一个可选点", "edit", {"max_stops":2}),
 ("swap","第一天第二站我不喜欢。把它换成吉庆街，别的站按原来的顺序。",
  "序号引用与原位替换","edit",{}),
 ("stay","第二天在昙华林想多看看，那里留足九十分钟，其他地方别重新排。",
  "单个地点停留时长与时刻传播","edit",{"durations":{"昙华林":90}}),
 ("drop","第一天智民里这次不想去了，原来我说的必去取消，行程里也删掉。",
  "撤销持续约束并从卡片删除","edit",{"must":[]}),
 ("ban","第一天不逛江汉路了，以后每次改这一天也别再把江汉路列为游览站。住处还是那里。",
  "同一地点的出发点与游览对象身份不同","edit",{"exclude":["江汉路"]}),
 ("arrival","第一天下午三点前我要到汉口站接人，接人而已，不是坐车。游完智民里再过去。",
  "到站接人与发车截止的余量不同","edit",{"end":900,"buffer":0,"destination":"汉口站"}),
 ("vague","这个安排我不太满意。","反馈未指出原因，应追问并保留已确认版本","clarify",{}),
 ("ambiguous","第一天那个老建筑我不想看了，把它换掉。","多对象歧义不能任选一站","clarify",{}),
 ("access","第二天全程必须保证轮椅能过，一级台阶也不能有。能保证我才按这个走。",
  "无法验证的硬约束需显式处理","clarify",{}),
 ("compound","第一天改成十六点五十八分出发，十七点要结束，仍得逛智民里。另外，我个人报名 SAIG 必须交什么？",
  "排程无解时仍完成独立的赛事咨询","clarify",{}),
 ("preview","第一天假如十一点才出门会怎样？我先看看，别替我改。","临时副本与原卡隔离","preview",{"start":660}),
 ("accept","就按刚才预览的那个走，帮我定下来。","接受刚才展示的准确版本","edit",{"start":660}),
 ("restore","还是最初那版合适，撤销刚才确认的改动。","恢复已确认历史版本","edit",{}),
 ("coords","手机上搜不到汉口站。给我这个火车站的经纬度，说明坐标系。","有坐标的地点工具结果须传给用户","info",{}),
]
JOURNEY=[
 ("j-city","第一次来武汉，我住江汉路。武汉三镇是怎么回事，江汉路在哪一边？"),
 ("j-plan","周末我只玩一天，从江汉路出发。上午九点到下午四点，智民里是我这趟一定要去的地方。排一条能走的路线。"),
 ("j-community","路线上这个智民里跟数命社区是什么关系？零基础去那儿能学什么？"),
 ("j-event","我一个人也想报名 SAIG。有了体验网址，还要往哪儿交什么材料？"),
 ("j-feedback","排得有点满，我只想留两站，智民里保留，其余你帮我取舍。"),
]
def sources_valid(r,agent):
    cites=r.get("citations",[])
    hits={i for tr in r["trace"] for i in tr.get("hits",[])}
    return bool(cites) and all(c["id"] in hits and c["id"] in agent.kb.by_id and c["quote"] and
            c["quote"] in agent.kb.by_id[c["id"]]["text"] and c["claim"] in r["answer"] for c in cites)

def public_card(r):
    """Read client-visible card: independently reconcile timing and text for modified days."""
    for trace in r["trace"]:
        for op in trace.get("affected_days",[]):
            k=str(op["day"])
            card=(r["preview"] if r["mode"]=="preview" else r["days"])[k]
            c=card["contract"]
            last=c["start"]
            for stop in card["audit"]["stops"]:
                if stop["start"]<last+stop["leg"] or stop["end"]<=stop["start"]:
                    return False
                slot="%02d:%02d–%02d:%02d %s"%(*divmod(stop["start"],60),*divmod(stop["end"],60),stop["place"])
                if slot not in r["answer"]:
                    return False
                last=stop["end"]
            if last+card["audit"]["last_leg"]!=card["audit"]["arrival"] or card["audit"]["arrival"]+c["buffer"]>c["end"]:
                return False
    return True

def check(i,r,before,mode,delta,agent,preview):
    checks={"mode":r["mode"]==mode}
    answer=r["answer"]; days=r["days"]
    key="2" if i in ("stay","access") else "1"
    if i=="coords":
        checks["coordinate_and_crs"]=all(x in answer for x in ("30.621","114.248","WGS84"))
        checks["untouched"]=days==before
    elif mode=="clarify":
        checks["unchanged"]=days==before
        if i in ("vague","ambiguous"):
            checks["actionable_question"]=terms(answer,"？","请","哪","想","希望") and not terms(answer,"字段","set.","unknown")
        elif i=="access":
            checks["explains_limit"]=terms(answer,"核实","无法确认","不能保证","无法保证") and terms(answer,"轮椅","台阶","无障碍")
        else:
            checks["independent_answer"]=all(x in answer for x in ("简介","视频")) and sources_valid(r,agent)
            checks["route_conflict"]=terms(answer,"冲突","超出","无法","不够")
    elif i=="preview":
        checks["unchanged"]=days==before
        checks["draft_only"]=bool(r.get("preview") and r["preview"][key]["contract"]["start"]==660 and r["preview"]["2"]==before["2"])
    elif i=="accept":
        checks["same_draft"]=bool(preview) and days==preview
    elif i=="restore":
        checks["original_restored"]=days==fixture()["days"]
    else:
        card=days.get(key,{})
        old=before[key]
        expected={**old["contract"],**delta}
        checks["exact_contract"]=card.get("contract")==expected
        checks["unaffected_day"]=days.get("1" if key=="2" else "2")==before["1" if key=="2" else "2"]
        order=card.get("order",[])
        if i=="cap": good=len(order)==2 and "智民里" in order and order==[v for v in old["order"] if v in order]
        elif i=="swap": good=order==["江汉路","吉庆街","智民里"]
        elif i=="drop": good=order==["江汉路","黎黄陂路"]
        elif i=="ban": good=order==["黎黄陂路","智民里"]
        elif i=="stay": good=order==old["order"] and any(s["place"]=="昙华林" and s["end"]-s["start"]==90 for s in card["audit"]["stops"])
        else: good=order==old["order"] and card["audit"]["arrival"]<=900
        checks["minimal_effect"]=good
    if r["mode"] in ("edit","preview") and i not in ("accept","restore"):
        checks["card_to_answer"]=public_card(r)
    return checks

def run(out,only=None):
    rows=[]
    def record(id,q,expected,result,checks,elapsed):
        rows.append(dict(id=id,input=q,expect=expected,seconds=round(elapsed,2),checks=checks,
                         passed=all(checks.values()),result=result))
        out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
        print(id,rows[-1]["passed"],flush=True)
    with tempfile.TemporaryDirectory() as folder:
        agent=Agent(str(Path(folder)/"test.db"))
        server=ThreadingHTTPServer(("127.0.0.1",0),handler(agent))
        Thread(target=server.serve_forever,daemon=True).start()
        api=f"http://127.0.0.1:{server.server_port}"
        def call(sid,q):
            resp=requests.post(api+"/chat",json={"session":sid,"query":q},timeout=350)
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            return resp.json()
        draft=None
        try:
            for i,q,expect,mode,delta in CASES:
                if only and i not in only: continue
                sid="preview-chain" if i in ("preview","accept","restore") else i
                if i not in ("accept","restore"):
                    agent.store.save(sid,"fixture","fixture",0,fixture(),{})
                _,state,_=agent.store.read(sid,"read","read")
                start=time.monotonic()
                try:
                    r=call(sid,q)
                    checks=check(i,r,state["days"],mode,delta,agent,draft)
                    if i=="preview": draft=r.get("preview")
                    if i=="restore": checks["prerequisite_confirmed"]=any(v["id"]=="accept" and v["passed"] for v in rows)
                    if i=="accept": checks["prerequisite_preview"]=any(v["id"]=="preview" and v["passed"] for v in rows)
                    _,saved,_=agent.store.read(sid,"read","read")
                    checks["response_matches_storage"]=r["days"]==saved["days"] and r["facts"]==saved["facts"]
                except Exception as err:
                    r={"error":repr(err)};checks={"completed":False}
                record(i,q,expect,r,checks,time.monotonic()-start)
            previous={}
            for i,q in JOURNEY:
                if only and i not in only: continue
                start=time.monotonic()
                try:
                    r=call("fresh-visitor",q);s=r["answer"];days=r["days"];c=days.get("1",{}).get("contract",{})
                    if i=="j-city": checks={"three_towns":all(x in s for x in ("汉口","汉阳","武昌")),"locates_street":terms(s,"位于汉口","属于汉口","在汉口","汉口的","坐落于汉口"),"grounded":sources_valid(r,agent)}
                    elif i=="j-plan": checks={"origin":c.get("origin")=="江汉路","hours":(c.get("start"),c.get("end"))==(540,960),
                        "must":"智民里" in c.get("must",[]) and "智民里" in days.get("1",{}).get("order",[]),"visible":r["mode"]=="plan" and public_card(r)}
                    elif i=="j-community": checks={"relates_place":terms(s,"江岸","智民里"),"learning":terms(s,"订单","项目","实战"),"card_preserved":bool(previous) and days==previous,"grounded":sources_valid(r,agent)}
                    elif i=="j-event": checks={"required":all(x in s for x in ("简介","视频")),"form_destination":terms(s,"官网","报名表","报名页面","dlife.love"),"card_preserved":bool(previous) and days==previous,"grounded":sources_valid(r,agent)}
                    else: checks={"actual_card":r["mode"]=="edit" and len(days.get("1",{}).get("order",[]))<=2 and "智民里" in days.get("1",{}).get("order",[]),
                        "unchanged_constraints":bool(previous) and c=={**previous["1"]["contract"],"max_stops":2}}
                    previous=days
                except Exception as err:
                    r={"error":repr(err)};checks={"completed":False}
                record(i,q,"全新访客连续五轮，检查实际答复、引用和行程延续",r,checks,time.monotonic()-start)
        finally:
            server.shutdown();server.server_close()

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);p.add_argument("--only",nargs="+")
    a=p.parse_args();run(a.out,set(a.only or []))
