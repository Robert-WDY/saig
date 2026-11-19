"""Non-conversational acceptance: independent gold passages, component faults and handoffs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
from threading import Barrier
from unittest.mock import Mock,patch
import requests

from agent import Agent,apply_constraints
from audit_visitors import fixture, public_card, sources_valid
from ingest import read_pack
from knowledge import Knowledge, TOOLS, grounded
from model import Model
from planning import evaluate, solve, Invalid, new_contract
from semantics import compile_day
from storage import Conflict,Sessions

# Different failure signatures: ambiguity of entities, current-vs-planned status, responsibility,
# selection pipeline, primary article vs product names, allergy uncertainty, actionable route order, CRS.
PROBES=[
 ("wuhan","长江和汉江在这里交汇，武汉三镇有哪些？",("towns","overview.1."),("汉口","武昌","汉阳")),
 ("community","体验区是已经天天开放，还是社区的规划？",("community.6.",),("规划","体验")),
 ("spu","交付后出了问题谁负责修正？",("spu.11.",),("责任","纠正")),
 ("saig","我的视频没拿到前十八名，还有哪些赛区选拔名额？",("selection",),("赛区","30","18")),
 ("attraction","黄鹤楼",("book.6.1",),("1985","蛇山")),
 ("food","有过敏原要跟店家确认吗？武汉早餐",("breakfast",),("过敏原","确认")),
 ("guide","我想在汉口过早，再看老建筑，体力不好可以少去哪里？",("oldtown",),("黎黄陂路","山海关路")),
]

def run(out,base):
    agent=Agent(":memory:")  # Database functions use an on-disk private store in the state tests.
    k=agent.kb
    rows=[]
    def record(name,level,expected,test):
        try:
            ok,observed=test()
        except Exception as exc:
            ok,observed=False,repr(exc)
        rows.append(dict(id=name,level=level,expected=expected,passed=bool(ok),observed=observed))
    def post(tool,q):
        r=requests.post(base+"/tool",json={"tool":tool,"query":q},timeout=15)
        r.raise_for_status()
        return r.json()
    for name,q,ids,terms in PROBES:
        def check():
            found=post(name,q)
            hits=[r for r in found if any(r["id"].startswith(i) for i in ids) and all(w in r["text"] for w in terms)]
            return (bool(hits) and all(r["category"] in TOOLS[name] and r["source"] and r["locator"]
                    for r in found) and (name!="attraction" or found[0]["id"]=="book.6.1"),
                    {"input":q,"ranked":[r["id"] for r in found],"support":[r["text"] for r in hits]})
        record(name,"工具HTTP","指定来源含全部必要信息；结果类型和定位有效",check)
    def location():
        p=post("location","汉口站")["catalog"][0]; unknown=post("location","未核实的红杯子门口")
        return (p["point"]["crs"]=="WGS84" and abs(p["point"]["lat"]-30.62158)<.001 and
                abs(p["point"]["lon"]-114.24895)<.001 and p["evidence"] in k.by_id and
                not unknown["catalog"] and not unknown["geocodes"],{"poi":p,"unknown":unknown})
    record("location","工具HTTP","已知地标点、坐标系、来源；未知地址不可冒充已定位",location)
    def import_back():
        path=Path(tempfile.gettempdir())/"saig-competition-materials.zip"
        imported=read_pack(path)
        stored=[r for r in k.rows if r["edition"]=="赛事中文资料包"]
        return (imported==stored and len({r["id"] for r in stored})==len(stored),
                {"source_zip":path.name,"imported":len(imported),"persisted":len(stored)})
    record("import_is_repeatable","采集→索引","从官方原 ZIP 重新抽取后的正文、页段、ID、顺序与落库完全一致",import_back)
    def corrupt_claim():
        model=Mock()
        model.ask.side_effect=[{"claims":[{"key":"fake","text":"编造"}]},
                               {"claims":[{"key":"fake","text":"另一份资料"}]},{"key":"NONE"}]
        a=grounded(model,"可以保证入场吗？",[k.by_id["venue"]])
        return (not a["supported"] and not a["citations"] and "编造" not in a["answer"],a)
    record("orphan_citation","回答模型→引用审核","模型给了检索以外的引文，不能带引用发布",corrupt_claim)
    def revisions():
        doc={"id":"notice","source":"fixture:announcement","title":"测试公告","locator":"已核对","edition":"测试环境"}
        results=[]
        for text in ("样例服务本月需提前预约。","样例服务本月可直接到访。"):
            results.append(grounded(agent.model,"这个月到访需要提前预约吗？",[{**doc,"text":text}]))
        return (all(v["supported"] and v["citations"][0]["quote"]==t for v,t in
              zip(results,["样例服务本月需提前预约。","样例服务本月可直接到访。"])) and
              "预约" in results[0]["answer"] and any(w in results[1]["answer"] for w in ("直接","无需","不需")),results)
    record("changed_source","RAG生成·真实模型","同一问题、同一证据ID，替换权威原文后结论随之翻转",revisions)
    def compiler():
        raw={"query":"旧城","changes":[{"field":"window","target":"智民里","value":"11:00-12:00","quote":"十一点到十二点"},
            {"field":"exclude","value":"江汉路","target":"","quote":"不逛江汉路"}]}
        q="不逛江汉路，智民里十一点到十二点。"
        op=compile_day(raw,1,q)
        old=fixture()["days"]["1"]["contract"]
        c=apply_constraints(old,op)
        return (c=={**old,"windows":{"智民里":[660,720]},"exclude":["江汉路"]} and not old["exclude"],{"op":op,"contract":c})
    record("semantic_units","语义操作→程序合同","时间窗绑定引用对象，排除游览保留同名起点；输入合同不可变",compiler)
    def bad_proof():
        try: compile_day({"query":"","changes":[{"field":"duration","target":"智民里","value":2,"quote":"两天"}]},1,"留两天")
        except ValueError as e: return True,str(e)
        return False,"接受把天数作为单站分钟数"
    record("dimension","原文→类型审核","数值相同但单位不同，拒绝错绑",bad_proof)
    def timecalc():
        c={**new_contract(),"start":600,"origin":"江汉路","destination":"汉口站","end":810,"buffer":30,
           "must":["智民里"],"windows":{"智民里":[680,725]}}
        a=evaluate(c,["黎黄陂路","智民里"])
        b=evaluate({**c,"end":809},["黎黄陂路","智民里"])
        # 10:00 +25 +35 +25=11:25; visit until 12:05, station at 13:05 +30=13:35.
        # The independent deadline oracle is 815. Check both sides of it.
        exact=evaluate({**c,"end":815},["黎黄陂路","智民里"])
        short=evaluate({**c,"end":814},["黎黄陂路","智民里"])
        return (a["stops"][-1]["start"]==685 and a["arrival"]==785 and bool(a["violations"]) and
                bool(b["violations"]) and not exact["violations"] and bool(short["violations"]),
                {"arrival":a["arrival"],"edge":exact["violations"],"late":short["violations"]})
    record("station_window","路段→排程审核","独立手算转场、站内余量、闭馆上限与临界点",timecalc)
    def conflicting():
        c={**new_contract(),"origin":"江汉路","must":["智民里"],"exclude":["黎黄陂路"]}
        try: solve(c,["智民里"],[],add=["黎黄陂路"])
        except Invalid as e: return True,str(e)
        return False,"提交了互相冲突的用户修改"
    record("op_conflict","增量操作→求解","新增站与持久排除相撞，求解不得吃掉任一要求",conflicting)
    def adapter():
        def reply(content):
            resp=Mock();resp.json.return_value={"choices":[{"finish_reason":"stop","message":{"content":content}}]}
            return resp
        with patch("model.requests.post",side_effect=[reply("{"),reply('{"answer":"恢复"}')]) as net:
            val=Model().ask("测试",{"query":"q"})
            return val=={"answer":"恢复"} and net.call_count==2,{"attempts":net.call_count,"value":val}
    record("model_retry","模型适配器·故障注入","截断的JSON不能进入业务；成功重试才能返回",adapter)
    def race():
        with tempfile.TemporaryDirectory() as td:
            p=str(Path(td)/"db");s=Sessions(p);barrier=Barrier(2)
            def write(who):
                rev,state,_=s.read("visitor",who,who);barrier.wait()
                state["facts"].append(who)
                try: s.save("visitor",who,who,rev,state,{"who":who});return "committed"
                except Conflict: return "conflict"
            with ThreadPoolExecutor(2) as pool: result=list(pool.map(write,["a","b"]))
            rev,state,_=Sessions(p).read("visitor","x","x")
            return sorted(result)==["committed","conflict"] and rev==1 and len(state["facts"])==1,{"threads":result,"durable":state}
    record("concurrent_commit","持久化·并发","同基线并发编辑只能提交一个，重开连接后读取获胜者",race)
    def transport():
        from serve import handler
        from threading import Thread
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as td:
            a=Agent(str(Path(td)/"db"),kb=k)
            server=ThreadingHTTPServer(("127.0.0.1",0),handler(a));Thread(target=server.serve_forever,daemon=True).start()
            try:
                url=f"http://127.0.0.1:{server.server_port}/chat"
                payload={"session":"s","request_id":"1","query":"测试重试"}
                with patch.object(a,"understand",side_effect=requests.Timeout("injected")):
                    failure=requests.post(url,json=payload,timeout=5)
                rev=a.store.read("s","1","测试重试")[0]
                with patch.object(a,"understand",return_value={"mode":"clarify","question":"哪一天？"}):
                    success=requests.post(url,json=payload,timeout=5)
                    retry=requests.post(url,json=payload,timeout=5)
                    conflict=requests.post(url,json={**payload,"query":"另一请求"},timeout=5)
                return (failure.status_code==503 and rev==0 and success.status_code==200 and
                        success.json()==retry.json() and conflict.status_code==409),[failure.status_code,rev,success.status_code,retry.status_code,conflict.status_code]
            finally: server.shutdown();server.server_close()
    record("transport_recovery","HTTP→事务→重试","服务超时不落半成品，原请求能重试且只提交一次；复用ID换输入返回409",transport)
    def detectors():
        base=fixture()["days"];card=deepcopy(base["1"])
        card["audit"]["stops"][0]["end"]=card["audit"]["stops"][0]["start"]-1
        forged={"trace":[{"affected_days":[{"day":1}]}],"days":{"1":card},"mode":"edit","answer":"照旧"}
        cite={"trace":[{"hits":["towns"]}],"citations":[{"id":"venue","quote":"智民里","claim":"在这里"}],"answer":"在这里"}
        return not public_card(forged) and not sources_valid(cite,agent),{"bad_card_rejected":not public_card(forged),"foreign_citation_rejected":not sources_valid(cite,agent)}
    record("red_team_oracles","评测器自检","故意放入倒走的钟点和外来引用，应检出两类错误",detectors)
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
    print([(r["id"],r["passed"]) for r in rows])
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True);p.add_argument("--base",default="http://127.0.0.1:18943")
    a=p.parse_args();run(a.out,a.base)
