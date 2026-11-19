"""Live multiround test through the public Python entry point; fresh private session per run."""
import argparse
import json
from pathlib import Path
import tempfile
from agent import Agent

def run(out=None):
    turns=[
        ("新建","我住江汉路，帮我排半天汉口老建筑路线，早上九点出发，中午一点结束，智民里必须保留。"),
        ("改线","还是刚才那条路线，改成十点出发，其余条件照旧。"),
        ("假设","只是想看看：如果改成十点半出发呢？不要修改现在的行程。"),
        ("关系","记住我妈妈叫阿芳，她喜欢老建筑。我喜欢逛江滩。"),
        ("指代","我妈妈叫什么，她上次说喜欢什么？"),
        ("无解","智民里仍然必须去。改成十二点五十五从江汉路出发，下午一点前要结束。")]
    reports=[]
    with tempfile.TemporaryDirectory() as tmp:
        agent=Agent(str(Path(tmp)/"test.sqlite"))
        last=None
        for title,q in turns:
            r=agent.respond("visitor",q)
            card=r["days"].get("1",{})
            if title=="新建":
                ok=r["mode"]=="plan" and card.get("contract",{}).get("start")==540 and "智民里" in card.get("order",[])
            elif title=="改线":
                ok=r["mode"]=="edit" and card["contract"]["start"]==600 and card["contract"]["end"]==780 and "智民里" in card["order"]
            elif title=="假设":
                ok=r["mode"]=="preview" and r["days"]==last and r["preview"]["1"]["contract"]["start"]==630
            elif title=="关系":
                ok=any("阿芳" in str(f["object"])+f["subject"] for f in r["facts"])
            elif title=="指代":
                ok="阿芳" in r["answer"] and "老建筑" in r["answer"] and r["days"]==last
            else:
                ok=bool(last) and r["mode"]=="clarify" and r["days"]==last and any(
                    t.get("audit_error") for t in r["trace"])
            reports.append({"case":title,"passed":bool(ok),"input":q,"result":r})
            if out:
                out.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf8")
            last=r["days"]
        q="安排两天。第一天从江汉路出发，黎黄陂路一定要去。第二天从户部巷出发，昙华林一定要去。两天均是上午九点至下午四点。"
        first=agent.respond("two-days",q)
        days=first["days"]
        ok=(set(days)=={"1","2"} and days["1"]["contract"]["must"]==["黎黄陂路"] and
            days["2"]["contract"]["must"]==["昙华林"] and days["1"]["contract"]["origin"]=="江汉路"
            and days["2"]["contract"]["origin"]=="户部巷" and all(
               (d["contract"]["start"],d["contract"]["end"])==(540,960) and not d["contract"]["durations"]
               and not d["contract"]["windows"] and d["contract"]["destination"] is None for d in days.values()))
        reports.append({"case":"跨日对象绑定","passed":ok,"input":q,"result":first})
        q="只改第二天，十点才从户部巷出发。第一天完全照旧。"
        edit=agent.respond("two-days",q)
        ok=bool(ok and edit["mode"]=="edit" and edit["days"]["1"]==days["1"]
                and edit["days"]["2"]["contract"]["start"]==600)
        reports.append({"case":"局部更新不波及首日","passed":ok,"input":q,"result":edit})
        q="武汉人说的过早是什么意思？另外，数命SPU是什么意思？"
        answer=agent.respond("mixed",q)
        names={t.get("tool") for t in answer["trace"]}
        ok={"food","spu"}<=names and any(w in answer["answer"] for w in ("早餐","早点","早饭")) and any(
            w in answer["answer"] for w in ("超级个体","Super Person","价值创造"))
        reports.append({"case":"独立问题分别调用工具","passed":ok,"input":q,"result":answer})
    return reports

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    results=run(args.out)
    args.out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
    print([(r["case"],r["passed"]) for r in results])
    raise SystemExit(any(not r["passed"] for r in results))
