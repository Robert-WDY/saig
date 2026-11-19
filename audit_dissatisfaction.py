"""Held-out dissatisfaction journeys. Each one attacks a separate kind of failure."""
import argparse
import json
from pathlib import Path
import tempfile
import time
from agent import Agent
from audit_visitors import fixture, sources_valid

def run(out):
    rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        a=Agent(str(Path(tmp)/"sessions.sqlite"))
        def turn(sid,name,question,description,check):
            start=time.monotonic()
            try:
                before=a.store.read(sid,"audit","audit")[1]
                r=a.respond(sid,question)
                passed=check(r,before)
            except Exception as err:
                passed=False;r={"error":repr(err)}
            rows.append({"id":name,"question":question,"expected":description,"passed":bool(passed),
                         "result":r,"seconds":round(time.monotonic()-start,2)})
            out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
        turn("critic","first","说说数命 SPU 的意思，我总觉得它是个积分。",
             "用资料说明SPU的含义",lambda r,b:sources_valid(r,a) and any(w in r["answer"] for w in ("超级个体","Super Person","责任主体")))
        turn("critic","challenge","这个解释我不满意。你说的 SPU 到底谁为交付担责？给我支持这句话的出处。",
             "知识答复被质疑，须重新取证到交付责任段，不能误改行程",
             lambda r,b:r["mode"]=="info" and not r["days"] and sources_valid(r,a) and
               any("责任" in c["quote"] and c["id"].startswith("spu.") for c in r["citations"]) and "责任" in r["answer"])
        a.store.save("choice","seed","seed",0,fixture(),{})
        turn("choice","conflict","我对第一天不满意。三站一站也不能删，但全天最多只能去两个地方。这两条都是硬要求。",
             "指出两个要求互斥，请游客选择放宽哪一条，保持原卡",
             lambda r,b:r["mode"]=="clarify" and r["days"]==b["days"] and
               any(w in r["answer"] for w in ("冲突","矛盾","无法同时","不能同时","只能保留")) and
               any(w in r["answer"] for w in ("三","3")) and any(w in r["answer"] for w in ("两","二","2")))
        turn("choice","withdraw","那就不要两站上限了。我想按原来三站走，今天不用改。",
             "撤回从未生效的要求，不能把新上限或待处理预览偷偷写入",
             lambda r,b:r["days"]==fixture()["days"] and not r["preview"] and
                        not a.store.read("choice","audit","audit")[1].get("pending_days"))
        a.store.save("soft","seed","seed",0,fixture(),{})
        turn("soft","delegated_choice","第一天第二站的建筑我兴趣不大，帮我换一处能过早吃东西的地方，我没指定哪家。智民里还去。",
             "把明确的换站权限给系统；用美食资料支持替代，保留未涉及对象、排序和另一日",
             lambda r,b:r["mode"]=="edit" and r["days"]["2"]==b["days"]["2"] and
               r["days"]["1"]["contract"]==b["days"]["1"]["contract"] and
               (lambda o:len(o)==3 and o[0]=="江汉路" and o[-1]=="智民里" and o[1] in ("吉庆街","山海关路","户部巷","粮道街"))(r["days"]["1"]["order"]) and
               any(t.get("tool")=="guide" and t.get("hits") for t in r["trace"]))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path)
    run(p.parse_args().out)
