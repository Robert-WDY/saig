"""Fresh, stateful black-box acceptance. Authored before the repair, independent of model prompts."""
import argparse
import json
from pathlib import Path
import tempfile
from agent import Agent
from audit_visitors import fixture

def run(out,batch):
    with tempfile.TemporaryDirectory() as tmp:
        a=Agent(str(Path(tmp)/"visitor.db"))
        rows=[]
        def visit(sid,name,question,judge):
            _,s,_=a.store.read(sid,"inspect","inspect")
            try:
                r=a.respond(sid,question)
                passed=bool(judge(r,s)) and r["days"]==a.store.read(sid,"inspect","inspect")[1]["days"]
            except Exception as e:
                r={"error":repr(e)};passed=False
            rows.append({"case":name,"input":question,"passed":passed,"result":r})
            out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
        def seed(sid): a.store.save(sid,"seed","seed",0,fixture(),{})
        if batch=="A":
            seed("desk")
            visit("desk","异日同句双改","我想同时改两天。第一天改从十点半出门；第二天户部巷逛半小时。其他都保留。",
                  lambda r,s:r["mode"]=="edit" and r["days"]["1"]["contract"]=={**s["days"]["1"]["contract"],"start":630} and
                  r["days"]["2"]["contract"]=={**s["days"]["2"]["contract"],"durations":{"户部巷":30}})
            visit("desk","讨论之后读回修改","不用动路线了，帮我回忆一下第二天户部巷我刚留了多少分钟？",
                  lambda r,s:r["days"]==s["days"] and any(w in r["answer"] for w in ("30","三十","半小时")) and not r["citations"])
            visit("map","从地址切换到意义","我已经知道数命社区的地址了。我问的是 SPU 这个缩写展开写是什么？顺带问，武汉人把吃早饭叫啥？",
                  lambda r,s:{"food","spu"}<={t.get("tool") for t in r["trace"]} and "super person unit" in r["answer"].lower() and "过早" in r["answer"])
            seed("ticket")
            visit("ticket","预览后插入知识问答","假设第二天晚一个小时出发，先试排，不要确定。",
                  lambda r,s:r["mode"]=="preview" and r["days"]==s["days"] and r["preview"]["2"]["contract"]["start"]==600)
            visit("ticket","预览间隙咨询","等待朋友答复时，我想问 SAIG 一个人能参加吗？",
                  lambda r,s:r["days"]==s["days"] and any(c["id"]=="register" for c in r["citations"]))
            visit("ticket","跨话题采纳试排","朋友到了，刚才试排的那版我们确定了。",
                  lambda r,s:bool(s.get("pending_days")) and r["mode"]=="edit" and r["days"]==s["pending_days"])
        else:
            seed("inspector")
            visit("inspector","负向约束读回","我暂时不改。原定行程里，第二天哪些地方非去不可？",
                  lambda r,s:r["days"]==s["days"] and "昙华林" in r["answer"] and not r["citations"])
            visit("inspector","两项作用于同一对象","第二天保留昙华林，那里我想下午两点到三点之间去，待四十分钟再走。",
                  lambda r,s:r["days"]["1"]==s["days"]["1"] and r["days"]["2"]["contract"]=={
                    **s["days"]["2"]["contract"],"windows":{"昙华林":[840,900]},"durations":{"昙华林":40}})
            visit("novice","两个同域问题需不同文档","接待员作品按几项功能打分？再问个报名手续，项目主页是必填的吗？",
                  lambda r,s:{"register","challenge"}<={c["id"] for c in r["citations"]} and
                         any(w in r["answer"] for w in ("四","4")) and any(w in r["answer"] for w in ("选填","可选","非必","不是必")))
            seed("guide")
            visit("guide","删除游览但保留当天出发时刻","第一天我还在江汉路出发，不过黎黄陂路只在这次删掉，别记成我不喜欢这里。",
                  lambda r,s:r["days"]["1"]["order"]==["江汉路","智民里"] and r["days"]["1"]["contract"]==s["days"]["1"]["contract"] and not r["facts"])
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("batch",choices=["A","B"]);p.add_argument("--out",required=True,type=Path)
    args=p.parse_args();run(args.out,args.batch)
